from __future__ import annotations
import json
from typing import AsyncIterator
from pydantic import BaseModel
from patent_agent.llm.base import LLMClient, Message
from patent_agent.models.analysis import AnalysisResult
from patent_agent.core.prompts import render

CHATBOT_TOOLS = [
    {
        "name": "get_claim_chart_row",
        "description": "Claim Chart의 특정 행 반환 (우리 판단 + 심사관 판단 + 일치 여부)",
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string"},
                "prior_art_id": {"type": "string"},
            },
            "required": ["element_id", "prior_art_id"],
        },
    },
    {
        "name": "get_strategy",
        "description": "공격 또는 방어 전략 전문 반환",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy_type": {"type": "string", "enum": ["공격", "방어"]},
            },
            "required": ["strategy_type"],
        },
    },
    {
        "name": "get_amendment",
        "description": "특정 청구항 보정안 반환",
        "input_schema": {
            "type": "object",
            "properties": {
                "claim_number": {"type": "integer"},
                "strategy_type": {"type": "string", "enum": ["공격", "방어"]},
            },
            "required": ["claim_number", "strategy_type"],
        },
    },
    {
        "name": "propose_patch",
        "description": "분석 결과 특정 필드 수정 제안 반환 (저장 안 함)",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_path": {"type": "string"},
                "instruction": {"type": "string"},
                "proposed_value": {"type": "string"},
            },
            "required": ["target_path", "instruction", "proposed_value"],
        },
    },
    {
        "name": "propose_regenerate",
        "description": "특정 Tool 재실행 제안 반환 (저장 안 함)",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "enum": ["claim_chart", "strategy", "amendment"],
                },
                "hint": {"type": "string"},
            },
            "required": ["tool_name", "hint"],
        },
    },
]


def _execute_tool(tool_name: str, tool_input: dict, result: AnalysisResult) -> str:
    if tool_name == "get_claim_chart_row":
        element_id = tool_input["element_id"]
        prior_art_id = tool_input["prior_art_id"]
        for chart in result.claim_chart.charts:
            for row in chart.rows:
                if row.element_id == element_id and row.prior_art_id == prior_art_id:
                    return row.model_dump_json(indent=2, ensure_ascii=False)
        return "해당 행을 찾을 수 없습니다."

    if tool_name == "get_strategy":
        strategy_type = tool_input["strategy_type"]
        s = (result.strategy.offensive if strategy_type == "공격"
             else result.strategy.defensive)
        return s.model_dump_json(indent=2, ensure_ascii=False)

    if tool_name == "get_amendment":
        claim_number = tool_input["claim_number"]
        strategy_type = tool_input["strategy_type"]
        draft = (result.amendment.offensive_draft if strategy_type == "공격"
                 else result.amendment.defensive_draft)
        for ac in draft.amended_claims:
            if ac.claim_number == claim_number:
                return ac.model_dump_json(indent=2, ensure_ascii=False)
        return "해당 보정안을 찾을 수 없습니다."

    if tool_name in ("propose_patch", "propose_regenerate"):
        return json.dumps(
            {"proposal": tool_input, "status": "pending_user_approval"},
            ensure_ascii=False,
        )

    return f"알 수 없는 tool: {tool_name}"


class ChatRequest(BaseModel):
    messages: list[Message]
    active_strategy: str = "공격"


class ChatResponse(BaseModel):
    message: Message
    proposals: list[dict] = []


def run_chatbot(
    request: ChatRequest,
    analysis: AnalysisResult,
    llm: LLMClient,
) -> ChatResponse:
    system_prompt = render(
        "chatbot_system.j2",
        application_number=analysis.application_number,
        active_strategy_type=request.active_strategy,
        rejection_reasons=analysis.office_action.rejection_reasons,
        claim_charts=analysis.claim_chart.charts,
        current_strategy=(
            analysis.strategy.offensive
            if request.active_strategy == "공격"
            else analysis.strategy.defensive
        ),
        current_amendment=(
            analysis.amendment.offensive_draft
            if request.active_strategy == "공격"
            else analysis.amendment.defensive_draft
        ),
    )

    messages = [
        Message(role="user", content=system_prompt),
        Message(role="assistant", content="이해했습니다. 질문해 주세요."),
        *request.messages[-10:],
    ]

    proposals: list[dict] = []
    max_turns = 5

    for _ in range(max_turns):
        response = llm.chat(messages, tools=CHATBOT_TOOLS)
        content = response["content"]
        stop_reason = response["stop_reason"]

        if stop_reason != "tool_use":
            text = ""
            if isinstance(content, list):
                text = next(
                    (b.text for b in content if hasattr(b, "text")),
                    str(content),
                )
            else:
                text = str(content)
            return ChatResponse(
                message=Message(role="assistant", content=text),
                proposals=proposals,
            )

        tool_results = []
        for block in (content if isinstance(content, list) else []):
            if not hasattr(block, "type") or block.type != "tool_use":
                continue
            tool_result = _execute_tool(block.name, block.input, analysis)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": tool_result,
            })
            if block.name.startswith("propose_"):
                proposals.append({"tool": block.name, "input": block.input})

        messages.append(Message(role="assistant",
                                content=json.dumps(content, default=str)))
        messages.append(Message(role="user",
                                content=json.dumps(tool_results, default=str)))

    return ChatResponse(
        message=Message(role="assistant", content="응답 생성 중 문제가 발생했습니다."),
        proposals=proposals,
    )


async def stream_chatbot(
    request: ChatRequest,
    analysis: AnalysisResult,
    llm: LLMClient,
) -> AsyncIterator[dict]:
    system_prompt = render(
        "chatbot_system.j2",
        application_number=analysis.application_number,
        active_strategy_type=request.active_strategy,
        rejection_reasons=analysis.office_action.rejection_reasons,
        claim_charts=analysis.claim_chart.charts,
        current_strategy=(
            analysis.strategy.offensive
            if request.active_strategy == "공격"
            else analysis.strategy.defensive
        ),
        current_amendment=(
            analysis.amendment.offensive_draft
            if request.active_strategy == "공격"
            else analysis.amendment.defensive_draft
        ),
    )

    messages: list[Message] = [
        Message(role="user", content=system_prompt),
        Message(role="assistant", content="이해했습니다. 질문해 주세요."),
        *request.messages[-10:],
    ]

    proposals: list[dict] = []

    for _ in range(5):  # max_turns
        tool_use_events: list[dict] = []
        content_for_history: list = []
        stop_reason = "end_turn"

        async for event in llm.stream_chat(messages, tools=CHATBOT_TOOLS):
            if event["type"] == "token":
                yield event  # 토큰 즉시 SSE로 전송

            elif event["type"] == "tool_use":
                tool_use_events.append(event)
                if event["name"].startswith("propose_"):
                    proposals.append({"tool": event["name"], "input": event["input"]})

            elif event["type"] == "done":
                stop_reason = event["stop_reason"]
                content_for_history = event.get("content_for_history", [])

        if stop_reason != "tool_use":
            break

        # tool_use 처리: 어시스턴트 메시지 + 툴 결과 추가
        messages.append(Message(
            role="assistant",
            content=json.dumps(content_for_history, ensure_ascii=False),
        ))

        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": _execute_tool(tu["name"], tu["input"], analysis),
            }
            for tu in tool_use_events
        ]
        messages.append(Message(
            role="user",
            content=json.dumps(tool_results, ensure_ascii=False),
        ))

    if proposals:
        yield {"type": "proposals", "data": proposals}
    yield {"type": "done"}
