from __future__ import annotations
from typing import Type, TypeVar
import anthropic
from pydantic import BaseModel
from patent_agent.llm.base import Message

T = TypeVar("T", bound=BaseModel)


class ClaudeProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
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
