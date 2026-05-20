# Claim Conclusion Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 result.json에 `claim_conclusion` 필드를 post-processing 스크립트로 추가해 "거절된 청구항별 LLM 동의/부분동의/반대 판단"을 저장하고, 보고서에 해당 통계 섹션을 추가한다.

**Architecture:** 파이프라인(`pipeline.py`)은 건드리지 않는다. 별도 스크립트 `scripts/enrich_claim_conclusion.py`가 기존 result.json을 읽어 (청구항 × 거절유형) 쌍을 도출하고(신규성+진보성 동시 거절은 신규성 1건으로 합산), 문서 단위로 LLM 1회 호출해 판단을 받아 result.json에 `claim_conclusion`을 추가한다. `report_agreement.py`에 새 섹션을 추가해 strict/loose agreement 통계를 출력한다.

**Tech Stack:** Python 3.12, Pydantic v2, Jinja2, pytest + MagicMock, 기존 `LLMClient.generate()` + `core.prompts.render()` 패턴

---

## 배경 지식 (구현 전 필독)

- **LLM 호출 패턴:** `llm.generate(prompt_str, schema=PydanticModel, temperature=0.0)` → PydanticModel 인스턴스 반환. 프롬프트는 `from patent_agent.core.prompts import render; render("template.j2", **kwargs)`로 렌더링.
- **result.json 위치:** `data/analysis/{출원번호}/{모델명}/result.json`. 모델명은 `/` → `__` 치환 (예: `anthropic/claude-sonnet-4.6` → `anthropic__claude-sonnet-4.6`).
- **LLM 클라이언트 생성:** `anthropic/*` → `ClaudeProvider`, `openai/*` → `OpenAIProvider`, `google/*`, `deepseek/*` → `OpenAIProvider` (OpenAI-compatible endpoint).
- **신규성+진보성 병합:** 같은 청구항에 신규성·진보성이 동시에 있으면 신규성 1건으로 합친다. 기재불비는 별도 유지.
- **분모:** 10개 문서 전체에서 병합 후 약 65개 (청구항 × 거절유형) 쌍.
- **프롬프트 thin reasoning 문제:** 종속항 거절이유는 "통상의 기술자가 쉽게 발명할 수 있습니다" 수준 한 줄. 프롬프트에서 "근거가 불충분하면 '부분동의'를 기본값으로" 지침을 명시해야 한다.

---

## File Map

| 파일 | 변경 |
|---|---|
| `src/patent_agent/models/output.py` | `ClaimConclusionItem`, `ClaimConclusionResult` 클래스 추가 |
| `src/patent_agent/models/analysis.py` | `AnalysisResult.claim_conclusion` 필드 추가 (Optional) |
| `src/patent_agent/prompts/claim_conclusion.j2` | 신규 — LLM 판단 요청 프롬프트 |
| `scripts/enrich_claim_conclusion.py` | 신규 — post-processing 실행 스크립트 |
| `scripts/report_agreement.py` | 청구항 결론 통계 섹션 추가 |
| `tests/conftest.py` | scripts/ 임포트용 sys.path 추가 |
| `tests/unit/test_claim_conclusion.py` | 신규 — 머지 로직·리포트 빌더 단위 테스트 |

---

## Task 1: Pydantic 모델 추가

**Files:**
- Modify: `src/patent_agent/models/output.py`
- Modify: `src/patent_agent/models/analysis.py`
- Create: `tests/unit/test_claim_conclusion.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/unit/test_claim_conclusion.py
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
```

- [ ] **Step 2: 테스트 실패 확인**

```
uv run pytest tests/unit/test_claim_conclusion.py -v
```
Expected: `ImportError: cannot import name 'ClaimConclusionItem'`

- [ ] **Step 3: output.py 하단 `ToolError` 클래스 아래에 추가**

`src/patent_agent/models/output.py` 파일 맨 끝에 추가:

