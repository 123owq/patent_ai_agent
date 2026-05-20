import json
import os
import re
import shutil
from pathlib import Path
from patent_agent.models.analysis import AnalysisResult


_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def model_name_to_id(model_name: str) -> str:
    return model_name.replace("/", "__") if model_name else ""


def normalize_model_id(model_id: str | None) -> str:
    if not model_id:
        return ""
    normalized = model_name_to_id(model_id.strip())
    if (
        not normalized
        or "/" in normalized
        or "\\" in normalized
        or ".." in normalized
        or not _MODEL_ID_RE.fullmatch(normalized)
    ):
        raise ValueError(f"Invalid model_id: {model_id!r}")
    return normalized


def _model_dir(model_id: str | None = None) -> str:
    explicit = normalize_model_id(model_id)
    if explicit:
        return explicit
    model = os.getenv("OPENAI_MODEL") or os.getenv("CLAUDE_MODEL") or ""
    return normalize_model_id(model)


def _analysis_dir(application_number: str, model_id: str | None = None) -> Path:
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    model = _model_dir(model_id)
    if model:
        return data_dir / "analysis" / application_number / model
    return data_dir / "analysis" / application_number


def save_analysis(result: AnalysisResult, model_id: str | None = None) -> Path:
    directory = _analysis_dir(result.application_number, model_id)
    directory.mkdir(parents=True, exist_ok=True)
    versioned = directory / f"result.v{result.version}.json"
    latest = directory / "result.json"
    content = result.model_dump_json(indent=2)
    versioned.write_text(content, encoding="utf-8")
    shutil.copy2(versioned, latest)
    return latest


def load_analysis(application_number: str, model_id: str | None = None) -> AnalysisResult:
    latest = _analysis_dir(application_number, model_id) / "result.json"
    if not latest.exists():
        raise FileNotFoundError(f"분석 결과 없음: {application_number}")
    return AnalysisResult.model_validate_json(latest.read_text(encoding="utf-8"))


def load_analysis_version(
    application_number: str,
    version: int,
    model_id: str | None = None,
) -> AnalysisResult:
    path = _analysis_dir(application_number, model_id) / f"result.v{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"버전 {version} 없음: {application_number}")
    return AnalysisResult.model_validate_json(path.read_text(encoding="utf-8"))


def list_versions(application_number: str, model_id: str | None = None) -> list[int]:
    directory = _analysis_dir(application_number, model_id)
    if not directory.exists():
        return []
    versions = [
        int(p.stem.split(".v")[1])
        for p in directory.glob("result.v*.json")
        if ".v" in p.stem
    ]
    return sorted(versions)


def load_input_patent(application_number: str) -> dict:
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    path = data_dir / "input" / application_number / "patent.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_input_office_action(application_number: str) -> dict:
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    path = data_dir / "input" / application_number / "office_action.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_input_prior_arts(application_number: str) -> list[dict]:
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    directory = data_dir / "input" / application_number / "prior_arts"
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("*.json"))
    ]
