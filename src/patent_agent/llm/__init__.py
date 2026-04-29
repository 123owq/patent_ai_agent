import os
from patent_agent.llm.base import LLMClient
from patent_agent.llm.claude import ClaudeProvider
from patent_agent.llm.openai_provider import OpenAIProvider


def get_llm() -> LLMClient:
    provider = os.getenv("LLM_PROVIDER", "claude").lower()

    if provider == "claude":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
        return ClaudeProvider(api_key=api_key, base_url=base_url, model=model)

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("OPENAI_MODEL", "gpt-4.1")
        return OpenAIProvider(api_key=api_key, base_url=base_url, model=model)

    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'claude' or 'openai'.")
