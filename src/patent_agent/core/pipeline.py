from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from typing import Callable
from patent_agent.llm.base import LLMClient
from patent_agent.models.input import PatentDoc, OfficeActionRaw, PriorArtDoc
from patent_agent.models.analysis import AnalysisResult
from patent_agent.models.output import (
    ClaimConclusionResult,
    ClaimChartResult,
    ClaimParseResult,
    OfficeActionResult,
    SpecMappingResult,
    ToolError,
)
from patent_agent.tools.tool1_parse_office_action import (
    parse_office_action,
    extract_examiner_chart,
)
from patent_agent.tools.tool2_parse_claims import parse_claims
from patent_agent.tools.tool3_map_spec import map_spec_to_elements
from patent_agent.tools.tool4_claim_chart import build_claim_chart
from patent_agent.tools.tool5_strategy import analyze_diff_and_strategy
from patent_agent.tools.tool6_amendment import generate_amendments, validate_spec_basis
from patent_agent.core.prompts import render
from patent_agent.core.storage import save_analysis


def _build_conclusion_items(rejection_reasons: list) -> list[dict]:
    by_claim: dict[int, dict[str, object]] = defaultdict(dict)
    for reason in rejection_reasons:
        rtype = reason.rejection_type
        for cn in reason.target_claim_numbers:
            by_claim[cn][rtype] = reason

    items: list[dict] = []
    for cn in sorted(by_claim.keys()):
        types = by_claim[cn]
        if "신규성" in types and "진보성" in types:
            r = types["신규성"]
            items.append({
                "claim_number": cn, "rejection_type": "신규성",
                "merged_from": ["신규성", "진보성"],
                "examiner_reasoning": r.examiner_reasoning,
                "cited_art_ids": r.cited_art_ids,
            })
            for rtype in sorted(t for t in types if t not in ("신규성", "진보성")):
                r2 = types[rtype]
                items.append({
                    "claim_number": cn, "rejection_type": rtype,
                    "merged_from": [],
                    "examiner_reasoning": r2.examiner_reasoning,
                    "cited_art_ids": r2.cited_art_ids,
                })
        else:
            for rtype in sorted(types.keys()):
                r = types[rtype]
                items.append({
                    "claim_number": cn, "rejection_type": rtype,
                    "merged_from": [],
                    "examiner_reasoning": r.examiner_reasoning,
                    "cited_art_ids": r.cited_art_ids,
                })
    return items


def _generate_claim_conclusion(
    oa_result: OfficeActionResult,
    claims_result: ClaimParseResult,
    chart_result: ClaimChartResult,
    llm: LLMClient,
) -> ClaimConclusionResult | None:
    items = _build_conclusion_items(oa_result.rejection_reasons)
    if not items:
        return None

    claims_by_number = {c.claim_number: c for c in claims_result.claims}
    charts_by_claim = {c.target_claim_number: c.rows for c in chart_result.charts}

    items_with_text = [
        {
            **item,
            "claim_text": getattr(claims_by_number.get(item["claim_number"]), "original_text", "(청구항 원문 없음)"),
            "prior_art_rows": charts_by_claim.get(item["claim_number"], []),
        }
        for item in items
    ]

    prompt = render(
        "claim_conclusion.j2",
        application_number=claims_result.application_number,
        items=items_with_text,
    )
    conclusion = llm.generate(prompt, schema=ClaimConclusionResult, temperature=0.0)

    merged_from_map = {
        (item["claim_number"], item["rejection_type"]): item["merged_from"]
        for item in items
    }
    for ci in conclusion.items:
        ci.merged_from = merged_from_map.get((ci.claim_number, ci.rejection_type), [])

    return conclusion


STEP_ORDER: list[str] = [
    "office_action",
    "claim_parse",
    "spec_mapping",
    "claim_chart",
    "claim_conclusion",
    "strategy",
    "amendment",
]


def run_analysis(
    patent: PatentDoc,
    office_action_raw: OfficeActionRaw,
    prior_arts: list[PriorArtDoc],
    llm: LLMClient,
    progress_cb: Callable[[str, float], None] | None = None,
    llm_model: str = "",
) -> AnalysisResult:
    errors: list[ToolError] = []
    _cb = progress_cb or (lambda s, r: None)

    _cb("통지서 분석", 0.0)
    oa_result = parse_office_action(office_action_raw, llm)

    _cb("청구항 파싱", 0.15)
    claims_result = parse_claims(patent.application_number, patent.claims, llm)

    _cb("상세설명 매핑", 0.30)
    try:
        spec_mapping = map_spec_to_elements(claims_result, patent.spec_paragraphs, llm)
    except Exception as e:
        errors.append(ToolError(
            tool_name="tool3_map_spec",
            error_type="llm_failure",
            message=str(e),
            is_fatal=False,
        ))
        spec_mapping = SpecMappingResult(mappings=[])

    _cb("Claim Chart 생성·검증", 0.45)
    examiner_chart = extract_examiner_chart(office_action_raw)
    target_claims = [
        c for c in claims_result.claims
        if c.claim_number in oa_result.rejected_claim_numbers
    ]

    def _tool4_cb(done: int, total: int) -> None:
        ratio = 0.45 + (done / total) * 0.18  # 0.45 → 0.63
        _cb(f"Claim Chart 생성·검증 ({done}/{total})", ratio)

    chart_result = build_claim_chart(target_claims, prior_arts, examiner_chart, llm, _tool4_cb)

    _cb("청구항별 최종 판단 생성", 0.65)
    claim_conclusion = _generate_claim_conclusion(oa_result, claims_result, chart_result, llm)

    _cb("공격·방어 전략 생성", 0.72)
    strategy = analyze_diff_and_strategy(chart_result, oa_result, spec_mapping, llm)

    _cb("보정청구항 생성", 0.86)
    amendment = generate_amendments(
        strategy,
        claims_result,
        spec_mapping,
        llm,
        spec_paragraphs=patent.spec_paragraphs,
    )

    # spec_basis validity check (자동 검증)
    for ac in amendment.defensive_draft.amended_claims:
        missing = [p for p in ac.spec_basis if p not in patent.spec_paragraphs]
        for para_id in missing:
            errors.append(ToolError(
                tool_name="tool6_amendment",
                error_type="validation_error",
                message=f"청구항 {ac.claim_number}: spec_basis '{para_id}'가 명세서에 없음",
                is_fatal=False,
            ))

    _cb("저장 중", 0.97)
    analysis_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{patent.application_number}"
    result = AnalysisResult(
        analysis_id=analysis_id,
        application_number=patent.application_number,
        llm_model=llm_model,
        created_at=datetime.now(),
        version=1,
        source_files={},
        errors=errors,
        office_action=oa_result,
        claim_parse=claims_result,
        spec_mapping=spec_mapping,
        claim_chart=chart_result,
        claim_conclusion=claim_conclusion,
        strategy=strategy,
        amendment=amendment,
    )
    save_analysis(result)
    _cb("완료", 1.0)
    return result