```python
# ── Claim Conclusion (post-processing) ───────────────────────────────
class ClaimConclusionItem(BaseModel):
    claim_number: int
    rejection_type: Literal["신규성", "진보성", "기재불비", "기타"]
    merged_from: list[str] = []
    our_verdict: Literal["동의", "부분동의", "반대"]
    our_reasoning: str


class ClaimConclusionResult(BaseModel):
    items: list[ClaimConclusionItem]
```

- [ ] **Step 4: analysis.py 수정**

`src/patent_agent/models/analysis.py` 전체를 다음으로 교체:

```python
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
from patent_agent.models.output import (
    OfficeActionResult,
    ClaimParseResult,
    SpecMappingResult,
    ClaimChartResult,
    StrategyResult,
    AmendmentResult,
    ToolError,
    ClaimConclusionResult,
)


class AnalysisResult(BaseModel):
    analysis_id: str
    application_number: str
    llm_model: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    version: int = 1
    source_files: dict[str, str] = {}
    errors: list[ToolError] = []
    office_action: OfficeActionResult
    claim_parse: ClaimParseResult
    spec_mapping: SpecMappingResult
    claim_chart: ClaimChartResult
    strategy: StrategyResult
    amendment: AmendmentResult
    claim_conclusion: ClaimConclusionResult | None = None


class EditLogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    target_path: str
    before: str
    after: str
    source: Literal["user-direct", "llm-proposed-user-applied", "regenerate"]
    user_instruction: str | None = None
```

- [ ] **Step 5: 테스트 통과 확인**

```
uv run pytest tests/unit/test_claim_conclusion.py -v
```
Expected: 4 PASSED

- [ ] **Step 6: 기존 테스트 회귀 없음 확인**

```
uv run pytest tests/unit/ -v
```
Expected: 전부 PASSED

- [ ] **Step 7: 커밋**

```bash
git add src/patent_agent/models/output.py src/patent_agent/models/analysis.py tests/unit/test_claim_conclusion.py
git commit -m "feat: add ClaimConclusionItem/Result models and optional field on AnalysisResult"
```

---

## Task 2: 머지 로직 (순수 함수)

**Files:**
- Create: `scripts/enrich_claim_conclusion.py` (이 태스크에서 머지 함수만, 나머지는 Task 4에서)
- Modify: `tests/conftest.py`
- Modify: `tests/unit/test_claim_conclusion.py`

- [ ] **Step 1: conftest.py에 scripts 임포트 경로 추가**

`tests/conftest.py`를 다음으로 교체:

```python
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
# scripts/ 디렉터리를 임포트 가능하게 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
```

- [ ] **Step 2: 실패하는 테스트 추가**

`tests/unit/test_claim_conclusion.py`에 추가:

```python
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
```

- [ ] **Step 3: 테스트 실패 확인**

```
uv run pytest tests/unit/test_claim_conclusion.py::test_build_items_basic -v
```
Expected: `ModuleNotFoundError: No module named 'enrich_claim_conclusion'`

- [ ] **Step 4: scripts/enrich_claim_conclusion.py — 머지 함수만 작성**

```python
# scripts/enrich_claim_conclusion.py
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from patent_agent.core.prompts import render
from patent_agent.llm.base import LLMClient
from patent_agent.models.output import ClaimConclusionResult


def build_conclusion_items(rejection_reasons: list[dict]) -> list[dict]:
    """
    office_action["rejection_reasons"] 에서 (청구항 × 거절유형) 쌍 목록 생성.
    같은 청구항에 신규성·진보성이 동시에 존재하면 신규성 1건으로 합산.
    기재불비는 별도 유지. 결과는 claim_number 오름차순 정렬.
    """
    by_claim: dict[int, dict[str, dict]] = defaultdict(dict)

    for reason in rejection_reasons:
        rtype = reason["rejection_type"]
        for cn in reason["target_claim_numbers"]:
            by_claim[cn][rtype] = reason

    items: list[dict] = []
    for cn in sorted(by_claim.keys()):
        types = by_claim[cn]

        if "신규성" in types and "진보성" in types:
            r = types["신규성"]
            items.append({
                "claim_number": cn,
                "rejection_type": "신규성",
                "merged_from": ["신규성", "진보성"],
                "examiner_reasoning": r["examiner_reasoning"],
                "cited_art_ids": r["cited_art_ids"],
            })
            for rtype in sorted(t for t in types if t not in ("신규성", "진보성")):
                r2 = types[rtype]
                items.append({
                    "claim_number": cn,
                    "rejection_type": rtype,
                    "merged_from": [],
                    "examiner_reasoning": r2["examiner_reasoning"],
                    "cited_art_ids": r2["cited_art_ids"],
                })
        else:
            for rtype in sorted(types.keys()):
                r = types[rtype]
                items.append({
                    "claim_number": cn,
                    "rejection_type": rtype,
                    "merged_from": [],
                    "examiner_reasoning": r["examiner_reasoning"],
                    "cited_art_ids": r["cited_art_ids"],
                })

    return items
```

