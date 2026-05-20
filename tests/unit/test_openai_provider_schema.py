from patent_agent.llm.openai_provider import _to_openai_strict_json_schema
from patent_agent.models.output import OfficeActionResult


def test_openai_strict_schema_disallows_extra_properties_recursively():
    schema = _to_openai_strict_json_schema(OfficeActionResult.model_json_schema())

    assert schema["additionalProperties"] is False
    assert schema["$defs"]["RejectionReason"]["additionalProperties"] is False
    assert schema["$defs"]["CitedArtRef"]["additionalProperties"] is False
    assert schema["$defs"]["ExaminerChartRow"]["additionalProperties"] is False


def test_openai_strict_schema_requires_optional_object_fields_and_removes_defaults():
    schema = _to_openai_strict_json_schema(OfficeActionResult.model_json_schema())
    examiner_chart_row = schema["$defs"]["ExaminerChartRow"]

    assert "examiner_chart" in schema["required"]
    assert "comparison_id" in examiner_chart_row["required"]
    assert "claim_number" in examiner_chart_row["required"]
    assert "prior_art_location" in examiner_chart_row["required"]
    assert "note" in examiner_chart_row["required"]
    assert "default" not in examiner_chart_row["properties"]["comparison_id"]

