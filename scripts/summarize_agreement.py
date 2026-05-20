"""
Usage:
  uv run python scripts/summarize_agreement.py

Edit RESULT_PATHS below. The script prints examiner-vs-LLM agreement statistics
from result.json files.
"""

# uv run python scripts/summarize_agreement.py
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


RESULT_PATHS: list[str] = [
    "data/analysis/10-2014-0036561/deepseek__deepseek-v4-flash/result.json",
]

LABELS = ["동일", "유사", "차이"]


def _load_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_rows(result: dict[str, Any]):
    for chart in result.get("claim_chart", {}).get("charts", []):
        claim_number = chart.get("target_claim_number")
        for row in chart.get("rows", []):
            yield claim_number, row


def _model_label(result: dict[str, Any], path: Path) -> str:
    return result.get("llm_model") or path.parent.name.replace("__", "/")


def _empty_bucket() -> dict[str, int]:
    return {
        "total_rows": 0,
        "old_rows_without_comparison_id": 0,
        "comparable_rows": 0,
        "matched_rows": 0,
        "mismatched_rows": 0,
        "missing_examiner_rows": 0,
    }


def _add_row(bucket: dict[str, int], examiner_match: str | None, our_match: str | None) -> None:
    bucket["total_rows"] += 1
    if examiner_match is None:
        bucket["missing_examiner_rows"] += 1
        return

    bucket["comparable_rows"] += 1
    if examiner_match == our_match:
        bucket["matched_rows"] += 1
    else:
        bucket["mismatched_rows"] += 1


def _add_old_row(bucket: dict[str, int]) -> None:
    bucket["total_rows"] += 1
    bucket["old_rows_without_comparison_id"] += 1


def _rate(bucket: dict[str, int]) -> float:
    comparable = bucket["comparable_rows"]
    return bucket["matched_rows"] / comparable if comparable else 0.0


def _print_bucket(label: str, bucket: dict[str, int]) -> None:
    print(
        f"{label}: "
        f"agreement={_rate(bucket) * 100:.1f}% "
        f"matched={bucket['matched_rows']} "
        f"mismatched={bucket['mismatched_rows']} "
        f"comparable={bucket['comparable_rows']} "
        f"missing_examiner={bucket['missing_examiner_rows']} "
        f"old_rows={bucket['old_rows_without_comparison_id']} "
        f"total={bucket['total_rows']}"
    )


def summarize(result_paths: list[str | Path] | None = None) -> None:
    paths = result_paths if result_paths is not None else RESULT_PATHS

    by_model: dict[str, dict[str, int]] = defaultdict(_empty_bucket)
    by_document: dict[tuple[str, str], dict[str, int]] = defaultdict(_empty_bucket)
    by_claim: dict[tuple[str, str, int], dict[str, int]] = defaultdict(_empty_bucket)
    label_counts_by_model: dict[str, Counter[str]] = defaultdict(Counter)
    confusion_by_model: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)

    for raw_path in paths:
        path = Path(raw_path)
        result = _load_result(path)
        model = _model_label(result, path)
        application_number = result.get("application_number", path.parent.parent.name)

        for claim_number, row in _iter_rows(result):
            if not row.get("comparison_id"):
                _add_old_row(by_model[model])
                _add_old_row(by_document[(model, application_number)])
                if claim_number is not None:
                    _add_old_row(by_claim[(model, application_number, int(claim_number))])
                continue

            examiner_match = row.get("examiner_match")
            our_match = row.get("our_match")

            _add_row(by_model[model], examiner_match, our_match)
            _add_row(by_document[(model, application_number)], examiner_match, our_match)
            if claim_number is not None:
                _add_row(by_claim[(model, application_number, int(claim_number))], examiner_match, our_match)
            if examiner_match is not None and our_match is not None:
                label_counts_by_model[model][our_match] += 1
                confusion_by_model[model][(examiner_match, our_match)] += 1

    print("\n=== By Model ===")
    for model, bucket in sorted(by_model.items()):
        _print_bucket(model, bucket)

    print("\n=== By Document ===")
    for (model, application_number), bucket in sorted(by_document.items()):
        _print_bucket(f"{model} / {application_number}", bucket)

    print("\n=== By Claim ===")
    for (model, application_number, claim_number), bucket in sorted(by_claim.items()):
        _print_bucket(f"{model} / {application_number} / claim {claim_number}", bucket)

    print("\n=== LLM Label Distribution ===")
    for model, counts in sorted(label_counts_by_model.items()):
        total = sum(counts.values())
        parts = []
        for label in LABELS:
            count = counts[label]
            rate = count / total * 100 if total else 0.0
            parts.append(f"{label}={count} ({rate:.1f}%)")
        print(f"{model}: " + ", ".join(parts))

    print("\n=== Examiner vs LLM Matrix ===")
    print("Rows = examiner_match, columns = LLM our_match. Diagonal cells are agreements.")
    for model, counts in sorted(confusion_by_model.items()):
        print(f"\n{model}")
        print("examiner\\llm | " + " | ".join(f"{label:>4}" for label in LABELS))
        print("-" * 33)
        for examiner_label in LABELS:
            row_counts = [counts[(examiner_label, llm_label)] for llm_label in LABELS]
            print(f"{examiner_label:12} | " + " | ".join(f"{n:>4}" for n in row_counts))

    # claim_conclusion 통계
    verdict_labels = ["동의", "부분동의", "반대"]
    conclusion_by_model: dict[str, list[str]] = {}
    for raw_path in paths:
        path = Path(raw_path)
        result = _load_result(path)
        model = _model_label(result, path)
        conclusion = result.get("claim_conclusion")
        if not conclusion:
            continue
        verdicts = [
            item["our_verdict"]
            for item in conclusion.get("items", [])
            if item.get("our_verdict")
        ]
        if verdicts:
            conclusion_by_model.setdefault(model, []).extend(verdicts)

    if conclusion_by_model:
        print("\n=== Claim Conclusion (동의/부분동의/반대) ===")
        for model, verdicts in sorted(conclusion_by_model.items()):
            total = len(verdicts)
            strict = verdicts.count("동의")
            loose = strict + verdicts.count("부분동의")
            dist = ", ".join(
                f"{v}={verdicts.count(v)}" for v in verdict_labels
            )
            print(
                f"{model}: strict={strict/total*100:.1f}% loose={loose/total*100:.1f}%"
                f" ({dist}) total={total}"
            )


def main() -> None:
    summarize()


if __name__ == "__main__":
    main()
