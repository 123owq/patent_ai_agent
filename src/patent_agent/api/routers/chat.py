import json
from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse
from patent_agent.api.deps import get_llm_dep
from patent_agent.core.chatbot import ChatRequest, ChatResponse, run_chatbot, stream_chatbot
from patent_agent.core.storage import load_analysis
from patent_agent.llm.base import LLMClient

router = APIRouter(prefix="/api/v1/analysis", tags=["chat"])


@router.post("/{application_number}/chat", response_model=ChatResponse)
def chat(
    application_number: str,
    req: ChatRequest,
    llm: LLMClient = Depends(get_llm_dep),
):
    """비스트리밍 챗봇 (하위 호환)"""
    try:
        analysis = load_analysis(application_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")
    return run_chatbot(req, analysis, llm)


@router.post("/{application_number}/chat/stream")
async def chat_stream(
    application_number: str,
    req: ChatRequest,
    llm: LLMClient = Depends(get_llm_dep),
):
    """스트리밍 챗봇 — SSE로 토큰 실시간 전송

    SSE 이벤트 형식:
      data: {"type": "token", "content": "..."}   ← 텍스트 토큰
      data: {"type": "proposals", "data": [...]}   ← 수정 제안 (있을 때만)
      data: {"type": "done"}                       ← 종료
    """
    try:
        analysis = load_analysis(application_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")

    async def event_generator():
        async for event in stream_chatbot(req, analysis, llm):
            yield {"data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(event_generator())
