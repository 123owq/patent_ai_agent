import pytest
from fastapi import HTTPException

from patent_agent.api.routers.edits import (
    ApplyEditRequest,
    PreviewEditRequest,
    apply_edit,
    list_edit_candidates,
    preview_edit,
)
from patent_agent.core.storage import load_analysis, save_analysis
from tests.unit.factories import make_analysis_result


def test_apply_edit_returns_400_for_invalid_target_path_without_saving(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    result = make_analysis_result(application_number="10-test")
    save_analysis(result)

    with pytest.raises(HTTPException) as exc:
        apply_edit(
            "10-test",
            ApplyEditRequest(
                target_path="claim_parse.claims[999].text",
                new_value="bad value",
            ),
            model_id=None,
        )

    assert exc.value.status_code == 400
    assert "Invalid target_path" in str(exc.value.detail)
    assert load_analysis("10-test").version == 1
    assert not (tmp_path / "analysis" / "10-test" / "edits.log").exists()


def test_apply_edit_returns_400_for_invalid_value_without_saving(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    result = make_analysis_result(application_number="10-test")
    save_analysis(result)

    with pytest.raises(HTTPException) as exc:
        apply_edit(
            "10-test",
            ApplyEditRequest(
                target_path="strategy",
                new_value="not a strategy object",
            ),
            model_id=None,
        )

    assert exc.value.status_code == 400
    assert "Invalid value" in str(exc.value.detail)
    assert load_analysis("10-test").version == 1
    assert not (tmp_path / "analysis" / "10-test" / "edits.log").exists()


def test_list_edit_candidates_returns_matching_scalar_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    result = make_analysis_result(application_number="10-test")
    result.claim_parse.total_claims = 3
    save_analysis(result)

    response = list_edit_candidates("10-test", query="total", limit=5, model_id=None)

    assert response.candidates[0].target_path == "claim_parse.total_claims"
    assert response.candidates[0].current_value == 3
    assert response.candidates[0].value_type == "int"


def test_preview_edit_validates_and_normalizes_without_saving(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    result = make_analysis_result(application_number="10-test")
    result.claim_parse.total_claims = 3
    save_analysis(result)

    response = preview_edit(
        "10-test",
        PreviewEditRequest(target_path="claim_parse.total_claims", new_value="7"),
        model_id=None,
    )

    assert response.target_path == "claim_parse.total_claims"
    assert response.current_value == 3
    assert response.proposed_value == "7"
    assert response.normalized_value == 7
    assert response.value_type == "int"
    assert response.next_version == 2
    assert load_analysis("10-test").version == 1
    assert not (tmp_path / "analysis" / "10-test" / "result.v2.json").exists()
