# scripts/enrich_claim_conclusion.py
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Windows 터미널에서 한글 출력 보장
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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

    charts_by_claim = {
        c["target_claim_number"]: c["rows"]
        for c in result.get("claim_chart", {}).get("charts", [])
    }

    items_with_text = [
        {
            **item,
            "claim_text": claims_by_number.get(item["claim_number"], {}).get(
                "original_text", "(청구항 원문 없음)"
            ),
            "prior_art_rows": charts_by_claim.get(item["claim_number"], []),
        }
        for item in items
    ]

    prompt = render(
        "claim_conclusion.j2",
        application_number=result.get("application_number", ""),
        items=items_with_text,
    )
    conclusion = llm.generate(prompt, schema=ClaimConclusionResult, temperature=0.0)

    # LLM이 merged_from을 임의로 채울 수 있으므로 원본 값으로 덮어씀
    merged_from_map = {
        (item["claim_number"], item["rejection_type"]): item["merged_from"]
        for item in items
    }
    for ci in conclusion.items:
        ci.merged_from = merged_from_map.get((ci.claim_number, ci.rejection_type), [])

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
                print(f"[SKIP] {path} - 파일 없음")
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
                suffix = "" if did_change else " - claim_conclusion 이미 존재"
                print(f"{status} {path}{suffix}")
                if did_change:
                    changed += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"[ERR]  {path} - {e}")
                failed += 1

    print(f"\n완료: total={total} changed={changed} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="기존 claim_conclusion 덮어쓰기")
    parser.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 대상 목록만 출력")
    args = parser.parse_args()
    main(force=args.force, dry_run=args.dry_run)
