"""
usage: uv run python scripts/run_pipeline.py <출원번호>
uv run python scripts/run_pipeline.py 10-2014-0036561

"""
import sys
import os
from dotenv import load_dotenv
from patent_agent.llm import get_llm
from patent_agent.core.pipeline import run_analysis
from patent_agent.core.storage import (
    load_input_patent,
    load_input_office_action,
    load_input_prior_arts,
)
from patent_agent.models.input import OfficeActionRaw
from patent_agent.api.routers.analysis import _adapt_patent, _adapt_prior_art


def main(application_number: str) -> None:
    load_dotenv()
    llm = get_llm()
    llm_model: str = getattr(llm, "model", "")

    print(f"[{application_number}] 모델: {llm_model}")

    from patent_agent.core.storage import load_analysis
    force_rerun = os.getenv("FORCE_RERUN", "").lower() in {"1", "true", "yes", "on"}
    if not force_rerun:
        try:
            cached = load_analysis(application_number)
            if cached.llm_model == llm_model:
                print("이미 결과 있음. 종료.")
                return
            elif cached.llm_model == "":
                print("모델이름 빈칸")
                return
        except FileNotFoundError:
            pass
    
    print("분석 시작...")
    patent_raw = load_input_patent(application_number)
    oa_raw = load_input_office_action(application_number)
    prior_arts_raw = load_input_prior_arts(application_number)

    patent = _adapt_patent(application_number, patent_raw)
    oa = OfficeActionRaw(application_number=application_number, raw_dict=oa_raw)
    prior_arts = [_adapt_prior_art(i, raw) for i, raw in enumerate(prior_arts_raw)]

    def progress_cb(step: str, ratio: float) -> None:
        print(f"  [{ratio*100:5.1f}%] {step}")

    result = run_analysis(patent, oa, prior_arts, llm, progress_cb, llm_model=llm_model)

    if result.errors:
        print("\n[경고] 비치명적 에러:")
        for e in result.errors:
            print(f"  - {e.tool_name}: {e.message}")

    print(f"\n완료 → data/analysis/{application_number}/{llm_model.replace('/', '__')}/result.json")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: uv run python scripts/run_pipeline.py <출원번호>")
        sys.exit(1)
    main(sys.argv[1])
