from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


# ── Tool 1 출력 ──────────────────────────────────────────────────────
class RejectionReason(BaseModel):
    article: str
    rejection_type: Literal["진보성", "신규성", "기재불비", "기타"]
    target_claim_numbers: list[int]
    cited_art_ids: list[str]
    examiner_reasoning: str


class CitedArtRef(BaseModel):
    cited_art_id: str
    document_number: str


class OfficeActionResult(BaseModel):
    application_number: str
    rejection_reasons: list[RejectionReason]
    rejected_claim_numbers: list[int]
    cited_arts: list[CitedArtRef]


# ── Tool 2 출력 ──────────────────────────────────────────────────────
class ClaimElement(BaseModel):
    element_id: str                   # "1-A", "1-B"
    element_order: int
    text: str
    label: str | None = None


class Claim(BaseModel):
    claim_number: int
    claim_type: Literal["독립항", "종속항"]
    depends_on: list[int] = []
    preamble: str | None = None
    original_text: str
    elements: list[ClaimElement]


class ClaimParseResult(BaseModel):
    application_number: str
    total_claims: int
    independent_claims: list[int]
    dependent_claims: list[int]
    claims: list[Claim]


# ── Tool 3 출력 ──────────────────────────────────────────────────────
class ElementSpecMapping(BaseModel):
    element_id: str
    paragraph_ids: list[str]
    rationale: str
    confidence: float


class SpecMappingResult(BaseModel):
    mappings: list[ElementSpecMapping]


# ── Tool 4 보조 + 출력 ────────────────────────────────────────────────
class ExaminerChartRow(BaseModel):
    element_label: str
    our_claim_text: str
    prior_art_text: str
    prior_art_id: str
    examiner_match: Literal["동일", "유사", "차이"]
    note: str | None = None


class ExaminerChart(BaseModel):
    rows: list[ExaminerChartRow]


class ClaimChartRow(BaseModel):
    element_id: str
    element_text: str
    prior_art_id: str
    prior_art_element: str | None = None
    prior_art_location: str | None = None
    our_match: Literal["동일", "유사", "차이"]
    our_explanation: str
    examiner_match: Literal["동일", "유사", "차이"] | None = None
    examiner_explanation: str | None = None
    agreement: Literal["일치", "불일치"] | None = None
    disagreement_rationale: str | None = None


class ClaimChart(BaseModel):
    target_claim_number: int
    rows: list[ClaimChartRow]


class ClaimChartResult(BaseModel):
    charts: list[ClaimChart]


# ── Tool 5 출력 ──────────────────────────────────────────────────────
class Strategy(BaseModel):
    strategy_type: Literal["공격", "방어"]
    rationale: str
    leveraged_differences: list[str]
    proposed_action: str


class StrategyResult(BaseModel):
    offensive: Strategy
    defensive: Strategy


# ── Tool 6 출력 ──────────────────────────────────────────────────────
class AmendedClaim(BaseModel):
    claim_number: int
    original_text: str
    amended_text: str
    diff_summary: str
    spec_basis: list[str]


class AmendmentDraft(BaseModel):
    strategy_type: Literal["공격", "방어"]
    amended_claims: list[AmendedClaim]
    overall_explanation: str


class AmendmentResult(BaseModel):
    offensive_draft: AmendmentDraft
    defensive_draft: AmendmentDraft


# ── 에러 ─────────────────────────────────────────────────────────────
class ToolError(BaseModel):
    tool_name: str
    error_type: Literal["llm_failure", "validation_error", "timeout"]
    message: str
    is_fatal: bool
