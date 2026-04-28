from patent_agent.llm import get_llm
from patent_agent.llm.base import LLMClient


def get_llm_dep() -> LLMClient:
    return get_llm()
