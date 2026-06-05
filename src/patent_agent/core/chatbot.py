from __future__ import annotations
import json
from typing import AsyncIterator, Literal
from pydantic import BaseModel
from patent_agent.core.editing import find_edit_candidates
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
        "name": "find_editable_paths",
        "description": "사용자 수정 요청과 관련된 분석 결과 필드 후보 경로를 검색합니다. propose_patch 전에 먼저 호출하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
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
                    "enum": ["strategy", "amendment"],
                },
                "hint": {"type": "string"},
            },
            "required": ["tool_name", "hint"],
        },
    },
]

_RERUN_INTENT_KEYWORDS = (
    "재생성",
    "재작성",
    "수정",
    "고쳐",
    "바꿔",
    "짜줘",
    "작성해",
    "만들어",
    "보강",
    "한정",
)
_STRATEGY_KEYWORDS = ("전략", "공격", "방어")
_AMENDMENT_KEYWORDS = ("보정", "청구항", "클레임", "claim")


class RegenerationPlanDraft(BaseModel):
    tool_name: Literal["strategy", "amendment"]
    plan_summary: str
    rationale: list[str]
    constraints: list[str]
    hint: str
    original_request: str | None = None


def _latest_user_text(request: ChatRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content.strip()
    return ""


def _deterministic_regenerate_proposal(request: ChatRequest) -> dict | None:
    text = _latest_user_text(request)
    lowered = text.lower()
    if not text or not any(keyword in lowered for keyword in _RERUN_INTENT_KEYWORDS):
        return None

    if any(keyword in lowered for keyword in _STRATEGY_KEYWORDS):
        tool_name = "strategy"
        plan_summary = "방어 전략 중심으로 전략을 재정리하고, 새 전략에 맞춰 보정안도 함께 재생성합니다."
        rationale = [
            "전략 변경은 후속 보정안 문구와 함께 정합성을 맞춰야 합니다.",
            "현재 분석 결과의 Claim Chart 불일치 포인트를 재활용합니다.",
        ]
        scope = "Tool 5(전략) → Tool 6(보정안)"
        title = "전략과 보정안 재생성 계획 초안"
    elif any(keyword in lowered for keyword in _AMENDMENT_KEYWORDS):
        tool_name = "amendment"
        plan_summary = "현재 전략은 유지하고, 사용자 요청을 반영해 보정안만 더 구체적으로 재생성합니다."
        rationale = [
            "보정안 문구는 명세서 근거와 청구항 차이점을 함께 맞춰야 합니다.",
            "전략을 바꾸지 않고 Tool 6만 다시 실행하면 변경 범위를 줄일 수 있습니다.",
        ]
        scope = "Tool 6(보정안)"
        title = "보정안 재생성 계획 초안"
    else:
        return None

    constraints = [
        "명세서 근거가 있는 표현만 사용",
        "신규사항 추가 위험을 피함",
        "사용자 요청 원문을 우선 반영",
    ]
    hint = (
        f"{plan_summary}\n"
        f"제약: {'; '.join(constraints)}\n"
        f"사용자 원문: '{text}'"
    )
    message = (
        f"{title}을 만들었습니다.\n\n"
        f"- 요청: {text}\n"
        f"- 방향: {plan_summary}\n"
        f"- 실행 범위: {scope}\n\n"
        "아래 계획을 확인한 뒤 실행하거나, 방향 수정 의견을 남겨 주세요."
    )

    return {
        "tool": "propose_regenerate",
        "message": message,
        "input": {
            "tool_name": tool_name,
            "hint": hint,
            "original_request": text,
            "plan_summary": plan_summary,
            "rationale": rationale,
            "constraints": constraints,
        },
    }


def _proposal_payload(proposal: dict) -> dict:
    return {key: value for key, value in proposal.items() if key != "message"}


def _regenerate_scope(tool_name: str) -> str:
    if tool_name == "strategy":
        return "Tool 5(전략) → Tool 6(보정안)"
    return "Tool 6(보정안)"


def _regenerate_title(tool_name: str) -> str:
    if tool_name == "strategy":
        return "전략과 보정안 재생성 계획 초안"
    return "보정안 재생성 계획 초안"


def _regenerate_message(input_payload: dict) -> str:
    return (
        f"{_regenerate_title(input_payload['tool_name'])}을 만들었습니다.\n\n"
        f"- 요청: {input_payload['original_request']}\n"
        f"- 방향: {input_payload['plan_summary']}\n"
        f"- 실행 범위: {_regenerate_scope(input_payload['tool_name'])}\n\n"
        "아래 계획을 확인한 뒤 실행하거나, 방향 수정 의견을 남겨 주세요."
    )


def _build_regenerate_proposal(input_payload: dict) -> dict:
    return {
        "tool": "propose_regenerate",
        "message": _regenerate_message(input_payload),
        "input": input_payload,
    }


def _analysis_context_for_regenerate(analysis: AnalysisResult, active_strategy: str) -> dict:
    strategy = (
        analysis.strategy.offensive
        if active_strategy == "공격"
        else analysis.strategy.defensive
    )
    amendment = (
        analysis.amendment.offensive_draft
        if active_strategy == "공격"
        else analysis.amendment.defensive_draft
    )
    return {
        "application_number": analysis.application_number,
        "active_strategy": active_strategy,
        "rejection_reasons": [
            {
                "type": reason.rejection_type,
                "article": reason.article,
                "claims": reason.target_claim_numbers,
                "reasoning": reason.examiner_reasoning[:500],
            }
            for reason in analysis.office_action.rejection_reasons[:3]
        ],
        "claim_chart_disagreements": [
            {
                "claim": chart.target_claim_number,
                "element_id": row.element_id,
                "our_match": row.our_match,
                "examiner_match": row.examiner_match,
                "rationale": row.disagreement_rationale,
            }
            for chart in analysis.claim_chart.charts[:3]
            for row in chart.rows
            if row.agreement == "불일치"
        ][:8],
        "current_strategy": {
            "rationale": strategy.rationale,
            "proposed_action": strategy.proposed_action,
            "leveraged_differences": strategy.leveraged_differences[:5],
        },
        "current_amendment": [
            {
                "claim_number": claim.claim_number,
                "diff_summary": claim.diff_summary,
            }
            for claim in amendment.amended_claims[:8]
        ],
    }


def _llm_regenerate_proposal(
    request: ChatRequest,
    analysis: AnalysisResult,
    llm: LLMClient,
    fallback_proposal: dict,
) -> dict:
    latest_text = _latest_user_text(request)
    fallback_input = fallback_proposal["input"]
    prompt = (
        "당신은 특허 거절이유 대응 분석 결과를 바탕으로 재생성 실행 전 계획 초안을 작성하는 AI입니다.\n"
        "사용자는 아직 실행을 승인하지 않았습니다. 카드의 빈칸에 들어갈 내용을 JSON 스키마에 맞춰 작성하세요.\n\n"
        "반드시 지킬 것:\n"
        "- tool_name은 strategy 또는 amendment 중 하나만 선택합니다.\n"
        "- 전략 자체를 다시 짜야 하면 strategy를 선택합니다. 이 경우 Tool 5 이후 Tool 6도 같이 실행됩니다.\n"
        "- 보정청구항 문구만 다듬으면 충분하면 amendment를 선택합니다.\n"
        "- plan_summary는 사용자가 승인 여부를 판단할 수 있게 구체적으로 씁니다.\n"
        "- rationale은 왜 그 방향이 맞는지 2~4개 bullet로 씁니다.\n"
        "- constraints는 신규사항, 권리범위, 명세서 근거 등 실행 시 지킬 조건 2~4개로 씁니다.\n"
        "- hint는 실제 재생성 API에 넘길 실행 지시문이므로 구체적이고 간결하게 씁니다.\n"
        "- 최근 메시지가 기존 계획을 수정하는 요청이면 original_request에는 최초 수정 대상 요청만 깨끗하게 적습니다.\n\n"
        f"최근 사용자 메시지:\n{latest_text}\n\n"
        f"기본 fallback 판단:\n{json.dumps(fallback_input, ensure_ascii=False)}\n\n"
        f"최근 대화:\n{json.dumps([m.model_dump() for m in request.messages[-6:]], ensure_ascii=False)}\n\n"
        f"현재 분석 요약:\n{json.dumps(_analysis_context_for_regenerate(analysis, request.active_strategy), ensure_ascii=False)}"
    )
    draft = llm.generate(
        prompt,
        schema=RegenerationPlanDraft,
        temperature=0.2,
        max_tokens=2000,
    )
    original_request = (draft.original_request or "").strip() or fallback_input["original_request"]
    input_payload = {
        "tool_name": draft.tool_name,
        "hint": draft.hint.strip() or fallback_input["hint"],
        "original_request": original_request,
        "plan_summary": draft.plan_summary.strip() or fallback_input["plan_summary"],
        "rationale": [item.strip() for item in draft.rationale if item.strip()]
        or fallback_input["rationale"],
        "constraints": [item.strip() for item in draft.constraints if item.strip()]
        or fallback_input["constraints"],
    }
    return _build_regenerate_proposal(input_payload)


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

    if tool_name == "find_editable_paths":
        candidates = find_edit_candidates(
            result,
            query=str(tool_input.get("query", "")),
            limit=int(tool_input.get("limit", 10)),
        )
        return json.dumps(
            [
                {
                    "target_path": c.target_path,
                    "current_value": c.current_value,
                    "value_type": c.value_type,
                    "preview": c.preview,
                }
                for c in candidates
            ],
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
    deterministic_proposal = _deterministic_regenerate_proposal(request)
    if deterministic_proposal:
        try:
            deterministic_proposal = _llm_regenerate_proposal(
                request,
                analysis,
                llm,
                deterministic_proposal,
            )
        except Exception:
            pass
        return ChatResponse(
            message=Message(role="assistant", content=deterministic_proposal["message"]),
            proposals=[_proposal_payload(deterministic_proposal)],
        )

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
            if block.name in ("propose_patch", "propose_regenerate"):
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
    deterministic_proposal = _deterministic_regenerate_proposal(request)
    if deterministic_proposal:
        try:
            deterministic_proposal = _llm_regenerate_proposal(
                request,
                analysis,
                llm,
                deterministic_proposal,
            )
        except Exception:
            pass
        yield {"type": "token", "content": deterministic_proposal["message"]}
        yield {"type": "proposals", "data": [_proposal_payload(deterministic_proposal)]}
        yield {"type": "done"}
        return

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
                if event["name"] in ("propose_patch", "propose_regenerate"):
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
