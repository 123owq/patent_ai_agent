from patent_agent.llm.base import LLMClient
from patent_agent.models.output import ClaimParseResult, SpecMappingResult
from patent_agent.core.prompts import render


def map_spec_to_elements(
    claims: ClaimParseResult,
    spec_paragraphs: dict[str, str],
    llm: LLMClient,
) -> SpecMappingResult:
    all_elements = [e for c in claims.claims for e in c.elements]
    prompt = render("tool3.j2", elements=all_elements, spec_paragraphs=spec_paragraphs)
    return llm.generate(prompt, schema=SpecMappingResult, temperature=0.0)
