from patent_agent.llm.base import LLMClient
from patent_agent.models.output import (
    ClaimChartResult,
    OfficeActionResult,
    SpecMappingResult,
    StrategyResult,
)
from patent_agent.core.prompts import render


def analyze_diff_and_strategy(
    claim_chart: ClaimChartResult,
    office_action: OfficeActionResult,
    spec_mapping: SpecMappingResult,
    llm: LLMClient,
    user_instruction: str | None = None,
) -> StrategyResult:
    prompt = render(
        "tool5.j2",
        claim_charts=claim_chart.charts,
        rejection_reasons=office_action.rejection_reasons,
        spec_mappings=spec_mapping.mappings,
        user_instruction=user_instruction,
    )
    return llm.generate(prompt, schema=StrategyResult, temperature=0.0)