- [ ] **Step 5: 테스트 통과 확인**

```
uv run pytest tests/unit/test_claim_conclusion.py -v
```
Expected: 전부 PASSED (Task 1 + Task 2 테스트 포함)

- [ ] **Step 6: 커밋**

```bash
git add scripts/enrich_claim_conclusion.py tests/conftest.py tests/unit/test_claim_conclusion.py
git commit -m "feat: add build_conclusion_items merge logic with tests"
```

---

## Task 3: 프롬프트 템플릿

**Files:**
- Create: `src/patent_agent/prompts/claim_conclusion.j2`

- [ ] **Step 1: 템플릿 작성**

```jinja2
당신은 대한민국 특허 거절이유를 검토하는 전문가입니다.
아래는 출원번호 {{ application_number }} 에 대한 심사관의 거절 결론 목록입니다.
각 항목에 대해 심사관의 거절 결론이 타당한지 판단하십시오.

## 판단 라벨

[동의]
심사관의 거절 근거가 타당하고, 인용발명이 해당 청구항의 신규성 또는 진보성을 실질적으로 부정한다고 판단되는 경우.

[부분동의]
거절 방향성은 인정하나, 심사관의 근거나 인용발명 조합에 이견이 있거나, 청구항의 일부 구성은 극복 가능성이 있는 경우.
심사관 이유가 "통상의 기술자가 쉽게 발명할 수 있습니다"처럼 구체적 근거 없이 결론만 서술된 경우에도 부분동의를 기본값으로 사용하십시오.

[반대]
심사관의 거절 결론이 부당하다고 판단되는 경우. 인용발명이 해당 청구항의 신규성 또는 진보성을 부정하기에 충분하지 않습니다.

## 판단 항목
{% for item in items %}
---
### 항목 {{ loop.index }}: 청구항 {{ item.claim_number }} — {{ item.rejection_type }}
{% if item.merged_from %}
(이 항목은 {{ item.merged_from | join(' + ') }} 거절이 동시 적용된 청구항입니다. 신규성 기준으로 판단하십시오.)
{% endif %}
청구항 원문:
{{ item.claim_text }}

심사관 거절 이유:
{{ item.examiner_reasoning }}

인용발명: {{ item.cited_art_ids | join(', ') }}
{% endfor %}

---
## 출력 지시
- 위 항목 순서대로 정확히 {{ items | length }}개의 판단을 반환하십시오.
- claim_number와 rejection_type은 입력값 그대로 유지하십시오.
- our_reasoning에는 판단 근거를 간결하게 서술하십시오 (2~4문장).
- 심사관 이유가 구체적 근거 없이 결론만 서술된 경우 our_verdict는 "부분동의"로 하십시오.
```

- [ ] **Step 2: 템플릿 렌더링 오류 없는지 확인**

