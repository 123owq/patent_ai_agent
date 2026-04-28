"""
실제 LLM API를 호출하는 E2E 시연 테스트.
환경변수 ANTHROPIC_API_KEY 또는 OPENAI_API_KEY 필요.
평소엔 skip, 시연 전 수동 실행.

실행 방법:
  LLM_PROVIDER=claude ANTHROPIC_API_KEY=<key> uv run pytest tests/integration/test_e2e_demo.py -v -s
"""
import os
import json
import pytest
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "10-2014-0036561"

_HAS_API_KEY = bool(
    os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
)


@pytest.mark.skipif(not _HAS_API_KEY, reason="LLM API 키 없음 — 시연 시 실행")
def test_full_pipeline_with_real_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    # 입력 파일 배치
    input_dir = tmp_path / "input" / "10-2014-0036561"
    input_dir.mkdir(parents=True)
    (input_dir / "patent.json").write_bytes((FIXTURE_DIR / "patent.json").read_bytes())
    (input_dir / "office_action.json").write_bytes(
        (FIXTURE_DIR / "office_action.json").read_bytes()
    )
    prior_dir = input_dir / "prior_arts"
    prior_dir.mkdir()
    for f in (FIXTURE_DIR / "prior_arts").glob("*.json"):
        (prior_dir / f.name).write_bytes(f.read_bytes())

    from patent_agent.llm import get_llm
    from patent_agent.core.pipeline import run_analysis
    from patent_agent.api.routers.analysis import _adapt_patent, _adapt_prior_art
    from patent_agent.models.input import OfficeActionRaw
    from patent_agent.core.storage import (
        load_input_patent,
        load_input_office_action,
        load_input_prior_arts,
    )

    llm = get_llm()
    patent_raw = load_input_patent("10-2014-0036561")
    oa_raw = load_input_office_action("10-2014-0036561")
    prior_arts_raw = load_input_prior_arts("10-2014-0036561")

    patent = _adapt_patent("10-2014-0036561", patent_raw)
    oa = OfficeActionRaw(application_number="10-2014-0036561", raw_dict=oa_raw)
    prior_arts = [_adapt_prior_art(i, r) for i, r in enumerate(prior_arts_raw)]

    steps_recorded = []

    def progress_cb(step: str, ratio: float) -> None:
        steps_recorded.append((step, ratio))
        print(f"  [{ratio:.0%}] {step}")

    print("\n=== E2E 분석 시작 ===")
    result = run_analysis(patent, oa, prior_arts, llm, progress_cb)
    print("=== E2E 분석 완료 ===")

    # ── 정량 지표 검증 ─────────────────────────────────────────────
    assert result.application_number == "10-2014-0036561"
    assert result.claim_parse.total_claims == 7, "청구항 7개 파싱 필수"
    assert 1 in result.claim_parse.independent_claims
    assert sorted(result.office_action.rejected_claim_numbers) == [1, 4, 5, 6, 7]
    assert len(result.claim_chart.charts) > 0
    assert result.strategy.offensive.strategy_type == "공격"
    assert result.strategy.defensive.strategy_type == "방어"
    assert len(steps_recorded) >= 6

    # ── agreement_rate 측정 ───────────────────────────────────────
    all_rows = [row for chart in result.claim_chart.charts for row in chart.rows]
    rows_with_agreement = [r for r in all_rows if r.agreement is not None]
    if rows_with_agreement:
        agree_count = sum(1 for r in rows_with_agreement if r.agreement == "일치")
        rate = agree_count / len(rows_with_agreement)
        print(f"\nClaim Chart agreement_rate: {rate:.2%} "
              f"({agree_count}/{len(rows_with_agreement)}) "
              f"[목표: ≥ 0.85]")

    # ── spec_basis validity ───────────────────────────────────────
    spec = patent.spec_paragraphs
    spec_errors = [
        f"청구항 {ac.claim_number}: '{para_id}' 없음"
        for ac in result.amendment.defensive_draft.amended_claims
        for para_id in ac.spec_basis
        if para_id not in spec
    ]
    assert spec_errors == [], f"spec_basis 검증 실패: {spec_errors}"

    print(f"분석 ID: {result.analysis_id}")
    print(f"에러: {[e.message for e in result.errors]}")
    print("E2E 시연 테스트 통과 ✓")
