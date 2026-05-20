"""
Usage:
  uv run python scripts/report_agreement.py

Generate a Markdown report comparing examiner-vs-LLM agreement for the fixed
set of 10 applications and 3 target models.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


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

LABELS = ["동일", "유사", "차이"]
REPORT_PATH = Path("reports/agreement_report.md")


@dataclass
class RowRecord:
    application_number: str
    model: str
    claim_number: int | None
    comparison_id: str
    examiner_match: str | None
    our_match: str | None


VERDICT_LABELS = ["동의", "부분동의", "반대"]


@dataclass
class ConclusionRecord:
    application_number: str
    model: str
    claim_number: int
    rejection_type: str
    our_verdict: str


def _model_dir(model: str) -> str:
    return model.replace("/", "__")


def _result_path(application_number: str, model: str) -> Path:
    return Path("data") / "analysis" / application_number / _model_dir(model) / "result.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_records(path: Path, expected_application_number: str, expected_model: str):
    result = _load_json(path)
    application_number = result.get("application_number", expected_application_number)
    model = result.get("llm_model") or expected_model

    for chart in result.get("claim_chart", {}).get("charts", []):
        claim_number = chart.get("target_claim_number")
        for row in chart.get("rows", []):
            comparison_id = row.get("comparison_id")
            if not comparison_id:
                continue
            yield RowRecord(
                application_number=application_number,
                model=model,
                claim_number=claim_number,
                comparison_id=comparison_id,
                examiner_match=row.get("examiner_match"),
                our_match=row.get("our_match"),
            )


def _collect_records() -> tuple[list[RowRecord], list[tuple[str, str, Path]]]:
    records: list[RowRecord] = []
    missing: list[tuple[str, str, Path]] = []

    for application_number in APPLICATION_NUMBERS:
        for model in MODELS:
            path = _result_path(application_number, model)
            if not path.exists():
                missing.append((application_number, model, path))
                continue
            records.extend(_iter_records(path, application_number, model))

    return records, missing


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


def _empty_bucket() -> dict[str, int]:
    return {
        "total": 0,
        "comparable": 0,
        "matched": 0,
        "mismatched": 0,
        "missing_examiner": 0,
    }


def _add_record(bucket: dict[str, int], record: RowRecord) -> None:
    bucket["total"] += 1
    if record.examiner_match is None:
        bucket["missing_examiner"] += 1
        return
    bucket["comparable"] += 1
    if record.examiner_match == record.our_match:
        bucket["matched"] += 1
    else:
        bucket["mismatched"] += 1


def _rate(bucket: dict[str, int]) -> float:
    return bucket["matched"] / bucket["comparable"] * 100 if bucket["comparable"] else 0.0


def _bucket_cells(bucket: dict[str, int]) -> list[str]:
    return [
        f"{_rate(bucket):.1f}%",
        str(bucket["matched"]),
        str(bucket["mismatched"]),
        str(bucket["comparable"]),
        str(bucket["missing_examiner"]),
        str(bucket["total"]),
    ]


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _build_report(records: list[RowRecord], missing: list[tuple[str, str, Path]]) -> str:
    by_model: dict[str, dict[str, int]] = defaultdict(_empty_bucket)
    by_document: dict[tuple[str, str], dict[str, int]] = defaultdict(_empty_bucket)
    label_counts: dict[str, Counter[str]] = defaultdict(Counter)
    matrices: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)

    for record in records:
        _add_record(by_model[record.model], record)
        _add_record(by_document[(record.application_number, record.model)], record)
        if record.examiner_match is not None and record.our_match is not None:
            label_counts[record.model][record.our_match] += 1
            matrices[record.model][(record.examiner_match, record.our_match)] += 1

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [
        "# LLM 구성 대비 일치율 비교 보고서",
        "",
        f"- 생성 시각: {generated_at}",
        f"- 대상 문서: {len(APPLICATION_NUMBERS)}개 출원",
        f"- 대상 모델: {len(MODELS)}개",
        "- 비교 단위: 의견제출통지서 전체 청구항이 아니라, 심사관이 구성비교표 형태로 명시한 comparison row",
        "- 일치 기준: `examiner_match == our_match`",
        "- 라벨: 동일 / 유사 / 차이",
        "",
        "## 대상 출원번호",
        "",
        ", ".join(f"`{application_number}`" for application_number in APPLICATION_NUMBERS),
        "",
        "## 대상 모델",
        "",
        "\n".join(f"- `{model}`" for model in MODELS),
        "",
        "## 1. 모델별 전체 요약",
        "",
    ]

    model_rows = []
    for model in MODELS:
        bucket = by_model[model]
        model_rows.append([model, *_bucket_cells(bucket)])
    lines.append(_markdown_table(
        ["Model", "Agreement", "Matched", "Mismatched", "Comparable", "Missing Examiner", "Total"],
        model_rows,
    ))

    lines.extend([
        "",
        "## 2. 문서별 모델 일치율",
        "",
    ])

    doc_headers = ["Application", *MODELS, "Comparable Rows"]
    doc_rows = []
    for application_number in APPLICATION_NUMBERS:
        comparable_counts = []
        row = [application_number]
        for model in MODELS:
            bucket = by_document[(application_number, model)]
            row.append(f"{_rate(bucket):.1f}% ({bucket['matched']}/{bucket['comparable']})")
            comparable_counts.append(bucket["comparable"])
        row.append("/".join(str(count) for count in comparable_counts))
        doc_rows.append(row)
    lines.append(_markdown_table(doc_headers, doc_rows))

    lines.extend([
        "",
        "## 3. 모델별 LLM 라벨 분포",
        "",
    ])
    label_rows = []
    for model in MODELS:
        counts = label_counts[model]
        total = sum(counts.values())
        row = [model]
        for label in LABELS:
            count = counts[label]
            rate = count / total * 100 if total else 0.0
            row.append(f"{count} ({rate:.1f}%)")
        row.append(str(total))
        label_rows.append(row)
    lines.append(_markdown_table(["Model", *LABELS, "Total"], label_rows))

    lines.extend([
        "",
        "## 4. Examiner vs LLM Matrix",
        "",
        "행은 심사관 판단, 열은 LLM 판단입니다. 대각선 값이 일치 row입니다.",
        "",
    ])
    for model in MODELS:
        lines.extend([f"### {model}", ""])
        matrix_rows = []
        counts = matrices[model]
        for examiner_label in LABELS:
            matrix_rows.append([
                examiner_label,
                *[str(counts[(examiner_label, llm_label)]) for llm_label in LABELS],
            ])
        lines.append(_markdown_table(["Examiner \\ LLM", *LABELS], matrix_rows))
        lines.append("")

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

    lines.extend([
        "## 5. 해석 메모",
        "",
        "- 이 보고서는 거절 대상 청구항 전체 수가 아니라, 심사관이 명시적으로 구성 대비한 row를 기준으로 합니다.",
        "- 따라서 통지서에 언급된 청구항 수보다 비교 row 수가 적을 수 있습니다.",
        "- 모델별 row 수가 다르면 해당 모델의 result.json 생성 실패, 누락, 또는 old format row 여부를 확인해야 합니다.",
        "- `Missing Examiner`가 0에 가까울수록 fixed examiner row 기반 비교가 안정적으로 수행된 것입니다.",
        "",
    ])

    if missing:
        lines.extend(["## 6. 누락된 결과 파일", ""])
        missing_rows = [
            [application_number, model, str(path)]
            for application_number, model, path in missing
        ]
        lines.append(_markdown_table(["Application", "Model", "Expected Path"], missing_rows))
        lines.append("")
    else:
        lines.extend(["## 6. 누락된 결과 파일", "", "없음", ""])

    return "\n".join(lines)


def main() -> None:
    records, missing = _collect_records()
    report = _build_report(records, missing)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"wrote {REPORT_PATH}")
    print(f"records={len(records)} missing_files={len(missing)}")


if __name__ == "__main__":
    main()

