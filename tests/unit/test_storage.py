import pytest
from patent_agent.core.storage import save_analysis, load_analysis, list_versions
from tests.unit.factories import make_analysis_result


def test_save_creates_versioned_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    result = make_analysis_result(application_number="10-2014-0036561")
    save_analysis(result)
    v1 = tmp_path / "analysis" / "10-2014-0036561" / "result.v1.json"
    latest = tmp_path / "analysis" / "10-2014-0036561" / "result.json"
    assert v1.exists()
    assert latest.exists()


def test_load_returns_latest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    result = make_analysis_result(application_number="10-2014-0036561")
    save_analysis(result)
    loaded = load_analysis("10-2014-0036561")
    assert loaded.application_number == "10-2014-0036561"
    assert loaded.version == 1


def test_save_increments_version(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    r1 = make_analysis_result(application_number="10-0000-0000001")
    save_analysis(r1)
    r2 = make_analysis_result(application_number="10-0000-0000001")
    r2.version = 2
    save_analysis(r2)
    versions = list_versions("10-0000-0000001")
    assert versions == [1, 2]


def test_load_raises_when_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    with pytest.raises(FileNotFoundError):
        load_analysis("10-nonexistent")


def test_save_and_load_use_explicit_model_id(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    result = make_analysis_result(application_number="10-2014-0036561")

    save_analysis(result, model_id="openai__gpt-5.4")

    latest = tmp_path / "analysis" / "10-2014-0036561" / "openai__gpt-5.4" / "result.json"
    assert latest.exists()

    loaded = load_analysis("10-2014-0036561", model_id="openai__gpt-5.4")
    assert loaded.application_number == "10-2014-0036561"


def test_model_id_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    result = make_analysis_result(application_number="10-2014-0036561")

    with pytest.raises(ValueError):
        save_analysis(result, model_id="../outside")
