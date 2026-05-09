from __future__ import annotations
import json
from typing import AsyncIterator
from patent_agent.llm.base import LLMClient, Message
from patent_agent.models.analysis import AnalysisResult
from patent_agent.core.prompts import render
from patent_agent.core.chatbot import ChatRequest, ChatResponse
from patent_agent.core.pipeline import STEP_ORDER

_GET_CLAIM_CHART_ROW = {
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
}

_GET_STRATEGY = {
    "name": "get_strategy",
    "description": "공격 또는 방어 전략 전문 반환",
    "input_schema": {
        "type": "object",
        "properties": {
            "strategy_type": {"type": "string", "enum": ["공격", "방어"]},
        },
        "required": ["strategy_type"],
    },
}

_GET_AMENDMENT = {
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
}

_PROPOSE_PATCH = {
    "name": "propose_patch",
    "description": "이 단계 분석 결과의 특정 필드 수정 제안 반환 (저장 안 함)",
    "input_schema": {
        "type": "object",
        "properties": {
            "target_path": {"type": "string"},
            "instruction": {"type": "string"},
            "proposed_value": {"type": "string"},
        },
        "required": ["target_path", "instruction", "proposed_value"],
    },
}


def _make_propose_regenerate(step_name: str) -> dict:
    return {
        "name": "propose_regenerate",
        "description": f"현재 단계({step_name}) 재실행 제안 반환 (저장 안 함)",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "enum": [step_name],
                },
                "hint": {"type": "string"},
            },
            "required": ["tool_name", "hint"],
        },
    }


_STEP_TOOLS: dict[str, list[str]] = {
    "office_action": ["propose_patch", "propose_regenerate"],
    "claim_parse":   ["propose_patch", "propose_regenerate"],
    "spec_mapping":  ["propose_patch", "propose_regenerate"],
    "claim_chart":   ["get_claim_chart_row", "propose_patch", "propose_regenerate"],
    "strategy":      ["get_claim_chart_row", "get_strategy", "propose_patch", "propose_regenerate"],
    "amendment":     ["get_strategy", "get_amendment", "propose_patch", "propose_regenerate"],
}

_TOOL_DEFS = {
    "get_claim_chart_row": _GET_CLAIM_CHART_ROW,
    "get_strategy":        _GET_STRATEGY,
    "get_amendment":       _GET_AMENDMENT,
    "propose_patch":       _PROPOSE_PATCH,
}


def _get_step_tools(step_name: str) -> list[dict]:
    tools = []
    for name in _STEP_TOOLS.get(step_name, []):
        if name == "propose_regenerate":
            tools.append(_make_propose_regenerate(step_name))
        else:
            tools.append(_TOOL_DEFS[name])
    return tools


def _build_step_context(step_name: str, result: AnalysisResult) -> dict:
    base = {"application_number": result.application_number, "step_name": step_name}

    if step_name == "office_action":
        return {
            **base,
            "rejection_reasons": result.office_action.rejection_reasons,
            "rejected_claim_numbers": result.office_action.rejected_claim_numbers,
            "cited_arts": result.office_action.cited_arts,
        }
    if step_name == "claim_parse":
        return {
            **base,
            "claims": result.claim_parse.claims,
            "total_claims": result.claim_parse.total_claims,
            "independent_claims": result.claim_parse.independent_claims,
        }
    if step_name == "spec_mapping":
        return {
            **base,
            "mappings": result.spec_mapping.mappings,
        }
    if step_name == "claim_chart":
        return {
            **base,
            "charts": result.claim_chart.charts,
            "rejection_reasons": result.office_action.rejection_reasons,
        }
    if step_name == "strategy":
        return {
            **base,
            "offensive": result.strategy.offensive,
            "defensive": result.strategy.defensive,
            "charts": result.claim_chart.charts,
        }
    if step_name == "amendment":
        return {
            **base,
            "offensive_draft": result.amendment.offensive_draft,
            "defensive_draft": result.amendment.defensive_draft,
            "spec_mapping": result.spec_mapping,
        }
    return base


def _execute_step_tool(tool_name: str, tool_input: dict, result: AnalysisResult) -> str:
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


def run_step_chatbot(
    request: ChatRequest,
    step_name: str,
    result: AnalysisResult,
    llm: LLMClient,
) -> ChatResponse:
    if step_name not in STEP_ORDER:
        raise ValueError(f"Unknown step: {step_name!r}")

    ctx = _build_step_context(step_name, result)
    system_prompt = render("step_chat_system.j2", **ctx)
    tools = _get_step_tools(step_name)

    messages = [
        Message(role="user", content=system_prompt),
        Message(role="assistant", content="이해했습니다. 질문해 주세요."),
        *request.messages[-10:],
    ]

    proposals: list[dict] = []

    for _ in range(5):
        response = llm.chat(messages, tools=tools)
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
            tool_result = _execute_step_tool(block.name, block.input, result)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": tool_result,
            })
            if block.name == "propose_patch":
                proposals.append({
                    "target_path": block.input["target_path"],
                    "new_value": block.input["proposed_value"],
                    "reason": block.input["instruction"],
                })

        messages.append(Message(role="assistant",
                                content=json.dumps(content, default=str)))
        messages.append(Message(role="user",
                                content=json.dumps(tool_results, default=str)))

    return ChatResponse(
        message=Message(role="assistant", content="응답 생성 중 문제가 발생했습니다."),
        proposals=proposals,
    )


async def stream_step_chatbot(
    request: ChatRequest,
    step_name: str,
    result: AnalysisResult,
    llm: LLMClient,
) -> AsyncIterator[dict]:
    if step_name not in STEP_ORDER:
        raise ValueError(f"Unknown step: {step_name!r}")

    ctx = _build_step_context(step_name, result)
    system_prompt = render("step_chat_system.j2", **ctx)
    tools = _get_step_tools(step_name)

    messages: list[Message] = [
        Message(role="user", content=system_prompt),
        Message(role="assistant", content="이해했습니다. 질문해 주세요."),
        *request.messages[-10:],
    ]

    proposals: list[dict] = []

    for _ in range(5):
        tool_use_events: list[dict] = []
        content_for_history: list = []
        stop_reason = "end_turn"

        async for event in llm.stream_chat(messages, tools=tools):
            if event["type"] == "token":
                yield event

            elif event["type"] == "tool_use":
                tool_use_events.append(event)
                if event["name"] == "propose_patch":
                    proposals.append({
                        "target_path": event["input"]["target_path"],
                        "new_value": event["input"]["proposed_value"],
                        "reason": event["input"]["instruction"],
                    })

            elif event["type"] == "done":
                stop_reason = event["stop_reason"]
                content_for_history = event.get("content_for_history", [])

        if stop_reason != "tool_use":
            break

        messages.append(Message(
            role="assistant",
            content=json.dumps(content_for_history, ensure_ascii=False),
        ))

        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": _execute_step_tool(tu["name"], tu["input"], result),
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
