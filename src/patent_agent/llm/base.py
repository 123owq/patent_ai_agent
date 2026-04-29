from typing import AsyncIterator, Protocol, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Message(BaseModel):
    role: str
    content: str


class LLMClient(Protocol):
    def generate(self, prompt: str, schema: Type[T], temperature: float = 0.0) -> T: ...
    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> dict: ...
    def stream_chat(
        self, messages: list[Message], tools: list[dict] | None = None
    ) -> AsyncIterator[dict]: ...
