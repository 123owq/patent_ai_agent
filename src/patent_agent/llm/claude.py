from __future__ import annotations
from typing import AsyncIterator, Type, TypeVar
import anthropic
from pydantic import BaseModel
from patent_agent.llm.base import Message

T = TypeVar("T", bound=BaseModel)


class ClaudeProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
    ) -> None:
        self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self.async_client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
        self.model = model

    def generate(self, prompt: str, schema: Type[T], temperature: float = 0.0) -> T:
        tool_def = {
            "name": "output",
            "description": "Structured output",
            "input_schema": schema.model_json_schema(),
        }
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=temperature,
            tools=[tool_def],
            tool_choice={"type": "tool", "name": "output"},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_use = next(b for b in response.content if b.type == "tool_use")
        return schema.model_validate(tool_use.input)

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> dict:
        anthropic_msgs = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": anthropic_msgs,
        }
        if tools:
            kwargs["tools"] = tools
        response = self.client.messages.create(**kwargs)
        return {"content": response.content, "stop_reason": response.stop_reason}

    async def stream_chat(
        self, messages: list[Message], tools: list[dict] | None = None
    ) -> AsyncIterator[dict]:
        anthropic_msgs = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": anthropic_msgs,
        }
        if tools:
            kwargs["tools"] = tools

        async with self.async_client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield {"type": "token", "content": text}

            final = await stream.get_final_message()

            # tool_use 블록 추출
            for block in final.content:
                if block.type == "tool_use":
                    yield {"type": "tool_use", "name": block.name,
                           "input": block.input, "id": block.id}

            # 다음 메시지 턴 구성용 content 직렬화
            content_for_history = [
                {"type": "text", "text": b.text} if b.type == "text"
                else {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                for b in final.content
            ]
            yield {"type": "done", "stop_reason": final.stop_reason or "end_turn",
                   "content_for_history": content_for_history}
