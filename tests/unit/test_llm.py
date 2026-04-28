import pytest
from patent_agent.llm import get_llm


def test_get_llm_returns_claude(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    llm = get_llm()
    assert llm is not None


def test_get_llm_returns_openai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    llm = get_llm()
    assert llm is not None


def test_get_llm_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        get_llm()