```python
# Python REPL 또는 임시 스크립트에서 실행
import sys; sys.path.insert(0, "src")
from patent_agent.core.prompts import render
prompt = render(
    "claim_conclusion.j2",
    application_number="10-2019-0156160",
    items=[{
        "claim_number": 1,
        "rejection_type": "신규성",
        "merged_from": ["신규성", "진보성"],
        "claim_text": "청구항 1 원문...",
        "examiner_reasoning": "인용발명1과 동일합니다.",
        "cited_art_ids": ["인용발명1"],
    }],
)
assert "부분동의를 기본값" in prompt
print("OK:", prompt[:100])
```

- [ ] **Step 3: 커밋**

```bash
git add src/patent_agent/prompts/claim_conclusion.j2
git commit -m "feat: add claim_conclusion.j2 prompt template"
```

---

## Task 4: Enrichment 스크립트 완성

**Files:**
- Modify: `scripts/enrich_claim_conclusion.py`
- Modify: `tests/unit/test_claim_conclusion.py`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/unit/test_claim_conclusion.py`에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

```
uv run pytest tests/unit/test_claim_conclusion.py::test_enrich_one_writes_conclusion -v
```
Expected: `ImportError: cannot import name 'enrich_one'`

- [ ] **Step 3: 스크립트에 나머지 함수 추가**

`scripts/enrich_claim_conclusion.py`에서 `build_conclusion_items` 함수 아래에 추가:

```python
APPLICATION_NUMBERS = [
    "10-2014-0036561",
    "10-2019-0156160",
    "10-2020-0019150",
    "10-2022-0039209",
    "10-2020-0001439",
    "10-2018-0029369",
    "10-2012-0085288",
    "10-2020-0051159",
    "10-2011-0114638",
    "10-2024-0003359",
]

MODELS = [
    "google/gemini-3.1-pro-preview",
    "openai/gpt-5.4",
    "anthropic/claude-sonnet-4.6",
]


