"""
Usage:
  uv run python scripts/run_batch.py

Set the model in .env as usual, then edit APPLICATION_NUMBERS below.
Each application is executed sequentially through run_pipeline.main().
If one run fails, the batch stops immediately. Completed results remain cached.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from run_pipeline import main as run_pipeline
from summarize_agreement import summarize
from enrich_claim_conclusion import enrich_one
from patent_agent.llm import get_llm

#uv run python scripts/run_batch.py
#uv run python scripts/run_batch_copy.py
#uv run python scripts/run_batch_copy2.py
#uv run python scripts/run_batch_copy3.py
#uv run python scripts/run_batch_copy4.py
APPLICATION_NUMBERS: list[str] = [
    "10-2020-0019150",
    "10-2022-0039209",
    "10-2020-0001439"
]


def _result_path(application_number: str) -> Path:
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    model = os.getenv("OPENAI_MODEL") or os.getenv("CLAUDE_MODEL") or ""
    if model:
        return data_dir / "analysis" / application_number / model.replace("/", "__") / "result.json"
    return data_dir / "analysis" / application_number / "result.json"


def main() -> None:
    load_dotenv()

    if not APPLICATION_NUMBERS:
        raise ValueError("APPLICATION_NUMBERS is empty.")

    completed_result_paths: list[Path] = []
    total = len(APPLICATION_NUMBERS)
    for idx, application_number in enumerate(APPLICATION_NUMBERS, start=1):
        print(f"\n[batch {idx}/{total}] application={application_number}")
        run_pipeline(application_number)

        result_path = _result_path(application_number)
        if not result_path.exists():
            raise FileNotFoundError(f"Result not found after pipeline run: {result_path}")

        completed_result_paths.append(result_path)

        try:
            enrich_one(result_path, get_llm(), force=False)
        except Exception as e:
            print(f"[경고] claim_conclusion enrichment 실패: {e}")

        print(f"\n[batch {idx}/{total}] summary for {application_number}")
        summarize([result_path])

    print(f"\n[batch] completed {total} runs")
    print("\n[batch] summary for all completed runs")
    summarize(completed_result_paths)


if __name__ == "__main__":
    main()
