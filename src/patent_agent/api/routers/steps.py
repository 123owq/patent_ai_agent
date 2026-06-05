from __future__ import annotations
import json
import time
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from patent_agent.api.deps import get_llm_dep
from patent_agent.api.routers.analysis import (
    _progress_store,
    _adapt_patent,
    _adapt_prior_art,
)
from patent_agent.core.pipeline import run_from_step, STEP_ORDER
from patent_agent.core.step_chatbot import run_step_chatbot, stream_step_chatbot
from patent_agent.core.chatbot import ChatRequest, ChatResponse
from patent_agent.core.storage import (
    load_analysis,
    load_input_patent,
    load_input_office_action,
    load_input_prior_arts,
    model_name_to_id,
    normalize_model_id,
)
from patent_agent.models.input import OfficeActionRaw
from patent_agent.llm.base import LLMClient

router = APIRouter(prefix="/api/v1/analysis", tags=["steps"])

_STEP_FIELD_MAP = {
    "office_action":    lambda r: r.office_action,
    "claim_parse":      lambda r: r.claim_parse,
    "spec_mapping":     lambda r: r.spec_mapping,
    "claim_chart":      lambda r: r.claim_chart,
    "claim_conclusion": lambda r: r.claim_conclusion,
    "strategy":         lambda r: r.strategy,
    "amendment":        lambda r: r.amendment,
}


def _validate_step(step_name: str) -> None:
    if step_name not in STEP_ORDER:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 단계명: '{step_name}'. 가능한 값: {STEP_ORDER}",
        )


class RegenResponse(BaseModel):
    regen_id: str
    application_number: str
    step_name: str
    status: str = "started"


@router.get("/{application_number}/steps/{step_name}")
def get_step_result(
    application_number: str,
    step_name: str,
    model_id: str | None = Query(default=None),
):
    _validate_step(step_name)
    try:
        result = load_analysis(application_number, model_id=model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")

    step_obj = _STEP_FIELD_MAP[step_name](result)
    if step_obj is None:
        raise HTTPException(status_code=404, detail=f"'{step_name}' 결과 없음 (아직 생성되지 않음)")
    return JSONResponse(content=json.loads(step_obj.model_dump_json()))


@router.post("/{application_number}/steps/{step_name}/regenerate",
             response_model=RegenResponse)
async def regenerate_from_step(
    application_number: str,
    step_name: str,
    background_tasks: BackgroundTasks,
    model_id: str | None = Query(default=None),
    llm: LLMClient = Depends(get_llm_dep),
):
    _validate_step(step_name)
    try:
        requested_model_id = normalize_model_id(model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    current_model_id = model_name_to_id(getattr(llm, "model", ""))
    if requested_model_id and requested_model_id != current_model_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Requested model_id '{requested_model_id}' cannot be regenerated while "
                f"this server is configured for '{current_model_id}'."
            ),
        )
    try:
        existing = load_analysis(application_number, model_id=model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")

    regen_id = f"{int(time.time())}-{application_number}"
    _progress_store[regen_id] = []

    def _run():
        try:
            patent_raw = load_input_patent(application_number)
            oa_raw = load_input_office_action(application_number)
            prior_arts_raw = load_input_prior_arts(application_number)

            patent = _adapt_patent(application_number, patent_raw)
            oa = OfficeActionRaw(application_number=application_number, raw_dict=oa_raw)
            prior_arts = [_adapt_prior_art(i, raw) for i, raw in enumerate(prior_arts_raw)]

            def progress_cb(step: str, ratio: float) -> None:
                _progress_store[regen_id].append(
                    {"step": step, "ratio": ratio, "done": ratio >= 1.0}
                )

            run_from_step(step_name, existing, patent, oa, prior_arts, llm, progress_cb,
                          llm_model=getattr(llm, "model", ""))
        except Exception as e:
            _progress_store[regen_id].append(
                {"step": "오류", "ratio": 1.0, "done": True, "error": str(e)}
            )

    background_tasks.add_task(_run)
    return RegenResponse(
        regen_id=regen_id,
        application_number=application_number,
        step_name=step_name,
    )


@router.post("/{application_number}/steps/{step_name}/chat",
             response_model=ChatResponse)
def step_chat(
    application_number: str,
    step_name: str,
    req: ChatRequest,
    model_id: str | None = Query(default=None),
    llm: LLMClient = Depends(get_llm_dep),
):
    _validate_step(step_name)
    try:
        result = load_analysis(application_number, model_id=model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")

    return run_step_chatbot(req, step_name, result, llm)


@router.post("/{application_number}/steps/{step_name}/chat/stream")
async def step_chat_stream(
    application_number: str,
    step_name: str,
    req: ChatRequest,
    model_id: str | None = Query(default=None),
    llm: LLMClient = Depends(get_llm_dep),
):
    _validate_step(step_name)
    try:
        result = load_analysis(application_number, model_id=model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")

    async def event_generator():
        async for event in stream_step_chatbot(req, step_name, result, llm):
            yield {"data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(event_generator())
