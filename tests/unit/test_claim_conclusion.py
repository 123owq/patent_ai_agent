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
