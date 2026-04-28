"""파이프라인 통합 테스트 (mock LLM 사용)"""
from unittest.mock import patch
import pytest
from patent_agent.core.pipeline import run_analysis
from patent_agent.models.input import PatentDoc, OfficeActionRaw
from tests.unit.factories import make_analysis_result


@pytest.fixture
def patent_doc():
    return PatentDoc(
        application_number="10-test",
        title="테스트 발명",
        abstract="요약",
        claims={1: "청구항 1 텍스트"},
        spec_paragraphs={"0001": "단락 내용"},
    )


@pytest.fixture
def office_action_raw():
    return OfficeActionRaw(
        application_number="10-test",
        raw_dict={"구체적인거절이유": {}},
    )


def test_pipeline_runs_all_tools(patent_doc, office_action_raw, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    expected = make_analysis_result("10-test")

    steps_recorded = []
    def progress_cb(step, ratio):
        steps_recorded.append((step, ratio))

    with patch("patent_agent.core.pipeline.parse_office_action",
               return_value=expected.office_action), \
         patch("patent_agent.core.pipeline.parse_claims",
               return_value=expected.claim_parse), \
         patch("patent_agent.core.pipeline.map_spec_to_elements",
               return_value=expected.spec_mapping), \
         patch("patent_agent.core.pipeline.build_claim_chart",
               return_value=expected.claim_chart), \
         patch("patent_agent.core.pipeline.analyze_diff_and_strategy",
               return_value=expected.strategy), \
         patch("patent_agent.core.pipeline.generate_amendments",
               return_value=expected.amendment):
        result = run_analysis(patent_doc, office_action_raw, [], None, progress_cb)

    assert result.application_number == "10-test"
    assert result.version == 1
    assert len(steps_recorded) >= 6
    assert steps_recorded[-1][0] == "완료"
    assert steps_recorded[-1][1] == 1.0

    saved = tmp_path / "analysis" / "10-test" / "result.json"
    assert saved.exists()


def test_pipeline_degrades_on_tool3_failure(patent_doc, office_action_raw,
                                             tmp_path, monkeypatch):
    """Tool 3 실패 시 degrade & continue (is_fatal=False)"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    expected = make_analysis_result("10-test")

    with patch("patent_agent.core.pipeline.parse_office_action",
               return_value=expected.office_action), \
         patch("patent_agent.core.pipeline.parse_claims",
               return_value=expected.claim_parse), \
         patch("patent_agent.core.pipeline.map_spec_to_elements",
               side_effect=RuntimeError("LLM 오류")), \
         patch("patent_agent.core.pipeline.build_claim_chart",
               return_value=expected.claim_chart), \
         patch("patent_agent.core.pipeline.analyze_diff_and_strategy",
               return_value=expected.strategy), \
         patch("patent_agent.core.pipeline.generate_amendments",
               return_value=expected.amendment):
        result = run_analysis(patent_doc, office_action_raw, [], None)

    assert result is not None
    tool3_errors = [e for e in result.errors if e.tool_name == "tool3_map_spec"]
    assert len(tool3_errors) == 1
    assert not tool3_errors[0].is_fatal
