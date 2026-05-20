from __future__ import annotations
from typing import Callable
from pydantic import BaseModel
from patent_agent.llm.base import LLMClient
from patent_agent.models.input import PriorArtDoc
from patent_agent.models.output import (
    Claim,
    ClaimChart,
    ClaimChartResult,
    ClaimChartRow,
    ExaminerChart,
    ExaminerChartRow,
)
from patent_agent.core.prompts import render


class FixedComparisonAssessment(BaseModel):
    comparison_id: str
    our_match: str
    our_explanation: str
    prior_art_element: str | None = None
    prior_art_location: str | None = None
    disagreement_rationale: str | None = None


class FixedComparisonAssessmentResult(BaseModel):
    assessments: list[FixedComparisonAssessment]


def _normalize_comparison_id(comparison_id: str) -> str:
    return comparison_id.strip().upper()


def _fixed_rows_for(
    examiner_chart: ExaminerChart | None,
    claim_number: int,
    prior_art_id: str,
) -> list[ExaminerChartRow]:
    if examiner_chart is None:
        return []
    return [
        row for row in examiner_chart.rows
        if row.claim_number == claim_number and row.prior_art_id == prior_art_id
    ]


def _merge_fixed_rows(
    claim: Claim,
    fixed_rows: list[ExaminerChartRow],
    assessments: list[FixedComparisonAssessment],
) -> ClaimChart:
    fixed_by_id = {
        _normalize_comparison_id(row.comparison_id): row
        for row in fixed_rows
        if row.comparison_id
    }
    assessment_by_id = {
        _normalize_comparison_id(row.comparison_id): row
        for row in assessments
    }

    missing = set(fixed_by_id) - set(assessment_by_id)
    extra = set(assessment_by_id) - set(fixed_by_id)
    if missing or extra:
        raise ValueError(
            "Tool4 comparison_id mismatch. "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )

    rows: list[ClaimChartRow] = []
    for fixed in fixed_rows:
        if fixed.comparison_id is None:
            raise ValueError("Tool4 fixed examiner row is missing comparison_id.")
        assessment = assessment_by_id[_normalize_comparison_id(fixed.comparison_id)]
        agreement = "일치" if assessment.our_match == fixed.examiner_match else "불일치"
        rows.append(ClaimChartRow(
            comparison_id=fixed.comparison_id,
            element_id=fixed.element_label,
            element_text=fixed.our_claim_text,
            prior_art_id=fixed.prior_art_id,
            prior_art_element=assessment.prior_art_element or fixed.prior_art_text,
            prior_art_location=assessment.prior_art_location or fixed.prior_art_location,
            our_match=assessment.our_match,
            our_explanation=assessment.our_explanation,
            examiner_match=fixed.examiner_match,
            examiner_explanation=fixed.prior_art_text,
            agreement=agreement,
            disagreement_rationale=(
                None if agreement == "일치" else assessment.disagreement_rationale
            ),
        ))

    return ClaimChart(target_claim_number=claim.claim_number, rows=rows)


def build_claim_chart(
    target_claims: list[Claim],
    prior_arts: list[PriorArtDoc],
    examiner_chart: ExaminerChart | None,
    llm: LLMClient,
    progress_cb: Callable[[int, int], None] | None = None,
) -> ClaimChartResult:
    all_charts: list[ClaimChart] = []
    total = len(prior_arts) * len(target_claims)
    done = 0

    for prior_art in prior_arts:
        for claim in target_claims:
            fixed_rows = _fixed_rows_for(examiner_chart, claim.claim_number, prior_art.prior_art_id)
            if fixed_rows:
                prompt = render(
                    "tool4.j2",
                    target_claim_number=claim.claim_number,
                    claim=claim,
                    prior_art=prior_art,
                    fixed_comparisons=fixed_rows,
                )
                partial = llm.generate(
                    prompt, schema=FixedComparisonAssessmentResult, temperature=0.0
                )
                all_charts.append(_merge_fixed_rows(claim, fixed_rows, partial.assessments))

            done += 1
            if progress_cb and total > 0:
                progress_cb(done, total)

    return ClaimChartResult(charts=all_charts)
