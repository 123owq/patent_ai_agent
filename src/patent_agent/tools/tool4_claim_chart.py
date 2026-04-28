from patent_agent.llm.base import LLMClient
from patent_agent.models.input import PriorArtDoc
from patent_agent.models.output import Claim, ClaimChartResult, ExaminerChart
from patent_agent.core.prompts import render


def build_claim_chart(
    target_claims: list[Claim],
    prior_arts: list[PriorArtDoc],
    examiner_chart: ExaminerChart | None,
    llm: LLMClient,
) -> ClaimChartResult:
    all_charts = []
    for prior_art in prior_arts:
        for claim in target_claims:
            prompt = render(
                "tool4.j2",
                target_claim_number=claim.claim_number,
                elements=claim.elements,
                prior_art=prior_art,
                examiner_chart=examiner_chart,
            )
            partial: ClaimChartResult = llm.generate(
                prompt, schema=ClaimChartResult, temperature=0.0
            )
            all_charts.extend(partial.charts)
    return ClaimChartResult(charts=all_charts)