def _make_llm(llm_model: str) -> LLMClient:
    """result.json의 llm_model 값으로 LLM 클라이언트 생성."""
    from patent_agent.llm.claude import ClaudeProvider
    from patent_agent.llm.openai_provider import OpenAIProvider

    prefix, model_name = llm_model.split("/", 1)

    if prefix == "anthropic":
        return ClaudeProvider(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            model=model_name,
        )
    if prefix == "openai":
        return OpenAIProvider(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=model_name,
        )
    if prefix == "google":
        return OpenAIProvider(
            api_key=os.environ["GOOGLE_API_KEY"],
            base_url=os.getenv(
                "GOOGLE_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            model=model_name,
        )
    if prefix == "deepseek":
        return OpenAIProvider(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            model=model_name,
        )
    raise ValueError(f"Unknown model prefix: {prefix!r} (model={llm_model!r})")


def enrich_one(result_path: Path, llm: LLMClient, force: bool) -> bool:
    """
    result.json에 claim_conclusion 필드를 추가한다.
    이미 존재하고 force=False 이면 skip → False 반환.
    변경이 발생하면 True 반환.
    """
    result = json.loads(result_path.read_text(encoding="utf-8"))

    if result.get("claim_conclusion") and not force:
        return False

    rejection_reasons = result.get("office_action", {}).get("rejection_reasons", [])
    claims_by_number = {
        c["claim_number"]: c
        for c in result.get("claim_parse", {}).get("claims", [])
    }

    items = build_conclusion_items(rejection_reasons)
    if not items:
        return False

    items_with_text = [
        {
            **item,
            "claim_text": claims_by_number.get(item["claim_number"], {}).get(
                "original_text", "(청구항 원문 없음)"
            ),
        }
        for item in items
    ]

    prompt = render(
        "claim_conclusion.j2",
        application_number=result.get("application_number", ""),
        items=items_with_text,
    )
    conclusion = llm.generate(prompt, schema=ClaimConclusionResult, temperature=0.0)

    result["claim_conclusion"] = conclusion.model_dump()
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True


def _result_path(application_number: str, model: str) -> Path:
    return (
        Path("data")
        / "analysis"
        / application_number
        / model.replace("/", "__")
        / "result.json"
    )


def main(force: bool = False, dry_run: bool = False) -> None:
    total = skipped = changed = failed = 0

    for application_number in APPLICATION_NUMBERS:
        for model in MODELS:
            path = _result_path(application_number, model)
            if not path.exists():
                print(f"[SKIP] {path} — 파일 없음")
                skipped += 1
                continue

            total += 1
            if dry_run:
                print(f"[DRY]  {path}")
                continue

            try:
                llm = _make_llm(model)
                did_change = enrich_one(path, llm, force=force)
                status = "[OK]  " if did_change else "[SKIP]"
                suffix = "" if did_change else " — claim_conclusion 이미 존재"
                print(f"{status} {path}{suffix}")
                if did_change:
                    changed += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"[ERR]  {path} — {e}")
                failed += 1

    print(f"\n완료: total={total} changed={changed} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="기존 claim_conclusion 덮어쓰기")
    parser.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 대상 목록만 출력")
    args = parser.parse_args()
    main(force=args.force, dry_run=args.dry_run)
```

- [ ] **Step 4: 테스트 통과 확인**

```
uv run pytest tests/unit/test_claim_conclusion.py -v
```
Expected: 전부 PASSED

- [ ] **Step 5: dry-run 동작 확인**

```
uv run python scripts/enrich_claim_conclusion.py --dry-run
```
Expected: 존재하는 result.json 경로들 출력, `[DRY]` 또는 `[SKIP]` 접두사, LLM 호출 없음.

- [ ] **Step 6: 커밋**

```bash
git add scripts/enrich_claim_conclusion.py tests/unit/test_claim_conclusion.py
git commit -m "feat: complete enrich_claim_conclusion post-processing script"
```

---

## Task 5: 보고서 통계 섹션 추가

**Files:**
- Modify: `scripts/report_agreement.py`
- Modify: `tests/unit/test_claim_conclusion.py`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/unit/test_claim_conclusion.py`에 추가:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from report_agreement import (
    ConclusionRecord,
    _collect_conclusion_records,
    _build_conclusion_section,
)


def _write_result_with_conclusion(path: Path, verdicts: list[tuple[int, str, str]]) -> None:
    data = {
        "application_number": "10-test",
        "llm_model": "anthropic/claude-sonnet-4.6",
        "claim_conclusion": {
            "items": [
                {
                    "claim_number": cn,
                    "rejection_type": rt,
                    "merged_from": [],
                    "our_verdict": v,
                    "our_reasoning": "...",
                }
                for cn, rt, v in verdicts
            ]
        },
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_collect_conclusion_records(tmp_path):
    result_path = tmp_path / "result.json"
    _write_result_with_conclusion(
        result_path,
        [(1, "진보성", "동의"), (2, "신규성", "반대")],
    )
    records = list(_collect_conclusion_records(result_path, "10-test", "anthropic/claude-sonnet-4.6"))
    assert len(records) == 2
    assert records[0].our_verdict == "동의"
    assert records[1].our_verdict == "반대"


def test_collect_conclusion_records_skips_missing_verdict(tmp_path):
    result_path = tmp_path / "result.json"
    data = {
        "application_number": "10-test",
        "llm_model": "anthropic/claude-sonnet-4.6",
        "claim_conclusion": {
            "items": [{"claim_number": 1, "rejection_type": "진보성", "our_verdict": None}]
        },
    }
    result_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    records = list(_collect_conclusion_records(result_path, "10-test", "anthropic/claude-sonnet-4.6"))
    assert len(records) == 0


def test_build_conclusion_section_strict_loose():
    records = [
        ConclusionRecord("10-A", "model-X", 1, "진보성", "동의"),
        ConclusionRecord("10-A", "model-X", 2, "진보성", "부분동의"),
        ConclusionRecord("10-A", "model-X", 3, "진보성", "반대"),
    ]
    section = _build_conclusion_section(records)
    assert "33.3%" in section   # strict: 1/3
    assert "66.7%" in section   # loose: 2/3


def test_build_conclusion_section_empty():
    section = _build_conclusion_section([])
    assert "enrich_claim_conclusion" in section
```

- [ ] **Step 2: 테스트 실패 확인**

```
uv run pytest tests/unit/test_claim_conclusion.py::test_collect_conclusion_records -v
```
Expected: `ImportError: cannot import name 'ConclusionRecord' from 'report_agreement'`

- [ ] **Step 3: report_agreement.py 수정 — 임포트 및 상수 추가**

`scripts/report_agreement.py` 파일 상단의 기존 `@dataclass` 및 `from dataclasses import dataclass` 블록 바로 아래에 추가:

```python
VERDICT_LABELS = ["동의", "부분동의", "반대"]


@dataclass
class ConclusionRecord:
    application_number: str
    model: str
    claim_number: int
    rejection_type: str
    our_verdict: str
```

- [ ] **Step 4: report_agreement.py 수정 — 수집·빌드 함수 추가**

`_collect_records` 함수 바로 아래에 추가:

```python
def _collect_conclusion_records(
    path: Path,
    expected_application_number: str,
    expected_model: str,
):
    result = _load_json(path)
    application_number = result.get("application_number", expected_application_number)
    model = result.get("llm_model") or expected_model
    conclusion = result.get("claim_conclusion")
    if not conclusion:
        return
    for item in conclusion.get("items", []):
        verdict = item.get("our_verdict")
        if not verdict:
            continue
        yield ConclusionRecord(
            application_number=application_number,
            model=model,
            claim_number=item["claim_number"],
            rejection_type=item["rejection_type"],
            our_verdict=verdict,
        )


def _collect_all_conclusion_records() -> list[ConclusionRecord]:
    records: list[ConclusionRecord] = []
    for application_number in APPLICATION_NUMBERS:
        for model in MODELS:
            path = _result_path(application_number, model)
            if not path.exists():
                continue
            records.extend(
                _collect_conclusion_records(path, application_number, model)
            )
    return records


def _build_conclusion_section(records: list[ConclusionRecord]) -> str:
    if not records:
        return (
            "데이터 없음 — `uv run python scripts/enrich_claim_conclusion.py` 를 먼저 실행하세요.\n"
        )

    lines: list[str] = []

    # 모델별 strict / loose
    by_model: dict[str, list[ConclusionRecord]] = defaultdict(list)
    for r in records:
        by_model[r.model].append(r)

    model_rows = []
    for model in MODELS:
        recs = by_model[model]
        if not recs:
            model_rows.append([model, "—", "—", "0"])
            continue
        total = len(recs)
        strict = sum(1 for r in recs if r.our_verdict == "동의")
        loose = sum(1 for r in recs if r.our_verdict in ("동의", "부분동의"))
        model_rows.append([
            model,
            f"{strict / total * 100:.1f}% ({strict}/{total})",
            f"{loose / total * 100:.1f}% ({loose}/{total})",
            str(total),
        ])

    lines += [
        "### 모델별 Strict / Loose Agreement",
        "",
        "> Strict = 동의만 / Loose = 동의 + 부분동의",
        "",
        _markdown_table(
            ["Model", "Strict Agreement", "Loose Agreement", "Total"],
            model_rows,
        ),
        "",
    ]

    # 거절유형별 strict / loose
    by_type: dict[str, list[ConclusionRecord]] = defaultdict(list)
    for r in records:
        by_type[r.rejection_type].append(r)

    type_rows = []
    for rtype in sorted(by_type.keys()):
        recs = by_type[rtype]
        total = len(recs)
        strict = sum(1 for r in recs if r.our_verdict == "동의")
        loose = sum(1 for r in recs if r.our_verdict in ("동의", "부분동의"))
        type_rows.append([rtype, f"{strict / total * 100:.1f}%", f"{loose / total * 100:.1f}%", str(total)])

    lines += [
        "### 거절유형별 Strict / Loose Agreement",
        "",
        _markdown_table(["거절유형", "Strict", "Loose", "Total"], type_rows),
        "",
    ]

    # 문서×모델별 loose agreement
    by_doc_model: dict[tuple[str, str], list[ConclusionRecord]] = defaultdict(list)
    for r in records:
        by_doc_model[(r.application_number, r.model)].append(r)

    doc_rows = []
    for app in APPLICATION_NUMBERS:
        row = [app]
        for model in MODELS:
            recs = by_doc_model[(app, model)]
            if not recs:
                row.append("—")
            else:
                total = len(recs)
                loose = sum(1 for r in recs if r.our_verdict in ("동의", "부분동의"))
                row.append(f"{loose / total * 100:.1f}% ({loose}/{total})")
        doc_rows.append(row)

    lines += [
        "### 문서별 Loose Agreement",
        "",
        _markdown_table(["Application", *MODELS], doc_rows),
        "",
    ]

    return "\n".join(lines)
```

- [ ] **Step 5: `_build_report` 함수에 섹션 삽입**

`scripts/report_agreement.py`의 `_build_report` 함수 내 `## 5. 해석 메모` 섹션 앞에 다음을 추가:

```python
    conclusion_records = _collect_all_conclusion_records()
    lines += [
        "",
        "---",
        "",
        "# 청구항 거절 결론 통계",
        "",
        "> **비교 단위:** 거절된 개별 청구항 (신규성+진보성 동시 거절은 신규성 1건으로 집계)",
        "> **라벨:** 동의 / 부분동의 / 반대",
        "> **주의:** 위 구성요소 대비 통계(분모=row 수)와 이 섹션(분모=청구항 수)은 단위가 다르므로 수치를 합산하지 마십시오.",
        "",
        _build_conclusion_section(conclusion_records),
    ]
```

- [ ] **Step 6: 테스트 통과 확인**

```
uv run pytest tests/unit/test_claim_conclusion.py -v
```
Expected: 전부 PASSED

- [ ] **Step 7: 보고서 생성 확인**

```
uv run python scripts/report_agreement.py
```
Expected: `reports/agreement_report.md` 생성. 파일 하단에 "청구항 거절 결론 통계" 섹션 존재. claim_conclusion 데이터 없으면 "데이터 없음" 문구 출력.

- [ ] **Step 8: 커밋**

```bash
git add scripts/report_agreement.py tests/unit/test_claim_conclusion.py
git commit -m "feat: add claim conclusion statistics section to agreement report"
```

---

## 실행 순서 (구현 완료 후)

```bash
# 1. 모든 result.json에 claim_conclusion 추가 (문서 10개 × 모델 3개 = 30회 LLM 호출)
uv run python scripts/enrich_claim_conclusion.py

# 2. 보고서 생성
uv run python scripts/report_agreement.py

# 3. 결과 확인
cat reports/agreement_report.md

# 특정 result.json만 재처리 (이미 enriched된 것 포함)
uv run python scripts/enrich_claim_conclusion.py --force
```

---

## Self-Review

**스펙 커버리지:**
- [x] 신규성+진보성 병합 → Task 2 `build_conclusion_items`
- [x] 동의/부분동의/반대 라벨 → Task 1 `ClaimConclusionItem`
- [x] 종속항 thin reasoning 처리 → Task 3 프롬프트 지침
- [x] reasoning 저장 → `ClaimConclusionItem.our_reasoning`
- [x] strict/loose agreement → Task 5 `_build_conclusion_section`
- [x] 거절유형별 통계 → Task 5
- [x] 문서별 통계 → Task 5
- [x] 기존 result.json 하위 호환 → `claim_conclusion: ClaimConclusionResult | None = None`
- [x] 파이프라인 무변경 → `pipeline.py` 미포함
- [x] 프롬프트 템플릿 → Task 3

**타입 일관성:**
- `build_conclusion_items` → `list[dict]` (Task 2, 4에서 동일하게 사용)
- `enrich_one(result_path, llm, force)` → `bool` (Task 4 정의, 테스트 일치)
- `ConclusionRecord` dataclass → Task 5에서 정의, 테스트에서 import
- `_collect_conclusion_records` → generator → Task 5 정의, 테스트 `list()` 호출로 소비
