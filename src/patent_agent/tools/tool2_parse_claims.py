from patent_agent.llm.base import LLMClient
from patent_agent.models.output import ClaimParseResult
from patent_agent.core.prompts import render


def parse_claims(
    application_number: str,
    claims: dict[int, str],
    llm: LLMClient,
) -> ClaimParseResult:
    prompt = render("tool2.j2", application_number=application_number, claims=claims)
    return llm.generate(prompt, schema=ClaimParseResult, temperature=0.0)
