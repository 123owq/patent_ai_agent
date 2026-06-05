from __future__ import annotations
import os
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from patent_agent.core.editing import (
    InvalidEditValue,
    InvalidTargetPath,
    find_edit_candidates,
    get_nested,
    preview_edit as build_edit_preview,
    set_nested,
)
from patent_agent.core.storage import load_analysis, load_analysis_version, save_analysis
from patent_agent.models.analysis import AnalysisResult, EditLogEntry

router = APIRouter(prefix="/api/v1/analysis", tags=["edits"])


class ApplyEditRequest(BaseModel):
    target_path: str
    new_value: str
    user_instruction: str | None = None


class PreviewEditRequest(BaseModel):
    target_path: str
    new_value: str


class EditCandidateResponse(BaseModel):
    target_path: str
    current_value: object
    value_type: str
    preview: str


class ListEditCandidatesResponse(BaseModel):
    candidates: list[EditCandidateResponse]


class PreviewEditResponse(BaseModel):
    target_path: str
    current_value: object
    proposed_value: object
    normalized_value: object
    value_type: str
    next_version: int


class RevertRequest(BaseModel):
    version: int


def _append_edit_log(application_number: str, entry: EditLogEntry, model_id: str | None) -> None:
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    parts = [data_dir, Path("analysis"), Path(application_number)]
    if model_id:
        parts.append(Path(model_id))
    log_path = Path(*parts) / "edits.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(entry.model_dump_json() + "\n")


def _load_analysis_or_http(application_number: str, model_id: str | None) -> AnalysisResult:
    try:
        return load_analysis(application_number, model_id=model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")


@router.get("/{application_number}/edits/candidates", response_model=ListEditCandidatesResponse)
def list_edit_candidates(
    application_number: str,
    query: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=100),
    model_id: str | None = Query(default=None),
):
    result = _load_analysis_or_http(application_number, model_id)
    return ListEditCandidatesResponse(candidates=[
        EditCandidateResponse(
            target_path=c.target_path,
            current_value=c.current_value,
            value_type=c.value_type,
            preview=c.preview,
        )
        for c in find_edit_candidates(result, query=query, limit=limit)
    ])


@router.post("/{application_number}/edits/preview", response_model=PreviewEditResponse)
def preview_edit(
    application_number: str,
    req: PreviewEditRequest,
    model_id: str | None = Query(default=None),
):
    result = _load_analysis_or_http(application_number, model_id)
    try:
        preview = build_edit_preview(result, req.target_path, req.new_value)
    except InvalidTargetPath as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidEditValue as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PreviewEditResponse(
        target_path=preview.target_path,
        current_value=preview.current_value,
        proposed_value=preview.proposed_value,
        normalized_value=preview.normalized_value,
        value_type=preview.value_type,
        next_version=preview.next_version,
    )


@router.post("/{application_number}/edits/apply", response_model=AnalysisResult)
def apply_edit(
    application_number: str,
    req: ApplyEditRequest,
    model_id: str | None = Query(default=None),
):
    result = _load_analysis_or_http(application_number, model_id)

    try:
        preview = build_edit_preview(result, req.target_path, req.new_value)
    except InvalidTargetPath as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidEditValue as e:
        raise HTTPException(status_code=400, detail=str(e))

    result_dict = result.model_dump(mode="json")
    updated_dict = set_nested(result_dict, req.target_path, req.new_value)
    updated_dict["version"] = result.version + 1
    updated_result = AnalysisResult.model_validate(updated_dict)

    save_analysis(updated_result, model_id=model_id)

    _append_edit_log(application_number, EditLogEntry(
        target_path=req.target_path,
        before=str(preview.current_value),
        after=req.new_value,
        source="llm-proposed-user-applied",
        user_instruction=req.user_instruction,
    ), model_id)
    return updated_result


@router.post("/{application_number}/edits/revert", response_model=AnalysisResult)
def revert_to_version(
    application_number: str,
    req: RevertRequest,
    model_id: str | None = Query(default=None),
):
    try:
        target = load_analysis_version(application_number, req.version, model_id=model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"버전 {req.version} 없음")
    save_analysis(target, model_id=model_id)
    return target
