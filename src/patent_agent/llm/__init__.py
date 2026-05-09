import os
from patent_agent.llm.base import LLMClient
from patent_agent.llm.claude import ClaudeProvider
from patent_agent.llm.openai_provider import OpenAIProvider


def _make_real_llm(provider: str) -> LLMClient:
    if provider == "claude":
        return ClaudeProvider(
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
        )
    if provider == "openai":
        return OpenAIProvider(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
        )
    raise ValueError(f"Unknown provider: {provider!r}")


def get_llm() -> LLMClient:
    provider = os.getenv("LLM_PROVIDER", "claude").lower()

    if provider == "recording":
        from patent_agent.llm.recording import RecordingLLMClient
        real_provider = os.getenv("RECORDING_REAL_PROVIDER", "claude")
        cassette_dir = os.getenv("CASSETTE_DIR", "tests/cassettes")
        return RecordingLLMClient(
            real_llm=_make_real_llm(real_provider),
            cassette_dir=cassette_dir,
        )

    try:
        return _make_real_llm(provider)
    except ValueError:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'claude', 'openai', or 'recording'.")
