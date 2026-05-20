"""Tool 2~6 단위 테스트"""
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from patent_agent.tools.tool2_parse_claims import parse_claims
from patent_agent.tools.tool3_map_spec import map_spec_to_elements
from patent_agent.tools.tool4_claim_chart import build_claim_chart
from patent_agent.tools.tool5_strategy import analyze_diff_and_strategy
from patent_agent.tools.tool6_amendment import generate_amendments, validate_spec_basis
from patent_agent.models.input import PriorArtDoc
from patent_agent.models.output import (
    Claim, ClaimElement, ClaimParseResult,
    ClaimChart, ClaimChartResult, ClaimChartRow, ExaminerChart, ExaminerChartRow,
    OfficeActionResult,
    SpecMappingResult, ElementSpecMapping,
    Strategy, StrategyResult,
    AmendedClaim, AmendmentDraft, AmendmentResult,
)


# ── 공통 픽스처 ────────────────────────────────────────────────────
def _make_claim_parse() -> ClaimParseResult:
    return ClaimParseResult(
        application_number="10-test",
        total_claims=1,
        independent_claims=[1],
        dependent_claims=[],
        claims=[Claim(
            claim_number=1,
            claim_type="독립항",
            original_text="원본 텍스트",
            elements=[
                ClaimElement(element_id="1-A", element_order=1,
                             text="웨트 마스터 배치 50~200중량부", label="원료고무"),
            ],
        )],
    )


def _make_prior_art() -> PriorArtDoc:
    return PriorArtDoc(
        application_number="10-2012-0097198",
        title="인용발명1",
        abstract="",
        claims={1: "폴리머 라텍스..."},
        spec_paragraphs={"0001": "본 발명은..."},
        prior_art_id="인용발명1",
        publication_number="10-2014-0030706",
    )


def _make_strategy(t: str) -> Strategy:
    return Strategy(strategy_type=t, rationale="test",
                    leveraged_differences=["1-A"], proposed_action="test")


def _make_chart_result() -> ClaimChartResult:
    return ClaimChartResult(charts=[ClaimChart(
        target_claim_number=1,
        rows=[ClaimChartRow(
            element_id="1-A", element_text="웨트 마스터 배치",
            prior_art_id="인용발명1", our_match="차이", our_explanation="수치 범위 상이",
        )],
    )])


# ── Tool 2 ────────────────────────────────────────────────────────
def _make_examiner_chart() -> ExaminerChart:
    return ExaminerChart(rows=[
        ExaminerChartRow(
            comparison_id="C0001",
            claim_number=1,
            element_label="구성1",
            our_claim_text="웨트 마스터 배치: 50-200중량부",
            prior_art_text="웨트 마스터 배치: 130-180중량부",
            prior_art_id="인용발명1",
            examiner_match="차이",
            prior_art_location="청구항 1",
        )
    ])


def _make_assessment_result():
    return SimpleNamespace(assessments=[
        SimpleNamespace(
            comparison_id="C0001",
            our_match="차이",
            our_explanation="수치 범위가 다릅니다.",
            prior_art_element="웨트 마스터 배치: 130-180중량부",
            prior_art_location="청구항 1",
            disagreement_rationale=None,
        )
    ])


def test_tool2_parse_claims_calls_llm():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = _make_claim_parse()
    result = parse_claims("10-test", {1: "웨트 마스터 배치..."}, mock_llm)
    mock_llm.generate.assert_called_once()
    assert result.total_claims == 1
    assert 1 in result.independent_claims


# ── Tool 3 ────────────────────────────────────────────────────────
def test_tool3_map_spec_calls_llm():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = SpecMappingResult(mappings=[
        ElementSpecMapping(element_id="1-A", paragraph_ids=["0008"],
                           rationale="단락 0008에 기재됨", confidence=0.9),
    ])
    result = map_spec_to_elements(_make_claim_parse(),
                                  {"0008": "웨트 마스터 배치..."}, mock_llm)
    mock_llm.generate.assert_called_once()
    assert result.mappings[0].element_id == "1-A"


def test_tool3_spec_basis_paragraphs_exist_in_spec():
    """매핑된 단락 ID가 실제 명세서에 존재해야 함"""
    spec = {"0008": "text"}
    mapping = ElementSpecMapping(element_id="1-A", paragraph_ids=["0008"],
                                 rationale="ok", confidence=0.9)
    for para_id in mapping.paragraph_ids:
        assert para_id in spec


# ── Tool 4 ────────────────────────────────────────────────────────
def test_tool4_build_claim_chart_calls_llm():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = _make_assessment_result()
    claims = _make_claim_parse()
    result = build_claim_chart(claims.claims, [_make_prior_art()], _make_examiner_chart(), mock_llm)
    assert mock_llm.generate.call_count == 1
    assert len(result.charts) == 1


def test_tool4_with_multiple_prior_arts():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = _make_assessment_result()
    claims = _make_claim_parse()
    prior_arts = [_make_prior_art(), _make_prior_art()]
    result = build_claim_chart(claims.claims, prior_arts, _make_examiner_chart(), mock_llm)
    assert mock_llm.generate.call_count == 2


