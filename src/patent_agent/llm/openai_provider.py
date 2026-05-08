from __future__ import annotations
import json
from typing import AsyncIterator, Type, TypeVar
import openai
from pydantic import BaseModel
from patent_agent.llm.base import Message

T = TypeVar("T", bound=BaseModel)


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _ToolUseBlock:
    def __init__(self, id: str, name: str, input: dict) -> None:
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input


class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 120.0,
    ) -> None:
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.async_client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.model = model

    def generate(self, prompt: str, schema: Type[T], temperature: float = 0.0, max_tokens: int = 8192) -> T:
        tool = {
            "type": "function",
            "function": {
                "name": "output",
                "description": "Structured output",
                "parameters": schema.model_json_schema(),
            },
        }
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "output"}},
            temperature=temperature,
            max_tokens=max_tokens,
        )
        arguments = response.choices[0].message.tool_calls[0].function.arguments
        return schema.model_validate_json(arguments)

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> dict:
        oai_msgs = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict = {"model": self.model, "messages": oai_msgs, "max_tokens": 8192}
        if tools:
            kwargs["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["input_schema"],
                }}
                for t in tools
            ]
        response = self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        # Claude SDK 호환 포맷으로 변환
        content: list = []
        if msg.content:
            content.append(_TextBlock(msg.content))
        if msg.tool_calls:
            for tc in msg.tool_calls:
                content.append(_ToolUseBlock(
                    id=tc.id,
                    name=tc.function.name,
                    input=json.loads(tc.function.arguments),
                ))

        stop_reason = "tool_use" if choice.finish_reason == "tool_calls" else choice.finish_reason
        return {"content": content, "stop_reason": stop_reason}

    async def stream_chat(
        self, messages: list[Message], tools: list[dict] | None = None
    ) -> AsyncIterator[dict]:
        oai_msgs = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict = {"model": self.model, "messages": oai_msgs, "max_tokens": 8192}
        if tools:
            # chat.completions 형식으로 변환 (Responses API보다 streaming 안정적)
            kwargs["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["input_schema"],
                }}
                for t in tools
            ]

        tool_calls_acc: dict[int, dict] = {}

        async with self.async_client.chat.completions.stream(**kwargs) as stream:
            async for chunk in stream:
                choice = chunk.choices[0]
                delta = choice.delta

                if delta.content:
                    yield {"type": "token", "content": delta.content}

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc.id or "",
                                "name": tc.function.name or "",
                                "arguments": "",
                            }
                        if tc.function and tc.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc.function.arguments

                if choice.finish_reason:
                    if choice.finish_reason == "tool_calls":
                        tool_calls_list = []
                        for tc_data in tool_calls_acc.values():
                            try:
                                input_data = json.loads(tc_data["arguments"])
                            except Exception:
                                input_data = {}
                            yield {"type": "tool_use", "name": tc_data["name"],
                                   "input": input_data, "id": tc_data["id"]}
                            tool_calls_list.append({
                                "id": tc_data["id"], "type": "function",
                                "function": {"name": tc_data["name"],
                                             "arguments": tc_data["arguments"]},
                            })
                        yield {"type": "done", "stop_reason": "tool_use",
                               "content_for_history": [
                                   {"role": "assistant", "tool_calls": tool_calls_list}
                               ]}
                    else:
                        yield {"type": "done", "stop_reason": choice.finish_reason,
                               "content_for_history": []}
