import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from patent_agent.tools.tool1_parse_office_action import (
    parse_office_action,
    extract_claim_numbers,
    extract_examiner_chart,
)
from patent_agent.models.input import OfficeActionRaw
from patent_agent.models.output import CitedArtRef, OfficeActionResult, RejectionReason

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "10-2014-0036561"


@pytest.fixture
def office_action_raw():
    raw = json.loads((FIXTURE_DIR / "office_action.json").read_text(encoding="utf-8"))
    return OfficeActionRaw(application_number="10-2014-0036561", raw_dict=raw)


def test_extract_claim_numbers_single():
    assert extract_claim_numbers("제1항") == [1]


def test_extract_claim_numbers_range():
    assert extract_claim_numbers("제4항 내지 제7항") == [4, 5, 6, 7]


def test_extract_claim_numbers_mixed():
    result = extract_claim_numbers("제1항, 제4항 내지 제7항")
    assert sorted(result) == [1, 4, 5, 6, 7]


def test_extract_examiner_chart_has_rows(office_action_raw):
    chart = extract_examiner_chart(office_action_raw)
    assert chart is not None
    assert len(chart.rows) > 0


def test_extract_examiner_chart_match_values(office_action_raw):
    chart = extract_examiner_chart(office_action_raw)
    for row in chart.rows:
        assert row.examiner_match in ("동일", "유사", "차이")


def test_parse_office_action_calls_llm(office_action_raw):
    mock_llm = MagicMock()
    mock_llm.generate.return_value = OfficeActionResult(
        application_number="10-2014-0036561",
        rejection_reasons=[
            RejectionReason(
                article="특허법 제29조제2항",
                rejection_type="진보성",
                target_claim_numbers=[1, 4, 5, 6, 7],
                cited_art_ids=["인용발명1"],
                examiner_reasoning="test",
            )
        ],
        rejected_claim_numbers=[1, 4, 5, 6, 7],
        cited_arts=[CitedArtRef(cited_art_id="인용발명1", document_number="10-2000-0018563")],
    )
    result = parse_office_action(office_action_raw, mock_llm)
    mock_llm.generate.assert_called_once()
    assert sorted(result.rejected_claim_numbers) == [1, 4, 5, 6, 7]
