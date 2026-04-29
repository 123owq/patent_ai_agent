from __future__ import annotations
import json
from typing import AsyncIterator, Type, TypeVar
import openai
from pydantic import BaseModel
from patent_agent.llm.base import Message

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
    ) -> None:
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.async_client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def generate(self, prompt: str, schema: Type[T], temperature: float = 0.0) -> T:
        response = self.client.responses.parse(
            model=self.model,
            input=[{"role": "user", "content": prompt}],
            text_format=schema,
            temperature=temperature,
        )
        return response.output_parsed

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> dict:
        oai_msgs = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict = {"model": self.model, "input": oai_msgs}
        if tools:
            kwargs["tools"] = tools
        response = self.client.responses.create(**kwargs)
        return {"content": response.output, "stop_reason": response.stop_reason}

    async def stream_chat(
        self, messages: list[Message], tools: list[dict] | None = None
    ) -> AsyncIterator[dict]:
        oai_msgs = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict = {"model": self.model, "messages": oai_msgs}
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
