import pytest

from patent_agent.core.chatbot import ChatRequest, _execute_tool, run_chatbot, stream_chatbot
from patent_agent.llm.base import Message
from tests.unit.factories import make_analysis_result


class DraftPlanLLM:
    def __init__(self):
        self.generate_prompts: list[str] = []

    def generate(self, prompt, schema, temperature=0.0, max_tokens=16384):
        self.generate_prompts.append(prompt)
        return schema(
            tool_name="amendment",
            plan_summary="보정안은 유지 가능한 권리범위를 남기면서 진보성 반박 포인트를 더 선명하게 보강합니다.",
            rationale=[
                "사용자 요청이 보정청구항 강화에 집중되어 있어 Tool 6만 재생성하면 충분합니다.",
                "기존 전략의 핵심 논리는 유지하되 차이점 표현을 더 구체화합니다.",
            ],
            constraints=[
                "명세서에 직접 또는 암시적으로 뒷받침되는 표현만 사용합니다.",
                "권리범위를 불필요하게 좁히는 수치 한정은 피합니다.",
            ],
            hint="진보성 반박 중심으로 보정안을 보강하되 권리범위 축소를 최소화",
        )

    def chat(self, messages, tools=None):
        raise AssertionError("chat should not be called for LLM-backed rerun plans")

    async def stream_chat(self, messages, tools=None):
        raise AssertionError("stream_chat should not be called for LLM-backed rerun plans")
        yield


class FallbackLLM:
    def generate(self, prompt, schema, temperature=0.0, max_tokens=16384):
        raise RuntimeError("planner unavailable")

    def chat(self, messages, tools=None):
        raise AssertionError("chat should not be called for fallback rerun plans")

    async def stream_chat(self, messages, tools=None):
        raise AssertionError("stream_chat should not be called for fallback rerun plans")
        yield


class TextLLM:
    def generate(self, prompt, schema, temperature=0.0, max_tokens=16384):
        raise AssertionError("generate should not be called for explanation requests")

    def chat(self, messages, tools=None):
        class TextBlock:
            text = "설명 응답"

        return {"content": [TextBlock()], "stop_reason": "end_turn"}


def test_run_chatbot_uses_llm_generated_rerun_plan_content():
    result = make_analysis_result()
    request = ChatRequest(
        active_strategy="방어",
        messages=[Message(role="user", content="보정청구항을 더 강하게 보강해줘")],
    )
    llm = DraftPlanLLM()

    response = run_chatbot(request, result, llm)

    assert llm.generate_prompts
    assert "보정청구항을 더 강하게 보강해줘" in llm.generate_prompts[0]
    assert response.message.role == "assistant"
    assert "보정안은 유지 가능한 권리범위를 남기면서" in response.message.content
    proposal = response.proposals[0]
    assert proposal["tool"] == "propose_regenerate"
    assert proposal["input"]["tool_name"] == "amendment"
    assert proposal["input"]["original_request"] == "보정청구항을 더 강하게 보강해줘"
    assert proposal["input"]["plan_summary"] == "보정안은 유지 가능한 권리범위를 남기면서 진보성 반박 포인트를 더 선명하게 보강합니다."
    assert proposal["input"]["rationale"] == [
        "사용자 요청이 보정청구항 강화에 집중되어 있어 Tool 6만 재생성하면 충분합니다.",
        "기존 전략의 핵심 논리는 유지하되 차이점 표현을 더 구체화합니다.",
    ]
    assert proposal["input"]["constraints"] == [
        "명세서에 직접 또는 암시적으로 뒷받침되는 표현만 사용합니다.",
        "권리범위를 불필요하게 좁히는 수치 한정은 피합니다.",
    ]
    assert proposal["input"]["hint"] == "진보성 반박 중심으로 보정안을 보강하되 권리범위 축소를 최소화"


def test_run_chatbot_falls_back_to_template_when_plan_llm_fails():
    result = make_analysis_result()
    request = ChatRequest(
        active_strategy="방어",
        messages=[Message(role="user", content="전략을 방어 중심으로 다시 짜줘")],
    )

    response = run_chatbot(request, result, FallbackLLM())

    proposal = response.proposals[0]
    assert proposal["tool"] == "propose_regenerate"
    assert proposal["input"]["tool_name"] == "strategy"
    assert proposal["input"]["original_request"] == "전략을 방어 중심으로 다시 짜줘"
    assert proposal["input"]["plan_summary"]
    assert proposal["input"]["rationale"]
    assert proposal["input"]["constraints"]


def test_run_chatbot_explanation_request_uses_chat_without_rerun_proposal():
    result = make_analysis_result()
    request = ChatRequest(
        active_strategy="방어",
        messages=[Message(role="user", content="방어 전략을 다시 설명해줘")],
    )

    response = run_chatbot(request, result, TextLLM())

    assert response.message.content == "설명 응답"
    assert response.proposals == []


@pytest.mark.asyncio
async def test_stream_chatbot_uses_llm_generated_rerun_plan_content():
    result = make_analysis_result()
    request = ChatRequest(
        active_strategy="방어",
        messages=[Message(role="user", content="보정청구항을 더 강하게 보강해줘")],
    )

    events = [event async for event in stream_chatbot(request, result, DraftPlanLLM())]

    assert events[0]["type"] == "token"
    assert "보정안은 유지 가능한 권리범위를 남기면서" in events[0]["content"]
    assert events[1] == {
        "type": "proposals",
        "data": [
            {
                "tool": "propose_regenerate",
                "input": {
                    "tool_name": "amendment",
                    "hint": "진보성 반박 중심으로 보정안을 보강하되 권리범위 축소를 최소화",
                    "original_request": "보정청구항을 더 강하게 보강해줘",
                    "plan_summary": "보정안은 유지 가능한 권리범위를 남기면서 진보성 반박 포인트를 더 선명하게 보강합니다.",
                    "rationale": [
                        "사용자 요청이 보정청구항 강화에 집중되어 있어 Tool 6만 재생성하면 충분합니다.",
                        "기존 전략의 핵심 논리는 유지하되 차이점 표현을 더 구체화합니다.",
                    ],
                    "constraints": [
                        "명세서에 직접 또는 암시적으로 뒷받침되는 표현만 사용합니다.",
                        "권리범위를 불필요하게 좁히는 수치 한정은 피합니다.",
                    ],
                },
            }
        ],
    }
    assert events[2] == {"type": "done"}


def test_find_editable_paths_tool_returns_candidate_paths():
    result = make_analysis_result()
    result.claim_parse.total_claims = 3

    payload = _execute_tool("find_editable_paths", {"query": "total", "limit": 5}, result)

    assert "claim_parse.total_claims" in payload
    assert '"current_value": 3' in payload
