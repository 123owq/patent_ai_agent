from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Iterable

from pydantic import ValidationError

from patent_agent.models.analysis import AnalysisResult


@dataclass(frozen=True)
class EditCandidate:
    target_path: str
    current_value: Any
    value_type: str
    preview: str


@dataclass(frozen=True)
class EditPreview:
    target_path: str
    current_value: Any
    proposed_value: Any
    normalized_value: Any
    value_type: str
    next_version: int


class InvalidTargetPath(ValueError):
    pass


class InvalidEditValue(ValueError):
    pass


def _split_path(path: str) -> list[str]:
    return path.replace("][", ".").replace("[", ".").replace("]", "").split(".")


def get_nested(obj: dict, path: str):
    try:
        for part in _split_path(path):
            obj = obj[int(part)] if part.isdigit() else obj[part]
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise InvalidTargetPath(f"Invalid target_path: {path!r} ({e})") from e
    return obj


def set_nested(obj: dict, path: str, value: object) -> dict:
    result = copy.deepcopy(obj)
    try:
        parts = _split_path(path)
        current = result
        for part in parts[:-1]:
            current = current[int(part)] if part.isdigit() else current[part]
        last = parts[-1]
        if last.isdigit():
            current[int(last)] = value
        else:
            current[last] = value
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise InvalidTargetPath(f"Invalid target_path: {path!r} ({e})") from e
    return result


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _is_editable_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _join_path(parent: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    return f"{parent}.{key}" if parent else key


def _iter_scalar_paths(value: Any, parent: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_scalar_paths(child, _join_path(parent, str(key)))
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_scalar_paths(child, _join_path(parent, index))
        return
    if parent and _is_editable_scalar(value):
        yield parent, value


def find_edit_candidates(
    analysis: AnalysisResult,
    query: str = "",
    limit: int = 20,
) -> list[EditCandidate]:
    result_dict = json.loads(analysis.model_dump_json())
    normalized_query = query.strip().lower()
    candidates: list[EditCandidate] = []

    for path, value in _iter_scalar_paths(result_dict):
        haystack = f"{path} {value}".lower()
        if normalized_query and normalized_query not in haystack:
            continue
        preview = str(value)
        candidates.append(EditCandidate(
            target_path=path,
            current_value=value,
            value_type=_type_name(value),
            preview=preview[:160],
        ))
        if len(candidates) >= limit:
            break

    return candidates


def preview_edit(
    analysis: AnalysisResult,
    target_path: str,
    new_value: object,
) -> EditPreview:
    result_dict = json.loads(analysis.model_dump_json())
    current_value = get_nested(result_dict, target_path)
    updated_dict = set_nested(result_dict, target_path, new_value)
    updated_dict["version"] = analysis.version + 1
    try:
        updated_result = AnalysisResult.model_validate(updated_dict)
    except ValidationError as e:
        raise InvalidEditValue(f"Invalid value for target_path {target_path!r}: {e}") from e

    normalized_dict = json.loads(updated_result.model_dump_json())
    normalized_value = get_nested(normalized_dict, target_path)
    return EditPreview(
        target_path=target_path,
        current_value=current_value,
        proposed_value=new_value,
        normalized_value=normalized_value,
        value_type=_type_name(normalized_value),
        next_version=updated_result.version,
    )
