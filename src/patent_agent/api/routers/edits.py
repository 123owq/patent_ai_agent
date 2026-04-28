from __future__ import annotations
import copy
import json
import os
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from patent_agent.core.storage import load_analysis, load_analysis_version, save_analysis
from patent_agent.models.analysis import AnalysisResult, EditLogEntry

router = APIRouter(prefix="/api/v1/analysis", tags=["edits"])


class ApplyEditRequest(BaseModel):
    target_path: str
    new_value: str
    user_instruction: str | None = None


class RevertRequest(BaseModel):
    version: int


def _get_nested(obj: dict, path: str):
    parts = path.replace("][", ".").replace("[", ".").replace("]", "").split(".")
    for part in parts:
        obj = obj[int(part)] if part.isdigit() else obj[part]
    return obj


def _set_nested(obj: dict, path: str, value: object) -> dict:
    result = copy.deepcopy(obj)
    parts = path.replace("][", ".").replace("[", ".").replace("]", "").split(".")
    current = result
    for part in parts[:-1]:
        current = current[int(part)] if part.isdigit() else current[part]
    last = parts[-1]
    if last.isdigit():
        current[int(last)] = value
    else:
        current[last] = value
    return result


def _append_edit_log(application_number: str, entry: EditLogEntry) -> None:
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    log_path = data_dir / "analysis" / application_number / "edits.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(entry.model_dump_json() + "\n")


@router.post("/{application_number}/edits/apply", response_model=AnalysisResult)
def apply_edit(application_number: str, req: ApplyEditRequest):
    try:
        result = load_analysis(application_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")

    result_dict = json.loads(result.model_dump_json())
    before = str(_get_nested(result_dict, req.target_path))
    updated_dict = _set_nested(result_dict, req.target_path, req.new_value)
    updated_dict["version"] = result.version + 1
    updated_result = AnalysisResult.model_validate(updated_dict)
    save_analysis(updated_result)

    _append_edit_log(application_number, EditLogEntry(
        target_path=req.target_path,
        before=before,
        after=req.new_value,
        source="llm-proposed-user-applied",
        user_instruction=req.user_instruction,
    ))
    return updated_result


@router.post("/{application_number}/edits/revert", response_model=AnalysisResult)
def revert_to_version(application_number: str, req: RevertRequest):
    try:
        target = load_analysis_version(application_number, req.version)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"버전 {req.version} 없음")
    save_analysis(target)
    return target
