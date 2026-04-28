import os
from patent_agent.llm.base import LLMClient
from patent_agent.llm.claude import ClaudeProvider
from patent_agent.llm.openai_provider import OpenAIProvider


def get_llm() -> LLMClient:
    provider = os.getenv("LLM_PROVIDER", "claude").lower()
    if provider == "claude":
        model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
        return ClaudeProvider(model=model)
    if provider == "openai":
        model = os.getenv("OPENAI_MODEL", "gpt-4.1")
        return OpenAIProvider(model=model)
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'claude' or 'openai'.")
