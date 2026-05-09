from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import AsyncIterator, Type, TypeVar
from pydantic import BaseModel
from patent_agent.llm.base import LLMClient, Message

T = TypeVar("T", bound=BaseModel)


def _hash(*args) -> str:
    data = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def _serialize_content(content) -> list[dict]:
    result = []
    for block in (content if isinstance(content, list) else []):
        if not hasattr(block, "type"):
            continue
        if block.type == "text":
            result.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            result.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return result


class _Block:
    """저장된 dict를 Anthropic SDK 객체처럼 .type/.text/.name/.input/.id 접근 가능하게"""
    def __init__(self, data: dict):
        self.type = data["type"]
        self.text = data.get("text", "")
        self.id = data.get("id", "")
        self.name = data.get("name", "")
        self.input = data.get("input", {})


class RecordingLLMClient:
    """
    캐시 있으면 캐시 반환, 없으면 real_llm 호출 후 저장.
    LLM_PROVIDER=recording 으로 서버 가동 시 real_llm은 get_llm()이 자동 주입.
    """

    def __init__(self, real_llm: LLMClient, cassette_dir: str = "tests/cassettes"):
        self.real_llm = real_llm
        self.cassette_dir = Path(cassette_dir)
        self.cassette_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.cassette_dir / f"{key}.json"

    def generate(self, prompt: str, schema: Type[T], temperature: float = 0.0, max_tokens: int = 16384) -> T:
        key = _hash("generate", prompt, schema.__name__, temperature)
        path = self._path(key)

        if path.exists():
            return schema.model_validate_json(path.read_text(encoding="utf-8"))

        result = self.real_llm.generate(prompt, schema, temperature, max_tokens)
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> dict:
        key = _hash("chat", [(m.role, m.content) for m in messages], tools)
        path = self._path(key)

        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {
                "content": [_Block(b) for b in raw["content"]],
                "stop_reason": raw["stop_reason"],
            }

        response = self.real_llm.chat(messages, tools)
        serialized = {
            "content": _serialize_content(response["content"]),
            "stop_reason": response["stop_reason"],
        }
        path.write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")
        return response

    async def stream_chat(
        self, messages: list[Message], tools: list[dict] | None = None
    ) -> AsyncIterator[dict]:
        key = _hash("stream_chat", [(m.role, m.content) for m in messages], tools)
        path = self._path(key)

        if path.exists():
            events = json.loads(path.read_text(encoding="utf-8"))
            for event in events:
                yield event
            return

        events: list[dict] = []
        async for event in self.real_llm.stream_chat(messages, tools):
            events.append(event)
            yield event

        path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
