from fastapi import APIRouter, Depends, HTTPException
from patent_agent.api.deps import get_llm_dep
from patent_agent.core.chatbot import ChatRequest, ChatResponse, run_chatbot
from patent_agent.core.storage import load_analysis
from patent_agent.llm.base import LLMClient

router = APIRouter(prefix="/api/v1/analysis", tags=["chat"])


@router.post("/{application_number}/chat", response_model=ChatResponse)
def chat(
    application_number: str,
    req: ChatRequest,
    llm: LLMClient = Depends(get_llm_dep),
):
    try:
        analysis = load_analysis(application_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")
    return run_chatbot(req, analysis, llm)
