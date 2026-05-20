from __future__ import annotations
from datetime import datetime
import json
import os
from pathlib import Path
from typing import AsyncIterator, Type, TypeVar
import openai
from pydantic import BaseModel
from patent_agent.llm.base import Message

T = TypeVar("T", bound=BaseModel)


def _extract_json(text: str) -> str:
    # 마크다운 코드블록 제거
    if "```" in text:
        lines = text.split("\n")
        inside = False
        extracted = []
        for line in lines:
            if line.startswith("```"):
                inside = not inside
                continue
            if inside:
                extracted.append(line)
        text = "\n".join(extracted)
    # 첫 { 부터 마지막 } 까지만 추출
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end >= start:
        return text[start:end + 1]
    if start != -1:
        return text[start:]  # 닫는 } 없어도 일단 넘김 — Pydantic이 에러 처리
    return text


def _sanitize_path_part(value: str) -> str:
    safe = []
    for ch in value:
        if ch.isalnum() or ch in ("-", "_", "."):
            safe.append(ch)
        else:
            safe.append("_")
    return "".join(safe).strip("_") or "unknown"


def _to_openai_strict_json_schema(schema: dict) -> dict:
    """Convert Pydantic JSON Schema to OpenAI strict structured-output schema."""
    if isinstance(schema, list):
        return [_to_openai_strict_json_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    converted = {
        key: _to_openai_strict_json_schema(value)
        for key, value in schema.items()
        if key != "default"
    }
    properties = converted.get("properties")
    if isinstance(properties, dict):
        converted["additionalProperties"] = False
        converted["required"] = list(properties.keys())
    elif converted.get("type") == "object":
        converted["additionalProperties"] = False
    return converted


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
        self.base_url = base_url
        self.model = model

    def _openrouter_extra_body(self) -> dict | None:
        if "openrouter.ai" not in self.base_url:
            return None
        return {"provider": {"require_parameters": True}}

    def _supports_temperature(self) -> bool:
        return "gpt-5" not in self.model.lower()

    def _write_generate_debug_log(
        self,
        schema_name: str,
        *,
        finish_reason: str | None,
        had_tool_calls: bool,
        tool_call_name: str | None,
        raw_content: str | None,
        raw_arguments: str,
        extracted_json: str,
        validation_error: Exception,
    ) -> None:
        if os.getenv("LLM_DEBUG_RAW", "").lower() not in {"1", "true", "yes", "on"}:
            return

        data_dir = Path(os.getenv("DATA_DIR", "./data"))
        model_dir = _sanitize_path_part(self.model)
        directory = data_dir / "debug" / "llm" / model_dir
        directory.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = directory / f"{timestamp}-{_sanitize_path_part(schema_name)}.json"
        payload = {
            "model": self.model,
            "base_url": self.base_url,
            "schema": schema_name,
            "finish_reason": finish_reason,
            "had_tool_calls": had_tool_calls,
            "tool_call_name": tool_call_name,
            "raw_content": raw_content,
            "raw_arguments": raw_arguments,
            "extracted_json": extracted_json,
            "validation_error": str(validation_error),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def generate(self, prompt: str, schema: Type[T], temperature: float = 0.0, max_tokens: int = 16384) -> T:
        schema_json = _to_openai_strict_json_schema(schema.model_json_schema())
        extra_body = self._openrouter_extra_body()
        message_content = (
            f"{prompt}\n\n"
            "Return only a JSON object that conforms to the response_format schema. "
            "Do not include markdown fences or explanations. "
            "Include every schema field; use null or [] when a field is not applicable."
        )
        kwargs: dict = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": message_content,
            }],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "output",
                    "strict": True,
                    "schema": schema_json,
                },
            },
            "max_tokens": max_tokens,
        }
        if self._supports_temperature():
            kwargs["temperature"] = temperature
        if extra_body:
            kwargs["extra_body"] = extra_body
        response = self.client.chat.completions.create(
            **kwargs,
        )
        if not response.choices:
            raise ValueError(f"LLM 응답에 choices 없음: {getattr(response, 'error', response)}")
        choice = response.choices[0]
        msg = choice.message
        tool_calls = msg.tool_calls
        arguments = msg.content
        if not arguments:
            error = ValueError("LLM returned empty content for structured generate().")
            self._write_generate_debug_log(
                schema.__name__,
                finish_reason=choice.finish_reason,
                had_tool_calls=bool(tool_calls),
                tool_call_name=tool_calls[0].function.name if tool_calls else None,
                raw_content=msg.content,
                raw_arguments="",
                extracted_json="",
                validation_error=error,
            )
            raise error
        extracted = _extract_json(arguments)
        try:
            return schema.model_validate_json(extracted)
        except Exception as e:
            self._write_generate_debug_log(
                schema.__name__,
                finish_reason=choice.finish_reason,
                had_tool_calls=bool(tool_calls),
                tool_call_name=tool_calls[0].function.name if tool_calls else None,
                raw_content=msg.content,
                raw_arguments=arguments,
                extracted_json=extracted,
                validation_error=e,
            )
            raise

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> dict:
        oai_msgs = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict = {"model": self.model, "messages": oai_msgs, "max_tokens": 8192}
        extra_body = self._openrouter_extra_body()
        if extra_body:
            kwargs["extra_body"] = extra_body
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
        extra_body = self._openrouter_extra_body()
        if extra_body:
            kwargs["extra_body"] = extra_body
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

        response_stream = await self.async_client.chat.completions.create(
            stream=True, **kwargs
        )
        async for chunk in response_stream:
            if not chunk.choices:
                continue
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
