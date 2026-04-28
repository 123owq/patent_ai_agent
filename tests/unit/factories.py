from datetime import datetime
from patent_agent.models.analysis import AnalysisResult
from patent_agent.models.output import (
    OfficeActionResult,
    ClaimParseResult,
    SpecMappingResult,
    ClaimChartResult,
    StrategyResult,
    AmendmentResult,
    AmendmentDraft,
    Strategy,
)


def make_analysis_result(application_number: str = "10-test") -> AnalysisResult:
    return AnalysisResult(
        analysis_id=f"test-{application_number}",
        application_number=application_number,
        created_at=datetime.now(),
        office_action=OfficeActionResult(
            application_number=application_number,
            rejection_reasons=[],
            rejected_claim_numbers=[],
            cited_arts=[],
        ),
        claim_parse=ClaimParseResult(
            application_number=application_number,
            total_claims=0,
            independent_claims=[],
            dependent_claims=[],
            claims=[],
        ),
        spec_mapping=SpecMappingResult(mappings=[]),
        claim_chart=ClaimChartResult(charts=[]),
        strategy=StrategyResult(
            offensive=Strategy(
                strategy_type="공격",
                rationale="test",
                leveraged_differences=[],
                proposed_action="test",
            ),
            defensive=Strategy(
                strategy_type="방어",
                rationale="test",
                leveraged_differences=[],
                proposed_action="test",
            ),
        ),
        amendment=AmendmentResult(
            offensive_draft=AmendmentDraft(
                strategy_type="공격",
                amended_claims=[],
                overall_explanation="test",
            ),
            defensive_draft=AmendmentDraft(
                strategy_type="방어",
                amended_claims=[],
                overall_explanation="test",
            ),
        ),
    )
