from __future__ import annotations
from typing import Type, TypeVar
import openai
from pydantic import BaseModel
from patent_agent.llm.base import Message

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider:
    def __init__(self, model: str = "gpt-4.1") -> None:
        self.client = openai.OpenAI()
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
