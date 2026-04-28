import json
import os
import shutil
from pathlib import Path
from patent_agent.models.analysis import AnalysisResult


def _analysis_dir(application_number: str) -> Path:
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    return data_dir / "analysis" / application_number


def save_analysis(result: AnalysisResult) -> Path:
    directory = _analysis_dir(result.application_number)
    directory.mkdir(parents=True, exist_ok=True)
    versioned = directory / f"result.v{result.version}.json"
    latest = directory / "result.json"
    content = result.model_dump_json(indent=2)
    versioned.write_text(content, encoding="utf-8")
    shutil.copy2(versioned, latest)
    return latest


def load_analysis(application_number: str) -> AnalysisResult:
    latest = _analysis_dir(application_number) / "result.json"
    if not latest.exists():
        raise FileNotFoundError(f"분석 결과 없음: {application_number}")
    return AnalysisResult.model_validate_json(latest.read_text(encoding="utf-8"))


def load_analysis_version(application_number: str, version: int) -> AnalysisResult:
    path = _analysis_dir(application_number) / f"result.v{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"버전 {version} 없음: {application_number}")
    return AnalysisResult.model_validate_json(path.read_text(encoding="utf-8"))


def list_versions(application_number: str) -> list[int]:
    directory = _analysis_dir(application_number)
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
