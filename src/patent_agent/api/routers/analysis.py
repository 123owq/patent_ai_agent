from __future__ import annotations
import time
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from patent_agent.api.deps import get_llm_dep
from patent_agent.llm.base import LLMClient
from patent_agent.core.pipeline import run_analysis
from patent_agent.core.storage import (
    load_analysis,
    load_input_office_action,
    load_input_patent,
    load_input_prior_arts,
)
from patent_agent.models.analysis import AnalysisResult
from patent_agent.models.input import OfficeActionRaw, PatentDoc, PriorArtDoc

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])

# 진행 상황 임시 저장 (프로세스 내 메모리)
_progress_store: dict[str, list[dict]] = {}


class StartAnalysisRequest(BaseModel):
    application_number: str


class StartAnalysisResponse(BaseModel):
    analysis_id: str
    application_number: str
    status: str = "started"


@router.post("", response_model=StartAnalysisResponse)
async def start_analysis(
    req: StartAnalysisRequest,
    background_tasks: BackgroundTasks,
    llm: LLMClient = Depends(get_llm_dep),
):
    application_number = req.application_number
    analysis_id = f"{int(time.time())}-{application_number}"
    _progress_store[analysis_id] = []

    def _run():
        try:
            patent_raw = load_input_patent(application_number)
            oa_raw = load_input_office_action(application_number)
            prior_arts_raw = load_input_prior_arts(application_number)

            patent = _adapt_patent(application_number, patent_raw)
            oa = OfficeActionRaw(application_number=application_number, raw_dict=oa_raw)
            prior_arts = [_adapt_prior_art(i, raw) for i, raw in enumerate(prior_arts_raw)]

            def progress_cb(step: str, ratio: float) -> None:
                _progress_store[analysis_id].append(
                    {"step": step, "ratio": ratio, "done": ratio >= 1.0}
                )

            run_analysis(patent, oa, prior_arts, llm, progress_cb)
        except Exception as e:
            _progress_store[analysis_id].append(
                {"step": "오류", "ratio": 1.0, "done": True, "error": str(e)}
            )

    background_tasks.add_task(_run)
    return StartAnalysisResponse(
        analysis_id=analysis_id,
        application_number=application_number,
    )


@router.get("/{application_number}", response_model=AnalysisResult)
def get_analysis(application_number: str):
    try:
        return load_analysis(application_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")


def _adapt_patent(application_number: str, raw: dict) -> PatentDoc:
    claims_raw = raw.get("특허청구범위", {})
    claims = {int(k.replace("청구항", "")): v for k, v in claims_raw.items()}
    spec_paragraphs: dict[str, str] = {}
    for section in raw.get("명세서", {}).values():
        if isinstance(section, list):
            for p in section:
                if isinstance(p, dict) and "단락번호" in p:
                    spec_paragraphs[p["단락번호"]] = p["내용"]
    return PatentDoc(
        application_number=application_number,
        title=raw.get("발명의명칭", ""),
        abstract=raw.get("요약", ""),
        claims=claims,
        spec_paragraphs=spec_paragraphs,
    )


def _adapt_prior_art(index: int, raw: dict) -> PriorArtDoc:
    claims_raw = raw.get("특허청구범위", {})
    claims = {int(k.replace("청구항", "")): v for k, v in claims_raw.items()}
    spec_paragraphs: dict[str, str] = {}
    for section in raw.get("명세서", {}).values():
        if isinstance(section, list):
            for p in section:
                if isinstance(p, dict) and "단락번호" in p:
                    spec_paragraphs[p["단락번호"]] = p["내용"]
    return PriorArtDoc(
        application_number=raw.get("특허정보", {}).get("출원번호", f"prior-{index}"),
        title=raw.get("발명의명칭", ""),
        abstract=raw.get("요약", ""),
        claims=claims,
        spec_paragraphs=spec_paragraphs,
        prior_art_id=f"인용발명{index + 1}",
        publication_number=raw.get("특허정보", {}).get("공개번호", ""),
    )
