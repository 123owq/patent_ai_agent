from patent_agent.llm.base import LLMClient
from patent_agent.models.output import (
    AmendedClaim,
    AmendmentDraft,
    AmendmentResult,
    ClaimParseResult,
    SpecMappingResult,
    Strategy,
    StrategyResult,
)
from patent_agent.core.prompts import render


def generate_amendments(
    strategy: StrategyResult,
    claims: ClaimParseResult,
    spec_mapping: SpecMappingResult,
    llm: LLMClient,
    spec_paragraphs: dict[str, str] | None = None,
    user_instruction: str | None = None,
) -> AmendmentResult:
    all_spec_paragraphs: dict[str, str] = spec_paragraphs or {}
    rejected_claims = claims.claims  # 파이프라인에서 거절 청구항만 넘김

    # 공격 보정안
    prompt_offensive = render(
        "tool6_offensive.j2",
        strategy=strategy.offensive,
        rejected_claims=rejected_claims,
        user_instruction=user_instruction,
    )
    offensive_result: AmendmentResult = llm.generate(
        prompt_offensive, schema=AmendmentResult, temperature=0.0
    )

    # 방어 보정안 — 명세서 뒷받침 단락 포함
    relevant_mappings = spec_mapping.mappings
    defensive_spec = {
        para_id: all_spec_paragraphs[para_id]
        for m in relevant_mappings
        for para_id in m.paragraph_ids
        if para_id in all_spec_paragraphs
    }
    prompt_defensive = render(
        "tool6_defensive.j2",
        strategy=strategy.defensive,
        rejected_claims=rejected_claims,
        relevant_mappings=relevant_mappings,
        spec_paragraphs=defensive_spec,
        user_instruction=user_instruction,
    )
    defensive_result: AmendmentResult = llm.generate(
        prompt_defensive, schema=AmendmentResult, temperature=0.0
    )

    return AmendmentResult(
        offensive_draft=offensive_result.offensive_draft,
        defensive_draft=defensive_result.defensive_draft,
    )


def validate_spec_basis(
    amended_claims: list[AmendedClaim],
    spec_paragraphs: dict[str, str],
) -> list[str]:
    """spec_basis 단락 ID가 실제 명세서에 존재하는지 검증. 에러 메시지 목록 반환."""
    errors: list[str] = []
    for ac in amended_claims:
        for para_id in ac.spec_basis:
            if para_id not in spec_paragraphs:
                errors.append(
                    f"청구항 {ac.claim_number}: spec_basis '{para_id}'가 명세서에 없음"
                )
    return errors
