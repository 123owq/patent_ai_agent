from __future__ import annotations
from datetime import datetime
from typing import Callable
from patent_agent.llm.base import LLMClient
from patent_agent.models.input import PatentDoc, OfficeActionRaw, PriorArtDoc
from patent_agent.models.analysis import AnalysisResult
from patent_agent.models.output import SpecMappingResult, ToolError
from patent_agent.tools.tool1_parse_office_action import (
    parse_office_action,
    extract_examiner_chart,
)
from patent_agent.tools.tool2_parse_claims import parse_claims
from patent_agent.tools.tool3_map_spec import map_spec_to_elements
from patent_agent.tools.tool4_claim_chart import build_claim_chart
from patent_agent.tools.tool5_strategy import analyze_diff_and_strategy
from patent_agent.tools.tool6_amendment import generate_amendments, validate_spec_basis
from patent_agent.core.storage import save_analysis


def run_analysis(
    patent: PatentDoc,
    office_action_raw: OfficeActionRaw,
    prior_arts: list[PriorArtDoc],
    llm: LLMClient,
    progress_cb: Callable[[str, float], None] | None = None,
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
    chart_result = build_claim_chart(target_claims, prior_arts, examiner_chart, llm)

    _cb("공격·방어 전략 생성", 0.65)
    strategy = analyze_diff_and_strategy(chart_result, oa_result, spec_mapping, llm)

    _cb("보정청구항 생성", 0.85)
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
        created_at=datetime.now(),
        version=1,
        source_files={},
        errors=errors,
        office_action=oa_result,
        claim_parse=claims_result,
        spec_mapping=spec_mapping,
        claim_chart=chart_result,
        strategy=strategy,
        amendment=amendment,
    )
    save_analysis(result)
    _cb("완료", 1.0)
    return result
