from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
from patent_agent.models.output import (
    OfficeActionResult,
    ClaimParseResult,
    SpecMappingResult,
    ClaimChartResult,
    StrategyResult,
    AmendmentResult,
    ToolError,
    ClaimConclusionResult,
)


class AnalysisResult(BaseModel):
    analysis_id: str
    application_number: str
    llm_model: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    version: int = 1
    source_files: dict[str, str] = {}
    errors: list[ToolError] = []
    office_action: OfficeActionResult
    claim_parse: ClaimParseResult
    spec_mapping: SpecMappingResult
    claim_chart: ClaimChartResult
    strategy: StrategyResult
    amendment: AmendmentResult
    claim_conclusion: ClaimConclusionResult | None = None


class EditLogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    target_path: str
    before: str
    after: str
    source: Literal["user-direct", "llm-proposed-user-applied", "regenerate"]
    user_instruction: str | None = None