# ── Tool 5 ────────────────────────────────────────────────────────
def test_tool4_uses_fixed_examiner_rows_as_comparison_basis():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = SimpleNamespace(assessments=[
        SimpleNamespace(
            comparison_id="C0001",
            our_match="차이",
            our_explanation="수치 범위가 다릅니다.",
            prior_art_element="웨트 마스터 배치: 130-180중량부",
            prior_art_location="청구항 1",
            disagreement_rationale=None,
        )
    ])
    claims = _make_claim_parse()
    examiner_chart = ExaminerChart(rows=[
        ExaminerChartRow(
            comparison_id="C0001",
            claim_number=1,
            element_label="구성1",
            our_claim_text="웨트 마스터 배치: 50-200중량부",
            prior_art_text="웨트 마스터 배치: 130-180중량부",
            prior_art_id="인용발명1",
            examiner_match="차이",
            prior_art_location="청구항 1",
        )
    ])

    result = build_claim_chart(claims.claims, [_make_prior_art()], examiner_chart, mock_llm)

    assert mock_llm.generate.call_count == 1
    row = result.charts[0].rows[0]
    assert row.comparison_id == "C0001"
    assert row.element_id == "구성1"
    assert row.element_text == "웨트 마스터 배치: 50-200중량부"
    assert row.prior_art_id == "인용발명1"
    assert row.prior_art_element == "웨트 마스터 배치: 130-180중량부"
    assert row.examiner_match == "차이"
    assert row.our_match == "차이"


def test_tool4_matches_comparison_id_case_insensitively():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = SimpleNamespace(assessments=[
        SimpleNamespace(
            comparison_id="c0001",
            our_match="차이",
            our_explanation="수치 범위가 다릅니다.",
            prior_art_element="웨트 마스터 배치: 130-180중량부",
            prior_art_location="청구항 1",
            disagreement_rationale=None,
        )
    ])

    result = build_claim_chart(_make_claim_parse().claims, [_make_prior_art()], _make_examiner_chart(), mock_llm)

    row = result.charts[0].rows[0]
    assert row.comparison_id == "C0001"
    assert row.our_match == "차이"


def test_tool5_strategy_calls_llm():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = StrategyResult(
        offensive=_make_strategy("공격"),
        defensive=_make_strategy("방어"),
    )
    result = analyze_diff_and_strategy(
        _make_chart_result(),
        OfficeActionResult(application_number="t", rejection_reasons=[],
                           rejected_claim_numbers=[], cited_arts=[]),
        SpecMappingResult(mappings=[]),
        mock_llm,
    )
    assert result.offensive.strategy_type == "공격"
    assert result.defensive.strategy_type == "방어"


# ── Tool 6 ────────────────────────────────────────────────────────
def test_tool6_generate_amendments_calls_llm_twice():
    mock_llm = MagicMock()
    draft = AmendmentDraft(strategy_type="공격", amended_claims=[
        AmendedClaim(claim_number=1, original_text="orig", amended_text="orig",
                     diff_summary="원문 유지", spec_basis=[]),
    ], overall_explanation="ok")
    mock_llm.generate.return_value = AmendmentResult(
        offensive_draft=draft,
        defensive_draft=AmendmentDraft(strategy_type="방어", amended_claims=[],
                                       overall_explanation="ok"),
    )
    result = generate_amendments(
        StrategyResult(offensive=_make_strategy("공격"),
                       defensive=_make_strategy("방어")),
        _make_claim_parse(),
        SpecMappingResult(mappings=[]),
        mock_llm,
    )
    assert mock_llm.generate.call_count == 2  # 공격 + 방어
    assert result.offensive_draft.strategy_type == "공격"
    assert result.defensive_draft.strategy_type == "방어"


def test_tool6_filters_invalid_spec_basis_after_generation():
    mock_llm = MagicMock()
    offensive_draft = AmendmentDraft(strategy_type="공격", amended_claims=[
        AmendedClaim(
            claim_number=1,
            original_text="orig",
            amended_text="orig",
            diff_summary="원문 유지",
            spec_basis=["0008", "9999", ""],
        ),
    ], overall_explanation="ok")
    defensive_draft = AmendmentDraft(strategy_type="방어", amended_claims=[
        AmendedClaim(
            claim_number=1,
            original_text="orig",
            amended_text="orig amended",
            diff_summary="한정 추가",
            spec_basis=["0008", "9999", ""],
        ),
    ], overall_explanation="ok")
    mock_llm.generate.side_effect = [
        AmendmentResult(
            offensive_draft=offensive_draft,
            defensive_draft=AmendmentDraft(strategy_type="방어", amended_claims=[], overall_explanation=""),
        ),
        AmendmentResult(
            offensive_draft=AmendmentDraft(strategy_type="공격", amended_claims=[], overall_explanation=""),
            defensive_draft=defensive_draft,
        ),
    ]

    result = generate_amendments(
        StrategyResult(offensive=_make_strategy("공격"), defensive=_make_strategy("방어")),
        _make_claim_parse(),
        SpecMappingResult(mappings=[]),
        mock_llm,
        spec_paragraphs={"0008": "valid paragraph"},
    )

    assert result.offensive_draft.amended_claims[0].spec_basis == ["0008"]
    assert result.defensive_draft.amended_claims[0].spec_basis == ["0008"]


def test_tool6_validate_spec_basis_passes():
    spec = {"0008": "text1"}
    amended = AmendedClaim(claim_number=1, original_text="o", amended_text="a",
                           diff_summary="d", spec_basis=["0008"])
    errors = validate_spec_basis([amended], spec)
    assert errors == []


def test_tool6_validate_spec_basis_fails():
    spec = {"0008": "text1"}
    amended = AmendedClaim(claim_number=1, original_text="o", amended_text="a",
                           diff_summary="d", spec_basis=["9999"])
    errors = validate_spec_basis([amended], spec)
    assert len(errors) == 1
    assert "9999" in errors[0]
