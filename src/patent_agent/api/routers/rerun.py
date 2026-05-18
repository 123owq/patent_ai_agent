from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from patent_agent.api.deps import get_llm_dep
from patent_agent.api.routers.analysis import _adapt_patent, _adapt_prior_art
from patent_agent.core.storage import (
    load_analysis,
    load_input_patent,
    load_input_office_action,
    load_input_prior_arts,
    save_analysis,
)
from patent_agent.models.analysis import AnalysisResult
from patent_agent.models.input import OfficeActionRaw
from patent_agent.llm.base import LLMClient
from patent_agent.tools.tool5_strategy import analyze_diff_and_strategy
from patent_agent.tools.tool6_amendment import generate_amendments

router = APIRouter(prefix="/api/v1/analysis", tags=["rerun"])


class RerunRequest(BaseModel):
    user_instruction: str


def _load_inputs(application_number: str):
    try:
        patent_raw = load_input_patent(application_number)
        oa_raw = load_input_office_action(application_number)
        prior_arts_raw = load_input_prior_arts(application_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="원본 특허 파일 없음")

    patent = _adapt_patent(application_number, patent_raw)
    oa = OfficeActionRaw(application_number=application_number, raw_dict=oa_raw)
    prior_arts = [_adapt_prior_art(i, raw) for i, raw in enumerate(prior_arts_raw)]
    return patent, oa, prior_arts


@router.post("/{application_number}/rerun-strategy", response_model=AnalysisResult)
def rerun_strategy(
    application_number: str,
    req: RerunRequest,
    llm: LLMClient = Depends(get_llm_dep),
):
    try:
        existing = load_analysis(application_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")

    patent, _, _ = _load_inputs(application_number)

    new_strategy = analyze_diff_and_strategy(
        claim_chart=existing.claim_chart,
        office_action=existing.office_action,
        spec_mapping=existing.spec_mapping,
        llm=llm,
        user_instruction=req.user_instruction,
    )
    new_amendment = generate_amendments(
        strategy=new_strategy,
        claims=existing.claim_parse,
        spec_mapping=existing.spec_mapping,
        llm=llm,
        spec_paragraphs=patent.spec_paragraphs,
        user_instruction=req.user_instruction,
    )

    updated = AnalysisResult(
        analysis_id=existing.analysis_id,
        application_number=existing.application_number,
        created_at=existing.created_at,
        version=existing.version + 1,
        source_files=existing.source_files,
        errors=existing.errors,
        office_action=existing.office_action,
        claim_parse=existing.claim_parse,
        spec_mapping=existing.spec_mapping,
        claim_chart=existing.claim_chart,
        strategy=new_strategy,
        amendment=new_amendment,
    )
    save_analysis(updated)
    return updated


@router.post("/{application_number}/rerun-amendment", response_model=AnalysisResult)
def rerun_amendment(
    application_number: str,
    req: RerunRequest,
    llm: LLMClient = Depends(get_llm_dep),
):
    try:
        existing = load_analysis(application_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")

    patent, _, _ = _load_inputs(application_number)

    new_amendment = generate_amendments(
        strategy=existing.strategy,
        claims=existing.claim_parse,
        spec_mapping=existing.spec_mapping,
        llm=llm,
        spec_paragraphs=patent.spec_paragraphs,
        user_instruction=req.user_instruction,
    )

    updated = AnalysisResult(
        analysis_id=existing.analysis_id,
        application_number=existing.application_number,
        created_at=existing.created_at,
        version=existing.version + 1,
        source_files=existing.source_files,
        errors=existing.errors,
        office_action=existing.office_action,
        claim_parse=existing.claim_parse,
        spec_mapping=existing.spec_mapping,
        claim_chart=existing.claim_chart,
        strategy=existing.strategy,
        amendment=new_amendment,
    )
    save_analysis(updated)
    return updated
