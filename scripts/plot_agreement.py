"""
Usage:
  uv run python scripts/plot_agreement.py

Generates two PNG charts from claim_conclusion data (동의/부분동의/반대)
and prints a summary stats table.

Output:
  reports/fig1_model_distribution.png  — 모델별 판단 분포 (스택 막대)
  reports/fig2_document_strict.png     — 문서별 strict agreement (모델별 선)
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import matplotlib.font_manager as fm
import numpy as np

# Windows 한글 폰트 설정
for _fname in ["Malgun Gothic", "맑은 고딕", "NanumGothic", "AppleGothic"]:
    if any(_fname.lower() in f.name.lower() for f in fm.fontManager.ttflist):
        plt.rcParams["font.family"] = _fname
        break
plt.rcParams["axes.unicode_minus"] = False

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

MODEL_LABELS = ["Gemini", "GPT", "Claude"]
VERDICT_LABELS = ["동의", "부분동의", "반대"]
COLORS = {"동의": "#4C9BE8", "부분동의": "#F5A623", "반대": "#E85454"}
MODEL_COLORS = ["#4C9BE8", "#F5A623", "#6BCB77"]

DOC_LABELS = [f"#{i+1}" for i in range(len(APPLICATION_NUMBERS))]


def _result_path(application_number: str, model: str) -> Path:
    return (
        Path("data")
        / "analysis"
        / application_number
        / model.replace("/", "__")
        / "result.json"
    )


def _load_conclusions() -> dict[tuple[str, str], list[str]]:
    """Returns {(model, application_number): [verdict, ...]}"""
    data: dict[tuple[str, str], list[str]] = defaultdict(list)
    for model in MODELS:
        for app in APPLICATION_NUMBERS:
            path = _result_path(app, model)
            if not path.exists():
                continue
            result = json.loads(path.read_text(encoding="utf-8"))
            cc = result.get("claim_conclusion")
            if not cc:
                continue
            for item in cc.get("items", []):
                v = item.get("our_verdict")
                if v:
                    data[(model, app)].append(v)
    return data


def _model_distribution(data: dict) -> dict[str, dict[str, int]]:
    """모델별 전체 verdict 집계"""
    dist: dict[str, dict[str, int]] = {}
    for model in MODELS:
        counts = {v: 0 for v in VERDICT_LABELS}
        for app in APPLICATION_NUMBERS:
            for v in data.get((model, app), []):
                counts[v] = counts.get(v, 0) + 1
        dist[model] = counts
    return dist


def _strict_by_doc(data: dict) -> dict[str, list[float]]:
    """모델별 문서별 strict agreement (%)"""
    result: dict[str, list[float]] = {}
    for model in MODELS:
        rates = []
        for app in APPLICATION_NUMBERS:
            verdicts = data.get((model, app), [])
            if not verdicts:
                rates.append(float("nan"))
            else:
                rates.append(verdicts.count("동의") / len(verdicts) * 100)
        result[model] = rates
    return result


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    center = (p + z**2 / (2 * n)) / (1 + z**2 / n)
    margin = z * (p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5 / (1 + z**2 / n)
    return (max(0.0, center - margin) * 100, min(1.0, center + margin) * 100)


def plot_fig1(dist: dict[str, dict[str, int]], out_path: Path) -> None:
    """스택 막대: 모델별 동의/부분동의/반대 비율"""
    fig, ax = plt.subplots(figsize=(7, 4.5))

    x = np.arange(len(MODELS))
    bottoms = np.zeros(len(MODELS))

    for verdict in VERDICT_LABELS:
        totals = np.array([sum(dist[m].values()) for m in MODELS], dtype=float)
        counts = np.array([dist[m].get(verdict, 0) for m in MODELS], dtype=float)
        ratios = np.where(totals > 0, counts / totals * 100, 0)
        bars = ax.bar(x, ratios, bottom=bottoms, color=COLORS[verdict], label=verdict, width=0.5)
        for bar, ratio in zip(bars, ratios):
            if ratio >= 6:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_y() + bar.get_height() / 2,
                    f"{ratio:.1f}%",
                    ha="center", va="center", fontsize=9, color="white", fontweight="bold",
                )
        bottoms += ratios

    ax.set_xticks(x)
    ax.set_xticklabels(MODEL_LABELS, fontsize=11)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_ylim(0, 105)
    ax.set_ylabel("비율 (%)")
    ax.set_title("모델별 심사관 거절 결론 동의 분포", fontsize=12, fontweight="bold", pad=12)
    ax.legend(loc="upper right", fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"저장: {out_path}")


def plot_fig2(strict_by_doc: dict[str, list[float]], out_path: Path) -> None:
    """선 그래프: 문서별 strict agreement (모델별)"""
    fig, ax = plt.subplots(figsize=(9, 4.5))

    x = np.arange(len(APPLICATION_NUMBERS))
    for model, color, label in zip(MODELS, MODEL_COLORS, MODEL_LABELS):
        rates = strict_by_doc[model]
        valid = [(i, r) for i, r in enumerate(rates) if not np.isnan(r)]
        if not valid:
            continue
        xi, yi = zip(*valid)
        ax.plot(xi, yi, marker="o", color=color, label=label, linewidth=2, markersize=6)

    ax.set_xticks(x)
    ax.set_xticklabels(DOC_LABELS, fontsize=9)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_ylim(-5, 105)
    ax.set_xlabel("문서 (#1~#10)")
    ax.set_ylabel("Strict Agreement (%)")
    ax.set_title("문서별 Strict Agreement (동의 / 전체)", fontsize=12, fontweight="bold", pad=12)
    ax.legend(fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.spines[["top", "right"]].set_visible(False)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"저장: {out_path}")


def _build_summary_md(
    dist: dict[str, dict[str, int]],
    strict_by_doc: dict[str, list[float]],
) -> str:
    from datetime import datetime

    # 모델별 수치 미리 계산
    model_stats = {}
    for model, label in zip(MODELS, MODEL_LABELS):
        counts = dist[model]
        total = sum(counts.values())
        n_strict = counts.get("동의", 0)
        n_loose = n_strict + counts.get("부분동의", 0)
        strict_pct = n_strict / total * 100 if total else 0
        loose_pct = n_loose / total * 100 if total else 0
        ci_s = _wilson_ci(n_strict, total)
        ci_l = _wilson_ci(n_loose, total)
        model_stats[label] = dict(
            counts=counts, total=total,
            strict_pct=strict_pct, loose_pct=loose_pct,
            ci_s=ci_s, ci_l=ci_l,
        )

    best_strict = max(model_stats, key=lambda m: model_stats[m]["strict_pct"])
    best_loose  = max(model_stats, key=lambda m: model_stats[m]["loose_pct"])

    lines = [
        "# LLM × 특허 심사관 판단 일치율 보고서",
        "",
        f"> 생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "## 실험 개요",
        "",
        "특허 의견제출통지서(거절이유통지서)에서 심사관이 내린 **청구항별 거절 결론**을",
        "세 가지 LLM이 얼마나 동일하게 판단하는지 비교한 실험입니다.",
        "",
        f"- **대상 출원**: {len(APPLICATION_NUMBERS)}개 (한국 특허청 의견제출통지서)",
        f"- **비교 모델**: {', '.join(MODEL_LABELS)} ({len(MODELS)}개)",
        f"- **판단 단위**: 거절된 청구항 1건 = 1개 판단 (모델당 총 {list(model_stats.values())[0]['total']}건)",
        "  - 신규성 + 진보성이 동시에 거절된 청구항은 신규성 1건으로 합산",
        "",
        "---",
        "",
        "## 판단 라벨 정의",
        "",
        "LLM은 심사관의 각 거절 결론에 대해 다음 세 가지 중 하나로 판단합니다:",
        "",
        "| 라벨 | 의미 |",
        "|---|---|",
        "| **동의** | 심사관의 거절이 타당하다고 판단 |",
        "| **부분동의** | 거절 방향은 인정하나 근거나 범위에 이견 있음 |",
        "| **반대** | 심사관의 거절이 부당하다고 판단 |",
        "",
        "---",
        "",
        "## 측정 지표",
        "",
        "| 지표 | 계산식 | 의미 |",
        "|---|---|---|",
        "| **Strict Agreement** | 동의 수 / 전체 | LLM이 심사관과 완전히 같은 결론을 낸 비율 |",
        "| **Loose Agreement** | (동의 + 부분동의) / 전체 | LLM이 거절 방향성 자체에는 동의한 비율 |",
        "",
        "> Strict는 **자동화 가능성**, Loose는 **방향성 파악 능력**으로 해석할 수 있습니다.",
        "",
        "---",
        "",
        "## 모델별 결과",
        "",
        "| 모델 | 동의 | 부분동의 | 반대 | 합계 | Strict | 95% CI | Loose | 95% CI |",
        "|---|---:|---:|---:|---:|---:|---|---:|---|",
    ]

    for label in MODEL_LABELS:
        s = model_stats[label]
        lines.append(
            f"| {label} | {s['counts'].get('동의',0)} | {s['counts'].get('부분동의',0)} |"
            f" {s['counts'].get('반대',0)} | {s['total']} |"
            f" {s['strict_pct']:.1f}% | [{s['ci_s'][0]:.1f}%, {s['ci_s'][1]:.1f}%] |"
            f" {s['loose_pct']:.1f}% | [{s['ci_l'][0]:.1f}%, {s['ci_l'][1]:.1f}%] |"
        )

    lines += [
        "",
        "> **95% 신뢰구간**: 65건만 관찰했기 때문에 발생하는 추정 오차 범위입니다.",
        "> 예를 들어 Gemini Strict 84.6% [73.9%, 91.4%]는 \"케이스가 달랐다면 이 범위 안 어딘가로 나왔을 것\"이라는 의미입니다.",
        "> 구간이 좁을수록 결과를 더 신뢰할 수 있고, 구간이 넓을수록 샘플이 부족해 불확실합니다.",
        "",
        "### 주요 발견",
        "",
        f"- **Strict 1위**: {best_strict} ({model_stats[best_strict]['strict_pct']:.1f}%) — 심사관 판단과 가장 자주 완전히 일치",
        f"- **Loose 1위**: {best_loose} ({model_stats[best_loose]['loose_pct']:.1f}%) — 거절 방향성 파악에서 가장 높은 동의율",
    ]

    # Gemini 특이사항
    if model_stats.get("Gemini", {}).get("counts", {}).get("부분동의", -1) == 0:
        lines.append("- **Gemini**: 부분동의=0 — 이진 판단(동의/반대)만 사용, 다른 모델과 판단 스타일이 상이")

    lines += [
        "",
        "---",
        "",
        "## 문서별 Strict Agreement",
        "",
        "문서마다 청구항 수와 거절 난이도가 다르기 때문에 문서별 편차가 있습니다.",
        "",
        "| 출원번호 | " + " | ".join(MODEL_LABELS) + " |",
        "|---|" + "|".join(["---:"] * len(MODELS)) + "|",
    ]

    for i, app in enumerate(APPLICATION_NUMBERS):
        cells = []
        for model in MODELS:
            v = strict_by_doc[model][i]
            cells.append("—" if np.isnan(v) else f"{v:.1f}%")
        lines.append(f"| {app} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "---",
        "",
        "## 한계 및 유의사항",
        "",
        "1. **샘플 한정**: 10개 출원, 65건 판단 — 특허 전반에 대한 일반화는 제한적",
        "2. **문서 편향**: 10개 출원이 무작위 샘플이 아니므로 특정 기술 분야에 치우칠 수 있음",
        "3. **종속항 정보 제한**: 독립항과 달리 종속항의 거절 이유는 심사관이 한 줄만 기재하는 경우가 많아 LLM 판단 근거가 얇음",
        "4. **모델별 판단 스타일 차이**: 동일한 케이스에도 모델마다 라벨 선택 성향이 다름 (Gemini의 부분동의=0 참조)",
        "",
        "---",
        "",
        "## 그래프",
        "",
        "- **fig1_model_distribution.png**: 모델별 동의/부분동의/반대 비율을 스택 막대로 표시",
        "- **fig2_document_strict.png**: 10개 문서별 Strict Agreement를 모델별 선으로 표시",
        "",
    ]

    return "\n".join(lines)


def print_summary(dist: dict[str, dict[str, int]]) -> None:
    print("\n=== 모델별 판단 분포 및 95% CI ===")
    for model, label in zip(MODELS, MODEL_LABELS):
        counts = dist[model]
        total = sum(counts.values())
        n_strict = counts.get("동의", 0)
        n_loose = n_strict + counts.get("부분동의", 0)
        strict_pct = n_strict / total * 100 if total else 0
        loose_pct = n_loose / total * 100 if total else 0
        ci_strict = _wilson_ci(n_strict, total)
        ci_loose = _wilson_ci(n_loose, total)
        print(
            f"{label}: 동의={counts.get('동의',0)} 부분동의={counts.get('부분동의',0)} 반대={counts.get('반대',0)}"
            f" | strict={strict_pct:.1f}% [{ci_strict[0]:.1f}%,{ci_strict[1]:.1f}%]"
            f" | loose={loose_pct:.1f}% [{ci_loose[0]:.1f}%,{ci_loose[1]:.1f}%]"
        )


def main() -> None:
    out_dir = Path("reports")
    out_dir.mkdir(exist_ok=True)

    data = _load_conclusions()
    dist = _model_distribution(data)
    strict_by_doc = _strict_by_doc(data)

    plot_fig1(dist, out_dir / "fig1_model_distribution.png")
    plot_fig2(strict_by_doc, out_dir / "fig2_document_strict.png")
    print_summary(dist)

    md = _build_summary_md(dist, strict_by_doc)
    md_path = out_dir / "claim_conclusion_stats.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"저장: {md_path}")


if __name__ == "__main__":
    main()
