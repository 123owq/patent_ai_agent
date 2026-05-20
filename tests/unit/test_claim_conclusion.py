import pytest
from pydantic import ValidationError
from patent_agent.models.output import ClaimConclusionItem, ClaimConclusionResult


def test_claim_conclusion_item_valid():
    item = ClaimConclusionItem(
        claim_number=1,
        rejection_type="신규성",
        merged_from=["신규성", "진보성"],
        our_verdict="동의",
        our_reasoning="인용발명1이 본원 구성을 실질적으로 개시함",
    )
    assert item.claim_number == 1
    assert item.our_verdict == "동의"
    assert item.merged_from == ["신규성", "진보성"]


def test_claim_conclusion_item_default_merged_from():
    item = ClaimConclusionItem(
        claim_number=2,
        rejection_type="진보성",
        our_verdict="반대",
        our_reasoning="구성 차이가 있음",
    )
    assert item.merged_from == []


def test_claim_conclusion_item_rejects_invalid_verdict():
    with pytest.raises(ValidationError):
        ClaimConclusionItem(
            claim_number=1,
            rejection_type="신규성",
            our_verdict="모름",
            our_reasoning="",
        )


def test_claim_conclusion_result_serializes():
    result = ClaimConclusionResult(items=[
        ClaimConclusionItem(
            claim_number=1, rejection_type="진보성",
            our_verdict="부분동의", our_reasoning="일부 구성만 개시됨",
        )
    ])
    d = result.model_dump()
    assert d["items"][0]["our_verdict"] == "부분동의"


from enrich_claim_conclusion import build_conclusion_items


def _reason(rtype: str, claims: list[int], reasoning: str = "심사관 이유") -> dict:
    return {
        "rejection_type": rtype,
        "target_claim_numbers": claims,
        "examiner_reasoning": reasoning,
        "cited_art_ids": ["인용발명1"],
    }


def test_build_items_basic():
    items = build_conclusion_items([_reason("진보성", [1, 2])])
    assert len(items) == 2
    assert items[0]["claim_number"] == 1
    assert items[0]["rejection_type"] == "진보성"
    assert items[0]["merged_from"] == []


def test_build_items_merges_novelty_and_inventive():
    items = build_conclusion_items([
        _reason("신규성", [1]),
        _reason("진보성", [1, 2]),
    ])
    claim1 = [i for i in items if i["claim_number"] == 1]
    claim2 = [i for i in items if i["claim_number"] == 2]
    assert len(claim1) == 1
    assert claim1[0]["rejection_type"] == "신규성"
    assert "진보성" in claim1[0]["merged_from"]
    assert len(claim2) == 1
    assert claim2[0]["rejection_type"] == "진보성"
    assert claim2[0]["merged_from"] == []


def test_build_items_keeps_gijae_separate():
    items = build_conclusion_items([
        _reason("진보성", [4]),
        _reason("기재불비", [4]),
    ])
    assert len(items) == 2
    types = {i["rejection_type"] for i in items}
    assert types == {"진보성", "기재불비"}


def test_build_items_sorted_by_claim_number():
    items = build_conclusion_items([_reason("진보성", [3, 1, 2])])
    assert [i["claim_number"] for i in items] == [1, 2, 3]


def test_build_items_uses_novelty_reasoning_when_merged():
    items = build_conclusion_items([
        _reason("신규성", [1], reasoning="신규성 이유 원문"),
        _reason("진보성", [1], reasoning="진보성 이유 원문"),
    ])
    assert items[0]["examiner_reasoning"] == "신규성 이유 원문"


import json
from pathlib import Path
from unittest.mock import MagicMock
from patent_agent.models.output import ClaimConclusionItem, ClaimConclusionResult
from enrich_claim_conclusion import enrich_one


def _write_result(path: Path, has_conclusion: bool = False) -> None:
    data = {
        "application_number": "10-test",
        "llm_model": "anthropic/claude-sonnet-4.6",
        "office_action": {
            "rejection_reasons": [{
                "rejection_type": "진보성",
                "target_claim_numbers": [1],
                "examiner_reasoning": "인용발명 1로부터 쉽게 발명 가능",
                "cited_art_ids": ["인용발명1"],
            }]
        },
        "claim_parse": {
            "claims": [{"claim_number": 1, "original_text": "청구항 1 원문"}]
        },
    }
    if has_conclusion:
        data["claim_conclusion"] = {"items": []}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _mock_llm(verdict: str = "동의") -> MagicMock:
    llm = MagicMock()
    llm.generate.return_value = ClaimConclusionResult(items=[
        ClaimConclusionItem(
            claim_number=1, rejection_type="진보성",
            our_verdict=verdict, our_reasoning="판단 근거",
        )
    ])
    return llm


def test_enrich_one_writes_conclusion(tmp_path):
    result_path = tmp_path / "result.json"
    _write_result(result_path)

    changed = enrich_one(result_path, _mock_llm(), force=False)

    assert changed is True
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert "claim_conclusion" in saved
    assert saved["claim_conclusion"]["items"][0]["our_verdict"] == "동의"


def test_enrich_one_skips_existing(tmp_path):
    result_path = tmp_path / "result.json"
    _write_result(result_path, has_conclusion=True)
    llm = _mock_llm()

    changed = enrich_one(result_path, llm, force=False)

    assert changed is False
    llm.generate.assert_not_called()


def test_enrich_one_force_overwrites(tmp_path):
    result_path = tmp_path / "result.json"
    _write_result(result_path, has_conclusion=True)

    changed = enrich_one(result_path, _mock_llm(), force=True)

    assert changed is True


def test_enrich_one_returns_false_when_no_items(tmp_path):
    result_path = tmp_path / "result.json"
    data = {
        "application_number": "10-test",
        "llm_model": "anthropic/claude-sonnet-4.6",
        "office_action": {"rejection_reasons": []},
        "claim_parse": {"claims": []},
    }
    result_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    llm = _mock_llm()

    changed = enrich_one(result_path, llm, force=False)

    assert changed is False
    llm.generate.assert_not_called()