def run_from_step(
    step_name: str,
    existing: AnalysisResult,
    patent: PatentDoc,
    office_action_raw: OfficeActionRaw,
    prior_arts: list[PriorArtDoc],
    llm: LLMClient,
    progress_cb: Callable[[str, float], None] | None = None,
    llm_model: str = "",
) -> AnalysisResult:
    if step_name not in STEP_ORDER:
        raise ValueError(f"Unknown step: {step_name!r}. Valid: {STEP_ORDER}")

    start_idx = STEP_ORDER.index(step_name)
    _cb = progress_cb or (lambda s, r: None)
    errors: list[ToolError] = list(existing.errors)

    oa_result        = existing.office_action
    claims_result    = existing.claim_parse
    spec_mapping     = existing.spec_mapping
    chart_result     = existing.claim_chart
    claim_conclusion = existing.claim_conclusion
    strategy         = existing.strategy
    amendment        = existing.amendment

    if start_idx <= 0:
        _cb("통지서 분석", 0.0)
        oa_result = parse_office_action(office_action_raw, llm)

    if start_idx <= 1:
        _cb("청구항 파싱", 0.15)
        claims_result = parse_claims(patent.application_number, patent.claims, llm)

    if start_idx <= 2:
        _cb("상세설명 매핑", 0.30)
        try:
            spec_mapping = map_spec_to_elements(claims_result, patent.spec_paragraphs, llm)
        except Exception as e:
            errors.append(ToolError(
                tool_name="tool3_map_spec",
                error_type="llm_failure",
                message=str(e),
                is_fatal=False,
            ))
            spec_mapping = SpecMappingResult(mappings=[])

    if start_idx <= 3:
        _cb("Claim Chart 생성·검증", 0.45)
        examiner_chart = extract_examiner_chart(office_action_raw)
        target_claims = [
            c for c in claims_result.claims
            if c.claim_number in oa_result.rejected_claim_numbers
        ]

        def _tool4_cb(done: int, total: int) -> None:
            ratio = 0.45 + (done / total) * 0.18
            _cb(f"Claim Chart 생성·검증 ({done}/{total})", ratio)

        chart_result = build_claim_chart(target_claims, prior_arts, examiner_chart, llm, _tool4_cb)

    if start_idx <= 4:
        _cb("청구항별 최종 판단 생성", 0.65)
        claim_conclusion = _generate_claim_conclusion(oa_result, claims_result, chart_result, llm)

    if start_idx <= 5:
        _cb("공격·방어 전략 생성", 0.72)
        strategy = analyze_diff_and_strategy(chart_result, oa_result, spec_mapping, llm)

    if start_idx <= 6:
        _cb("보정청구항 생성", 0.86)
        amendment = generate_amendments(
            strategy,
            claims_result,
            spec_mapping,
            llm,
            spec_paragraphs=patent.spec_paragraphs,
        )
        for ac in amendment.defensive_draft.amended_claims:
            missing = [p for p in ac.spec_basis if p not in patent.spec_paragraphs]
            for para_id in missing:
                errors.append(ToolError(
                    tool_name="tool6_amendment",
                    error_type="validation_error",
                    message=f"청구항 {ac.claim_number}: spec_basis '{para_id}'가 명세서에 없음",
                    is_fatal=False,
                ))

    _cb("저장 중", 0.97)
    analysis_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{patent.application_number}"
    result = AnalysisResult(
        analysis_id=analysis_id,
        application_number=patent.application_number,
        llm_model=llm_model or existing.llm_model,
        created_at=existing.created_at,
        version=existing.version + 1,
        source_files=existing.source_files,
        errors=errors,
        office_action=oa_result,
        claim_parse=claims_result,
        spec_mapping=spec_mapping,
        claim_chart=chart_result,
        claim_conclusion=claim_conclusion,
        strategy=strategy,
        amendment=amendment,
    )
    save_analysis(result)
    _cb("완료", 1.0)
    return result
