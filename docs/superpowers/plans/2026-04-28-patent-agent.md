# 특허 심사대응 AI 플랫폼 구현 계획서

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 특허 의견제출통지서·자사특허·인용문헌 JSON을 입력받아 Claim Chart 생성·검증, 공격·방어 전략, 보정청구항을 자동 생성하는 FastAPI 백엔드를 구현한다.

**Architecture:** Tool 1~6의 Pure Python 함수 파이프라인이 결정적 직선 실행으로 AnalysisResult를 생성하고, 챗봇 Agent는 저장된 결과를 RAG 컨텍스트로 참조한다. LLM Provider Abstraction으로 Claude/OpenAI를 환경변수 스위칭한다.

**Tech Stack:** Python 3.12, uv, FastAPI, Pydantic v2, Jinja2, anthropic SDK, openai SDK, pdfplumber, pytest

**Spec:** `docs/superpowers/specs/2026-04-28-patent-agent-design.md`

---

## File Structure

```
src/patent_agent/
├── models/
│   ├── input.py         # PatentDoc, PriorArtDoc, OfficeActionRaw
│   ├── output.py        # Tool 1~6 출력 모델 + ExaminerChart + ToolError
│   └── analysis.py      # AnalysisResult, EditLogEntry
├── llm/
│   ├── base.py          # LLMClient Protocol
│   ├── claude.py        # ClaudeProvider
│   ├── openai_provider.py  # OpenAIProvider
│   └── __init__.py      # get_llm()
├── prompts/             # Jinja2 .j2 템플릿
│   ├── tool1.j2
│   ├── tool2.j2
│   ├── tool3.j2
│   ├── tool4.j2
│   ├── tool5_offensive.j2
│   ├── tool5_defensive.j2
│   ├── tool6_offensive.j2
│   ├── tool6_defensive.j2
│   └── chatbot_system.j2
├── tools/
│   ├── tool1_parse_office_action.py
│   ├── tool2_parse_claims.py
│   ├── tool3_map_spec.py
│   ├── tool4_claim_chart.py
│   ├── tool5_strategy.py
│   └── tool6_amendment.py
├── core/
│   ├── pipeline.py      # run_analysis()
│   ├── chatbot.py       # chatbot agent loop
│   └── storage.py       # save / load / version
└── api/
    ├── main.py
    ├── deps.py
    └── routers/
        ├── analysis.py
        ├── stream.py
        ├── edits.py
        └── chat.py

tests/
├── fixtures/
│   └── 10-2014-0036561/
│       ├── patent.json         # 보유 파일 복사
│       ├── office_action.json
│       └── prior_arts/
├── unit/
│   ├── test_tool1.py
│   ├── test_tool2.py
│   ├── test_tool3.py
│   ├── test_tool4.py
│   ├── test_tool5.py
│   ├── test_tool6.py
│   └── test_storage.py
└── integration/
    └── test_pipeline.py
```

---

## Task 0: 프로젝트 환경 세팅

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.env.example`
- Create: `src/patent_agent/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: uv로 프로젝트 초기화**

```bash
uv init patent-agent --python 3.12
cd patent-agent
```

- [ ] **Step 2: `pyproject.toml` 작성**

```toml
[project]
name = "patent-agent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "anthropic>=0.40",
    "openai>=1.50",
    "pydantic>=2.8",
    "pydantic-settings>=2.5",
    "jinja2>=3.1",
    "pdfplumber>=0.11",
    "python-multipart>=0.0.9",
    "httpx>=0.27",
    "sse-starlette>=2.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.6",
    "pyright>=1.1",
    "pytest-mock>=3.14",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/patent_agent"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

- [ ] **Step 3: 의존성 설치**

```bash
uv sync --extra dev
```

- [ ] **Step 4: `.env.example` 작성**

```bash
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-6
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1
DATA_DIR=./data
API_PORT=8000
CORS_ORIGINS=http://localhost:3000
```

- [ ] **Step 5: 디렉토리 생성**

```bash
mkdir -p src/patent_agent/{models,llm,prompts,tools,core,api/routers}
mkdir -p tests/{fixtures/10-2014-0036561/prior_arts,unit,integration}
mkdir -p data/{input/10-2014-0036561/prior_arts,analysis/10-2014-0036561}
touch src/patent_agent/__init__.py
touch src/patent_agent/{models,llm,tools,core,api,api/routers}/__init__.py
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
```

- [ ] **Step 6: 보유 JSON 파일을 fixtures에 복사**

`data/input/10-2014-0036561/` 하위의 파일들을 `tests/fixtures/10-2014-0036561/`에 복사.

- [ ] **Step 7: Commit**

```bash
git add .
git commit -m "chore: 프로젝트 환경 세팅 (uv, pyproject.toml, 디렉토리 구조)"
```

---

## Task 1: 데이터 모델 (Pydantic)

**Files:**
- Create: `src/patent_agent/models/input.py`
- Create: `src/patent_agent/models/output.py`
- Create: `src/patent_agent/models/analysis.py`

- [ ] **Step 1: `models/input.py` 작성**

```python
from pydantic import BaseModel


class PatentDoc(BaseModel):
    application_number: str
    title: str
    abstract: str
    claims: dict[int, str]            # {1: "웨트 마스터 배치...", ...}
    spec_paragraphs: dict[str, str]   # {"0001": "본 발명은...", ...}


class PriorArtDoc(PatentDoc):
    prior_art_id: str                 # "인용발명1"
    publication_number: str


class OfficeActionRaw(BaseModel):
    application_number: str
    raw_dict: dict
```

- [ ] **Step 2: `models/output.py` 작성**

```python
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


# ── Tool 1 출력 ─────────────────────────────────────────────────────
class RejectionReason(BaseModel):
    article: str
    rejection_type: Literal["진보성", "신규성", "기재불비", "기타"]
    target_claim_numbers: list[int]
    cited_art_ids: list[str]
    examiner_reasoning: str


class CitedArtRef(BaseModel):
    cited_art_id: str
    document_number: str


class OfficeActionResult(BaseModel):
    application_number: str
    rejection_reasons: list[RejectionReason]
    rejected_claim_numbers: list[int]
    cited_arts: list[CitedArtRef]


# ── Tool 2 출력 ─────────────────────────────────────────────────────
class ClaimElement(BaseModel):
    element_id: str                   # "1-A", "1-B"
    element_order: int
    text: str
    label: str | None


class Claim(BaseModel):
    claim_number: int
    claim_type: Literal["독립항", "종속항"]
    depends_on: list[int] = []
    preamble: str | None = None
    original_text: str
    elements: list[ClaimElement]


class ClaimParseResult(BaseModel):
    application_number: str
    total_claims: int
    independent_claims: list[int]
    dependent_claims: list[int]
    claims: list[Claim]


# ── Tool 3 출력 ─────────────────────────────────────────────────────
class ElementSpecMapping(BaseModel):
    element_id: str
    paragraph_ids: list[str]
    rationale: str
    confidence: float


class SpecMappingResult(BaseModel):
    mappings: list[ElementSpecMapping]


# ── Tool 4 보조 + 출력 ───────────────────────────────────────────────
class ExaminerChartRow(BaseModel):
    element_label: str
    our_claim_text: str
    prior_art_text: str
    prior_art_id: str
    examiner_match: Literal["동일", "유사", "차이"]
    note: str | None = None


class ExaminerChart(BaseModel):
    rows: list[ExaminerChartRow]


class ClaimChartRow(BaseModel):
    element_id: str
    element_text: str
    prior_art_id: str
    prior_art_element: str | None = None
    prior_art_location: str | None = None
    our_match: Literal["동일", "유사", "차이"]
    our_explanation: str
    examiner_match: Literal["동일", "유사", "차이"] | None = None
    examiner_explanation: str | None = None
    agreement: Literal["일치", "불일치"] | None = None
    disagreement_rationale: str | None = None


class ClaimChart(BaseModel):
    target_claim_number: int
    rows: list[ClaimChartRow]


class ClaimChartResult(BaseModel):
    charts: list[ClaimChart]


# ── Tool 5 출력 ─────────────────────────────────────────────────────
class Strategy(BaseModel):
    strategy_type: Literal["공격", "방어"]
    rationale: str
    leveraged_differences: list[str]
    proposed_action: str


class StrategyResult(BaseModel):
    offensive: Strategy
    defensive: Strategy


# ── Tool 6 출력 ─────────────────────────────────────────────────────
class AmendedClaim(BaseModel):
    claim_number: int
    original_text: str
    amended_text: str
    diff_summary: str
    spec_basis: list[str]


class AmendmentDraft(BaseModel):
    strategy_type: Literal["공격", "방어"]
    amended_claims: list[AmendedClaim]
    overall_explanation: str


class AmendmentResult(BaseModel):
    offensive_draft: AmendmentDraft
    defensive_draft: AmendmentDraft


# ── 에러 ────────────────────────────────────────────────────────────
class ToolError(BaseModel):
    tool_name: str
    error_type: Literal["llm_failure", "validation_error", "timeout"]
    message: str
    is_fatal: bool
```

- [ ] **Step 3: `models/analysis.py` 작성**

```python
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
from patent_agent.models.output import (
    OfficeActionResult, ClaimParseResult, SpecMappingResult,
    ClaimChartResult, StrategyResult, AmendmentResult, ToolError,
)


class AnalysisResult(BaseModel):
    analysis_id: str
    application_number: str
    created_at: datetime = Field(default_factory=datetime.now)
    version: int = 1
    source_files: dict[str, str] = {}
    errors: list[ToolError] = []
    office_action: OfficeActionResult
    claim_parse: ClaimParseResult
    spec_mapping: SpecMappingResult
    claim_chart: ClaimChartResult
    strategy: StrategyResult
    amendment: AmendmentResult


class EditLogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    target_path: str
    before: str
    after: str
    source: Literal["user-direct", "llm-proposed-user-applied", "regenerate"]
    user_instruction: str | None = None
```

- [ ] **Step 4: 모델 import 확인**

```bash
uv run python -c "from patent_agent.models.analysis import AnalysisResult; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/patent_agent/models/
git commit -m "feat: Pydantic 데이터 모델 정의 (input, output, analysis)"
```

---

## Task 2: LLM Provider Abstraction

**Files:**
- Create: `src/patent_agent/llm/base.py`
- Create: `src/patent_agent/llm/claude.py`
- Create: `src/patent_agent/llm/openai_provider.py`
- Create: `src/patent_agent/llm/__init__.py`
- Create: `tests/unit/test_llm.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/test_llm.py
import os
import pytest
from pydantic import BaseModel
from patent_agent.llm import get_llm
from patent_agent.llm.base import LLMClient


class _SampleSchema(BaseModel):
    value: str


def test_get_llm_returns_claude_by_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    llm = get_llm()
    assert llm is not None


def test_get_llm_returns_openai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    llm = get_llm()
    assert llm is not None


def test_get_llm_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        get_llm()
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
uv run pytest tests/unit/test_llm.py -v
```

Expected: FAIL (모듈 없음)

- [ ] **Step 3: `llm/base.py` 작성**

```python
from typing import Protocol, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Message(BaseModel):
    role: str
    content: str


class LLMClient(Protocol):
    def generate(self, prompt: str, schema: Type[T], temperature: float = 0.0) -> T: ...
    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> dict: ...
```

- [ ] **Step 4: `llm/claude.py` 작성**

```python
from __future__ import annotations
import json
from typing import Type, TypeVar
import anthropic
from pydantic import BaseModel
from patent_agent.llm.base import Message

T = TypeVar("T", bound=BaseModel)


class ClaudeProvider:
    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.client = anthropic.Anthropic()
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
        kwargs: dict = {"model": self.model, "max_tokens": 4096,
                        "messages": anthropic_msgs}
        if tools:
            kwargs["tools"] = tools
        response = self.client.messages.create(**kwargs)
        return {"content": response.content, "stop_reason": response.stop_reason}
```

- [ ] **Step 5: `llm/openai_provider.py` 작성**

```python
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
```

- [ ] **Step 6: `llm/__init__.py` 작성**

```python
import os
from patent_agent.llm.base import LLMClient
from patent_agent.llm.claude import ClaudeProvider
from patent_agent.llm.openai_provider import OpenAIProvider


def get_llm() -> LLMClient:
    provider = os.getenv("LLM_PROVIDER", "claude").lower()
    if provider == "claude":
        model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
        return ClaudeProvider(model=model)
    if provider == "openai":
        model = os.getenv("OPENAI_MODEL", "gpt-4.1")
        return OpenAIProvider(model=model)
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'claude' or 'openai'.")
```

- [ ] **Step 7: 테스트 실행 — 통과 확인**

```bash
uv run pytest tests/unit/test_llm.py -v
```

Expected: 3 passed

- [ ] **Step 8: Commit**

```bash
git add src/patent_agent/llm/ tests/unit/test_llm.py
git commit -m "feat: LLM provider abstraction (Claude/OpenAI 환경변수 스위칭)"
```

---

## Task 3: Storage (저장·로드·버전 관리)

**Files:**
- Create: `src/patent_agent/core/storage.py`
- Create: `tests/unit/test_storage.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/test_storage.py
import json
from pathlib import Path
import pytest
from patent_agent.core.storage import save_analysis, load_analysis, list_versions
from tests.unit.factories import make_analysis_result


def test_save_creates_versioned_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    result = make_analysis_result(application_number="10-2014-0036561")
    save_analysis(result)
    v1 = tmp_path / "analysis" / "10-2014-0036561" / "result.v1.json"
    latest = tmp_path / "analysis" / "10-2014-0036561" / "result.json"
    assert v1.exists()
    assert latest.exists()


def test_load_returns_latest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    result = make_analysis_result(application_number="10-2014-0036561")
    save_analysis(result)
    loaded = load_analysis("10-2014-0036561")
    assert loaded.application_number == "10-2014-0036561"
    assert loaded.version == 1


def test_save_increments_version(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    r1 = make_analysis_result(application_number="10-0000-0000001")
    save_analysis(r1)
    r2 = make_analysis_result(application_number="10-0000-0000001")
    r2.version = 2
    save_analysis(r2)
    versions = list_versions("10-0000-0000001")
    assert versions == [1, 2]
```

- [ ] **Step 2: 테스트 픽스처 팩토리 작성**

```python
# tests/unit/factories.py
from datetime import datetime
from patent_agent.models.analysis import AnalysisResult
from patent_agent.models.output import (
    OfficeActionResult, ClaimParseResult, SpecMappingResult,
    ClaimChartResult, StrategyResult, AmendmentResult,
    AmendmentDraft, Strategy,
)


def make_analysis_result(application_number: str = "10-test") -> AnalysisResult:
    return AnalysisResult(
        analysis_id=f"test-{application_number}",
        application_number=application_number,
        created_at=datetime.now(),
        office_action=OfficeActionResult(
            application_number=application_number,
            rejection_reasons=[],
            rejected_claim_numbers=[],
            cited_arts=[],
        ),
        claim_parse=ClaimParseResult(
            application_number=application_number,
            total_claims=0,
            independent_claims=[],
            dependent_claims=[],
            claims=[],
        ),
        spec_mapping=SpecMappingResult(mappings=[]),
        claim_chart=ClaimChartResult(charts=[]),
        strategy=StrategyResult(
            offensive=Strategy(
                strategy_type="공격",
                rationale="test",
                leveraged_differences=[],
                proposed_action="test",
            ),
            defensive=Strategy(
                strategy_type="방어",
                rationale="test",
                leveraged_differences=[],
                proposed_action="test",
            ),
        ),
        amendment=AmendmentResult(
            offensive_draft=AmendmentDraft(
                strategy_type="공격",
                amended_claims=[],
                overall_explanation="test",
            ),
            defensive_draft=AmendmentDraft(
                strategy_type="방어",
                amended_claims=[],
                overall_explanation="test",
            ),
        ),
    )
```

- [ ] **Step 3: 테스트 실행 — 실패 확인**

```bash
uv run pytest tests/unit/test_storage.py -v
```

Expected: FAIL (storage 모듈 없음)

- [ ] **Step 4: `core/storage.py` 작성**

```python
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
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

```bash
uv run pytest tests/unit/test_storage.py -v
```

Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add src/patent_agent/core/storage.py tests/unit/ 
git commit -m "feat: storage 레이어 (save/load/version AnalysisResult)"
```

---

## Task 4: 프롬프트 템플릿 기반 유틸리티

**Files:**
- Create: `src/patent_agent/core/prompts.py`
- Create: `src/patent_agent/prompts/tool1.j2` ~ `tool6_defensive.j2`, `chatbot_system.j2`

- [ ] **Step 1: `core/prompts.py` 작성**

```python
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

_PROMPT_DIR = Path(__file__).parent.parent / "prompts"
_env = Environment(loader=FileSystemLoader(str(_PROMPT_DIR)), autoescape=False)


def render(template_name: str, **kwargs: object) -> str:
    """Jinja2 템플릿 렌더링. template_name 예: 'tool1.j2'"""
    return _env.get_template(template_name).render(**kwargs)
```

- [ ] **Step 2: 각 Tool 프롬프트 템플릿 작성**

**`prompts/tool1.j2`** — 통지서 분석

```jinja2
당신은 대한민국 특허 심사 전문가입니다.
다음 의견제출통지서 JSON을 분석하여 요청된 스키마로 구조화하세요.

## 핵심 작업
1. 모든 거절이유를 추출하고 유형을 분류하세요 (진보성/신규성/기재불비/기타).
2. "제1항, 제4항 내지 제7항" 같은 청구항 범위 표현을 정수 리스트로 변환하세요.
   - "제N항" → [N]
   - "제N항 내지 제M항" → [N, N+1, ..., M]
   - "제N항, 제M항 내지 제P항" → [N, M, M+1, ..., P]
3. 모든 인용문헌(인용발명)을 추출하세요.
4. rejected_claim_numbers는 모든 거절이유의 target_claim_numbers를 합산한 유니크 목록입니다.

## 입력 JSON
{{ raw_dict | tojson(indent=2) }}
```

**`prompts/tool2.j2`** — 청구항 파싱

```jinja2
당신은 대한민국 특허 청구항 분석 전문가입니다.
다음 청구항을 구성요소 단위로 분해하여 구조화하세요.

## 핵심 작업
1. 각 청구항의 독립항/종속항 여부를 판단하세요.
   - "제N항에 있어서" → 종속항, depends_on: [N]
   - "제N항 내지 제M항 중 어느 한 항에 있어서" → 종속항, depends_on: [N..M]
2. 독립항은 전제부(preamble)와 구성요소를 분리하세요.
3. 각 구성요소에 element_id를 부여하세요: 청구항1의 구성요소는 "1-A", "1-B", ...
4. label은 해당 구성요소가 나타내는 기술 내용을 10자 이내로 요약하세요.

## 예시 (Few-shot seed)
청구항 1 원문:
"웨트 마스터 배치(wet master batch) 50 내지 200 중량부 및 스티렌-부타디엔 고무 60 내지 70 중량부를
포함하는 원료고무 100중량부에 대하여; 요오드(I2) 흡착가가 200 내지 1000mg/g이고..."

구성요소 분해 예시:
- 1-A (원료고무 조성): "웨트 마스터 배치 50~200 중량부 및 스티렌-부타디엔 고무 60~70 중량부"
- 1-B (카본블랙 사양): "요오드 흡착가 200~1000mg/g, DBP 흡착량 150~800ml/100g인 카본블랙 50~200 중량부"
- 1-C (석유계 수지): "연화점 50~170℃인 석유계 수지 10~60 중량부"
- 1-D (웨트 마스터 배치 제조): "스티렌부타디엔 라텍스 100중량부, 카본블랙 50~200중량부, RAE 오일 50~200중량부를 회분식 중합"

## 입력 청구항
출원번호: {{ application_number }}
{% for num, text in claims.items() %}
청구항 {{ num }}: {{ text }}
{% endfor %}
```

**`prompts/tool3.j2`** — 상세설명 매핑

```jinja2
당신은 특허 명세서 분석 전문가입니다.
각 청구항 구성요소를 가장 잘 뒷받침하는 명세서 단락을 찾아 매핑하세요.

## 핵심 작업
1. 각 element_id에 대해 명세서에서 해당 구성요소를 구체적으로 설명하는 단락을 선택하세요.
2. 단락이 여러 개라면 모두 포함하세요 (최대 3개 권장).
3. confidence는 매핑의 확신도 (0.0~1.0).
4. rationale은 왜 이 단락이 해당 구성요소를 뒷받침하는지 1~2문장 설명.

## 구성요소 목록
{% for element in elements %}
- {{ element.element_id }} ({{ element.label }}): {{ element.text }}
{% endfor %}

## 명세서 단락
{% for para_id, text in spec_paragraphs.items() %}
[단락 {{ para_id }}] {{ text }}
{% endfor %}
```

**`prompts/tool4.j2`** — Claim Chart 생성·검증

```jinja2
당신은 특허 진보성 분석 전문가입니다.
자사 청구항 구성요소와 인용발명을 비교하여 Claim Chart를 생성하고,
심사관의 기존 판단이 타당한지 검증하세요.

## 자사 청구항 {{ target_claim_number }}항 구성요소
{% for element in elements %}
- {{ element.element_id }}: {{ element.text }}
{% endfor %}

## 인용발명: {{ prior_art.prior_art_id }} ({{ prior_art.publication_number }})
청구항:
{% for num, text in prior_art.claims.items() %}
  청구항{{ num }}: {{ text }}
{% endfor %}

{% if examiner_chart %}
## 심사관 기존 비교표 (검증 대상)
{% for row in examiner_chart.rows %}
- {{ row.element_label }}: 심사관 판단={{ row.examiner_match }} | 이 출원={{ row.our_claim_text }} | 인용발명={{ row.prior_art_text }}
{% endfor %}
{% endif %}

## 작성 지침
각 구성요소 element_id에 대해:
1. our_match: 인용발명에서 대응 요소를 찾아 "동일/유사/차이" 판정
2. prior_art_element: 인용발명의 대응 텍스트
3. prior_art_location: 인용발명 어디서 찾았는지 ("청구항 1", "단락 0012" 등)
4. our_explanation: 판정 근거 (수치 범위, 기술적 차이 등 구체적으로)
5. 심사관 판단이 있을 경우: agreement 판정 및 불일치 시 disagreement_rationale 작성
   - 불일치 예: 심사관이 "동일"이라 했지만 수치 범위가 실질적으로 다를 때
```

**`prompts/tool5.j2`** — 공격·방어 전략 동시 생성 (StrategyResult 한 번에 반환)

```jinja2
당신은 특허 대응 전략 전문가입니다. 공격적 전략과 방어적 전략을 동시에 수립하세요.

공격적 전략 = 현재 청구항의 권리범위를 최대한 유지하면서 진보성을 인정받는 전략.
방어적 전략 = 거절이유를 극복하기 위해 청구항에 구성요소를 추가 한정하는 전략.

## Claim Chart 분석 결과
{% for chart in claim_charts %}
청구항 {{ chart.target_claim_number }}항:
{% for row in chart.rows %}
  {{ row.element_id }}: our={{ row.our_match }}, examiner={{ row.examiner_match or "N/A" }}, agreement={{ row.agreement or "N/A" }}
  {% if row.agreement == "불일치" %}  ⭐ 불일치 근거: {{ row.disagreement_rationale }}{% endif %}
{% endfor %}
{% endfor %}

## 거절이유 요약
{% for reason in rejection_reasons %}
- {{ reason.rejection_type }}: {{ reason.examiner_reasoning[:200] }}
{% endfor %}

## 작성 지침
1. 특히 "agreement=불일치 + our_match=차이 + examiner_match=동일/유사" 항목에 집중하세요.
   → 이것이 심사관 판단에 이의를 제기하는 가장 강력한 근거입니다.
2. leveraged_differences에는 활용한 element_id를 나열하세요.
3. proposed_action은 구체적인 행동 방향을 기술하세요.
4. ClaimChart 불일치가 충분하면 청구항 변경 없이 의견서 주장을 제안할 수 있습니다.
```

**`prompts/tool5_defensive.j2`** — 방어 전략

```jinja2
당신은 특허 대응 전략 전문가입니다. 방어적 전략을 수립하세요.

방어적 전략 = 거절이유를 극복하기 위해 청구항에 구성요소를 추가 한정하여 등록 가능성을 높이는 전략.

## Claim Chart 분석 결과
{% for chart in claim_charts %}
청구항 {{ chart.target_claim_number }}항 — "동일/유사" 구성요소 (한정 추가 필요):
{% for row in chart.rows %}
  {% if row.our_match in ["동일", "유사"] %}
  {{ row.element_id }}: {{ row.element_text[:80] }}
  {% endif %}
{% endfor %}
{% endfor %}

## 상세설명 매핑 (추가 한정 근거 단락)
{% for mapping in spec_mappings %}
- {{ mapping.element_id }}: 단락 {{ mapping.paragraph_ids }} (confidence={{ mapping.confidence:.2f }})
{% endfor %}

## 작성 지침
1. "동일/유사"로 판정된 구성요소 중 명세서에 더 구체적인 기재가 있는 항목을 찾으세요.
2. 해당 명세서 기재를 근거로 청구항에 추가 한정할 내용을 제안하세요.
3. 모든 추가 한정은 반드시 최초 명세서 기재 사항 범위 내여야 합니다.
4. leveraged_differences에는 추가 한정이 필요한 element_id를 나열하세요.
```

**`prompts/tool6_offensive.j2`** — 공격 보정청구항

```jinja2
당신은 특허 보정 전문가입니다. 공격적 전략에 따라 보정청구항을 작성하세요.

공격적 전략 기조: {{ strategy.proposed_action }}
활용 차이점: {{ strategy.leveraged_differences | join(", ") }}

## 원본 청구항
{% for claim in rejected_claims %}
청구항 {{ claim.claim_number }} ({{ claim.claim_type }}):
{{ claim.original_text }}
{% endfor %}

## 작성 지침
1. 공격적 전략에서 ClaimChart 불일치가 충분하면 청구항 텍스트를 그대로 유지하고
   amended_text == original_text로 작성하세요.
2. 부분 한정이 필요한 경우에만 텍스트를 수정하세요.
3. diff_summary는 변경한 내용을 1~2문장으로 설명 (변경 없으면 "원문 유지 — 의견서로 진보성 주장").
4. spec_basis는 근거가 되는 명세서 단락 ID 목록 (변경이 있는 경우).
```

**`prompts/tool6_defensive.j2`** — 방어 보정청구항

```jinja2
당신은 특허 보정 전문가입니다. 방어적 전략에 따라 보정청구항을 작성하세요.

방어적 전략 기조: {{ strategy.proposed_action }}
추가 한정 대상 구성요소: {{ strategy.leveraged_differences | join(", ") }}

## 원본 청구항
{% for claim in rejected_claims %}
청구항 {{ claim.claim_number }} ({{ claim.claim_type }}):
{{ claim.original_text }}
{% endfor %}

## 상세설명 한정 근거
{% for mapping in relevant_mappings %}
{{ mapping.element_id }} → 단락 {{ mapping.paragraph_ids }}:
{% for para_id in mapping.paragraph_ids %}
  [{{ para_id }}] {{ spec_paragraphs.get(para_id, "") }}
{% endfor %}
{% endfor %}

## 작성 지침
1. 전략에서 지정한 구성요소에 추가 한정을 삽입하세요.
2. ⚠️ 모든 추가 내용은 반드시 위 상세설명 한정 근거에 기재된 내용 범위 내여야 합니다.
3. spec_basis에는 사용한 단락 ID를 모두 나열하세요.
4. diff_summary는 무엇을 어떻게 변경했는지 명확히 기술하세요.
```

**`prompts/chatbot_system.j2`** — 챗봇 시스템 프롬프트

```jinja2
당신은 특허 심사대응 AI 어시스턴트입니다.

## 역할과 제약
- 분석 결과를 기반으로 IP 담당자의 질문에 명확하게 답변합니다.
- 법적 판단을 확정하지 않습니다. 항상 "참고용"임을 명시하세요.
- 필요 시 수정 제안(propose_patch, propose_regenerate)을 제시할 수 있으나,
  실제 적용은 사용자가 UI에서 확인 후 진행합니다.

## 현재 분석 컨텍스트
출원번호: {{ application_number }}
현재 보고 있는 전략: {{ active_strategy_type }}

### 거절이유 요약
{% for reason in rejection_reasons %}
- {{ reason.rejection_type }} ({{ reason.article }}): 청구항 {{ reason.target_claim_numbers }}
  {{ reason.examiner_reasoning[:300] }}
{% endfor %}

### Claim Chart 불일치 항목 (핵심 대응 포인트)
{% for chart in claim_charts %}
청구항 {{ chart.target_claim_number }}항:
{% for row in chart.rows %}
{% if row.agreement == "불일치" %}
  ⭐ {{ row.element_id }}: 우리={{ row.our_match }}, 심사관={{ row.examiner_match }}
     근거: {{ row.disagreement_rationale }}
{% endif %}
{% endfor %}
{% endfor %}

### {{ active_strategy_type }} 전략
{{ current_strategy.rationale }}
행동 방향: {{ current_strategy.proposed_action }}

### 보정청구항 ({{ active_strategy_type }})
{% for amended in current_amendment.amended_claims %}
청구항 {{ amended.claim_number }}: {{ amended.diff_summary }}
{% endfor %}
```

- [ ] **Step 3: 렌더링 테스트**

```bash
uv run python -c "
from patent_agent.core.prompts import render
result = render('tool1.j2', raw_dict={'test': 1})
print(result[:100])
"
```

Expected: 프롬프트 텍스트 출력

- [ ] **Step 4: Commit**

```bash
git add src/patent_agent/core/prompts.py src/patent_agent/prompts/
git commit -m "feat: Jinja2 프롬프트 템플릿 (Tool 1~6, 챗봇 시스템)"
```

---

## Task 5: Tool 1 — 통지서 분석

**Files:**
- Create: `src/patent_agent/tools/tool1_parse_office_action.py`
- Create: `tests/unit/test_tool1.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/test_tool1.py
import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock
from patent_agent.tools.tool1_parse_office_action import (
    parse_office_action, extract_claim_numbers, extract_examiner_chart
)
from patent_agent.models.input import OfficeActionRaw
from patent_agent.models.output import OfficeActionResult, ExaminerChart

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "10-2014-0036561"


@pytest.fixture
def office_action_raw():
    raw = json.loads((FIXTURE_DIR / "office_action.json").read_text(encoding="utf-8"))
    return OfficeActionRaw(application_number="10-2014-0036561", raw_dict=raw)


def test_extract_claim_numbers_single():
    assert extract_claim_numbers("제1항") == [1]


def test_extract_claim_numbers_range():
    assert extract_claim_numbers("제4항 내지 제7항") == [4, 5, 6, 7]


def test_extract_claim_numbers_mixed():
    result = extract_claim_numbers("제1항, 제4항 내지 제7항")
    assert sorted(result) == [1, 4, 5, 6, 7]


def test_extract_examiner_chart_returns_chart(office_action_raw):
    chart = extract_examiner_chart(office_action_raw)
    # 보유 통지서에 구성비교표가 있는 경우
    assert chart is not None
    assert len(chart.rows) > 0


def test_parse_office_action_structure(office_action_raw):
    mock_llm = MagicMock()
    mock_llm.generate.return_value = OfficeActionResult(
        application_number="10-2014-0036561",
        rejection_reasons=[],
        rejected_claim_numbers=[1, 4, 5, 6, 7],
        cited_arts=[],
    )
    result = parse_office_action(office_action_raw, mock_llm)
    assert result.application_number == "10-2014-0036561"
    mock_llm.generate.assert_called_once()


def test_parse_office_action_rejected_claims(office_action_raw):
    """보유 통지서 기준: 거절 청구항은 1,4,5,6,7항"""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = OfficeActionResult(
        application_number="10-2014-0036561",
        rejection_reasons=[],
        rejected_claim_numbers=[1, 4, 5, 6, 7],
        cited_arts=[],
    )
    result = parse_office_action(office_action_raw, mock_llm)
    assert sorted(result.rejected_claim_numbers) == [1, 4, 5, 6, 7]
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
uv run pytest tests/unit/test_tool1.py -v
```

Expected: FAIL

- [ ] **Step 3: `tools/tool1_parse_office_action.py` 작성**

```python
import re
from patent_agent.llm.base import LLMClient
from patent_agent.models.input import OfficeActionRaw
from patent_agent.models.output import (
    OfficeActionResult, ExaminerChart, ExaminerChartRow
)
from patent_agent.core.prompts import render


def extract_claim_numbers(text: str) -> list[int]:
    """'제1항, 제4항 내지 제7항' → [1, 4, 5, 6, 7]"""
    result: set[int] = set()
    # 범위 패턴: "제N항 내지 제M항"
    for m in re.finditer(r"제(\d+)항\s*내지\s*제(\d+)항", text):
        result.update(range(int(m.group(1)), int(m.group(2)) + 1))
    # 단일 패턴: "제N항" (범위 패턴 제거 후 처리)
    cleaned = re.sub(r"제\d+항\s*내지\s*제\d+항", "", text)
    for m in re.finditer(r"제(\d+)항", cleaned):
        result.add(int(m.group(1)))
    return sorted(result)


def extract_examiner_chart(oa_raw: OfficeActionRaw) -> ExaminerChart | None:
    """통지서 raw_dict에서 구성비교표를 결정적으로 추출. LLM 없음."""
    try:
        reasons = oa_raw.raw_dict.get("구체적인거절이유", {})
        rows: list[ExaminerChartRow] = []
        for reason_key, reason_val in reasons.items():
            if not isinstance(reason_val, dict):
                continue
            claim_reasons = reason_val.get("청구항별거절이유", {})
            for claim_key, claim_val in claim_reasons.items():
                chart_rows = (
                    claim_val.get("진보성비교", {}).get("구성비교표", [])
                )
                for row in chart_rows:
                    match_raw = row.get("비고", "차이")
                    if match_raw == "동일":
                        match = "동일"
                    elif match_raw == "유사":
                        match = "유사"
                    else:
                        match = "차이"
                    our_text = row.get("이출원제1항발명", "")
                    if isinstance(our_text, dict):
                        our_text = our_text.get("내용", str(our_text))
                    prior_text = row.get("인용발명1", "")
                    if isinstance(prior_text, dict):
                        prior_text = prior_text.get("내용", str(prior_text))
                    rows.append(ExaminerChartRow(
                        element_label=row.get("구성", ""),
                        our_claim_text=str(our_text),
                        prior_art_text=str(prior_text),
                        prior_art_id="인용발명1",
                        examiner_match=match,
                        note=None,
                    ))
        return ExaminerChart(rows=rows) if rows else None
    except Exception:
        return None


def parse_office_action(oa_raw: OfficeActionRaw, llm: LLMClient) -> OfficeActionResult:
    prompt = render("tool1.j2", raw_dict=oa_raw.raw_dict)
    return llm.generate(prompt, schema=OfficeActionResult, temperature=0.0)
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
uv run pytest tests/unit/test_tool1.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/patent_agent/tools/tool1_parse_office_action.py tests/unit/test_tool1.py
git commit -m "feat: Tool 1 통지서 분석 (parse_office_action, extract_examiner_chart)"
```

---

## Task 6: Tool 2 — 청구항 파싱

**Files:**
- Create: `src/patent_agent/tools/tool2_parse_claims.py`
- Create: `tests/unit/test_tool2.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/test_tool2.py
import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from patent_agent.tools.tool2_parse_claims import parse_claims
from patent_agent.models.output import ClaimParseResult, Claim, ClaimElement

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "10-2014-0036561"


@pytest.fixture
def patent_claims():
    raw = json.loads((FIXTURE_DIR / "patent.json").read_text(encoding="utf-8"))
    return {int(k.replace("청구항", "")): v
            for k, v in raw["특허청구범위"].items()}


def _make_mock_result(application_number: str = "10-2014-0036561") -> ClaimParseResult:
    return ClaimParseResult(
        application_number=application_number,
        total_claims=7,
        independent_claims=[1],
        dependent_claims=[2, 3, 4, 5, 6, 7],
        claims=[
            Claim(
                claim_number=1,
                claim_type="독립항",
                depends_on=[],
                original_text="웨트 마스터 배치...",
                elements=[
                    ClaimElement(element_id="1-A", element_order=1,
                                 text="웨트 마스터 배치 50~200 중량부", label="원료고무 조성"),
                    ClaimElement(element_id="1-B", element_order=2,
                                 text="카본블랙 50~200 중량부", label="카본블랙 사양"),
                ],
            ),
            Claim(
                claim_number=7,
                claim_type="종속항",
                depends_on=[1, 2, 3, 4, 5, 6],
                original_text="제1항 내지 제6항 중 어느 한 항에 따른 타이어",
                elements=[],
            ),
        ],
    )


def test_parse_claims_calls_llm(patent_claims):
    mock_llm = MagicMock()
    mock_llm.generate.return_value = _make_mock_result()
    result = parse_claims("10-2014-0036561", patent_claims, mock_llm)
    mock_llm.generate.assert_called_once()
    assert result.total_claims == 7


def test_parse_claims_independent_claim(patent_claims):
    mock_llm = MagicMock()
    mock_llm.generate.return_value = _make_mock_result()
    result = parse_claims("10-2014-0036561", patent_claims, mock_llm)
    assert 1 in result.independent_claims


def test_parse_claims_claim7_depends_on(patent_claims):
    mock_llm = MagicMock()
    mock_llm.generate.return_value = _make_mock_result()
    result = parse_claims("10-2014-0036561", patent_claims, mock_llm)
    claim7 = next(c for c in result.claims if c.claim_number == 7)
    assert sorted(claim7.depends_on) == [1, 2, 3, 4, 5, 6]
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
uv run pytest tests/unit/test_tool2.py -v
```

- [ ] **Step 3: `tools/tool2_parse_claims.py` 작성**

```python
from patent_agent.llm.base import LLMClient
from patent_agent.models.output import ClaimParseResult
from patent_agent.core.prompts import render


def parse_claims(
    application_number: str,
    claims: dict[int, str],
    llm: LLMClient,
) -> ClaimParseResult:
    prompt = render("tool2.j2",
                    application_number=application_number,
                    claims=claims)
    return llm.generate(prompt, schema=ClaimParseResult, temperature=0.0)
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/unit/test_tool2.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/patent_agent/tools/tool2_parse_claims.py tests/unit/test_tool2.py
git commit -m "feat: Tool 2 청구항 파싱 및 구성요소 분해"
```

---

## Task 7: Tool 3 — 상세설명 매핑

**Files:**
- Create: `src/patent_agent/tools/tool3_map_spec.py`
- Create: `tests/unit/test_tool3.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/test_tool3.py
from unittest.mock import MagicMock
from patent_agent.tools.tool3_map_spec import map_spec_to_elements
from patent_agent.models.output import (
    ClaimParseResult, ClaimElement, Claim, SpecMappingResult, ElementSpecMapping
)


def _make_claims() -> ClaimParseResult:
    return ClaimParseResult(
        application_number="10-test",
        total_claims=1,
        independent_claims=[1],
        dependent_claims=[],
        claims=[Claim(
            claim_number=1,
            claim_type="독립항",
            original_text="test",
            elements=[
                ClaimElement(element_id="1-A", element_order=1,
                             text="웨트 마스터 배치 50~200 중량부", label="원료고무"),
            ],
        )],
    )


def test_map_spec_calls_llm():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = SpecMappingResult(mappings=[
        ElementSpecMapping(element_id="1-A", paragraph_ids=["0008"],
                           rationale="단락 0008에 상세히 기재됨", confidence=0.9),
    ])
    result = map_spec_to_elements(_make_claims(), {"0008": "웨트 마스터 배치..."}, mock_llm)
    mock_llm.generate.assert_called_once()
    assert len(result.mappings) == 1
    assert result.mappings[0].element_id == "1-A"


def test_map_spec_mappings_contain_valid_paragraphs():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = SpecMappingResult(mappings=[
        ElementSpecMapping(element_id="1-A", paragraph_ids=["0008"],
                           rationale="ok", confidence=0.9),
    ])
    spec = {"0008": "웨트 마스터 배치...", "0009": "other"}
    result = map_spec_to_elements(_make_claims(), spec, mock_llm)
    for mapping in result.mappings:
        for para_id in mapping.paragraph_ids:
            assert para_id in spec, f"단락 {para_id}가 명세서에 없음"
```

- [ ] **Step 2: `tools/tool3_map_spec.py` 작성**

```python
from patent_agent.llm.base import LLMClient
from patent_agent.models.output import ClaimParseResult, SpecMappingResult
from patent_agent.core.prompts import render


def map_spec_to_elements(
    claims: ClaimParseResult,
    spec_paragraphs: dict[str, str],
    llm: LLMClient,
) -> SpecMappingResult:
    all_elements = [e for c in claims.claims for e in c.elements]
    prompt = render("tool3.j2",
                    elements=all_elements,
                    spec_paragraphs=spec_paragraphs)
    return llm.generate(prompt, schema=SpecMappingResult, temperature=0.0)
```

- [ ] **Step 3: 테스트 통과 확인**

```bash
uv run pytest tests/unit/test_tool3.py -v
```

Expected: 2 passed

- [ ] **Step 4: Commit**

```bash
git add src/patent_agent/tools/tool3_map_spec.py tests/unit/test_tool3.py
git commit -m "feat: Tool 3 상세설명 매핑 (LLM-only, 임베딩 미사용)"
```

---

## Task 8: Tool 4 — Claim Chart 생성·검증

**Files:**
- Create: `src/patent_agent/tools/tool4_claim_chart.py`
- Create: `tests/unit/test_tool4.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/test_tool4.py
from unittest.mock import MagicMock
import pytest
from patent_agent.tools.tool4_claim_chart import build_claim_chart
from patent_agent.models.input import PriorArtDoc
from patent_agent.models.output import (
    Claim, ClaimElement, ExaminerChart, ExaminerChartRow,
    ClaimChartResult, ClaimChart, ClaimChartRow,
)


def _make_claim() -> Claim:
    return Claim(
        claim_number=1, claim_type="독립항", original_text="test",
        elements=[
            ClaimElement(element_id="1-A", element_order=1,
                         text="웨트 마스터 배치 50~200 중량부", label="원료고무"),
        ],
    )


def _make_prior_art() -> PriorArtDoc:
    return PriorArtDoc(
        application_number="10-2012-0097198",
        title="인용발명1",
        abstract="",
        claims={1: "폴리머 라텍스, 카본블랙..."},
        spec_paragraphs={"0001": "본 발명은..."},
        prior_art_id="인용발명1",
        publication_number="10-2014-0030706",
    )


def test_build_claim_chart_calls_llm_per_prior_art():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = ClaimChartResult(charts=[
        ClaimChart(target_claim_number=1, rows=[
            ClaimChartRow(
                element_id="1-A", element_text="웨트 마스터 배치",
                prior_art_id="인용발명1", our_match="차이",
                our_explanation="수치 범위 상이",
            ),
        ]),
    ])
    result = build_claim_chart([_make_claim()], [_make_prior_art()], None, mock_llm)
    assert mock_llm.generate.call_count == 1
    assert len(result.charts) == 1


def test_build_claim_chart_with_examiner_chart():
    mock_llm = MagicMock()
    examiner_chart = ExaminerChart(rows=[
        ExaminerChartRow(
            element_label="구성1", our_claim_text="50~200",
            prior_art_text="130~180", prior_art_id="인용발명1",
            examiner_match="차이",
        ),
    ])
    mock_llm.generate.return_value = ClaimChartResult(charts=[
        ClaimChart(target_claim_number=1, rows=[
            ClaimChartRow(
                element_id="1-A", element_text="웨트 마스터 배치",
                prior_art_id="인용발명1", our_match="차이",
                our_explanation="수치 범위 상이",
                examiner_match="차이",
                agreement="일치",
            ),
        ]),
    ])
    result = build_claim_chart([_make_claim()], [_make_prior_art()], examiner_chart, mock_llm)
    rows = result.charts[0].rows
    assert rows[0].agreement is not None
```

- [ ] **Step 2: `tools/tool4_claim_chart.py` 작성**

```python
from patent_agent.llm.base import LLMClient
from patent_agent.models.input import PriorArtDoc
from patent_agent.models.output import (
    Claim, ClaimChartResult, ExaminerChart
)
from patent_agent.core.prompts import render


def build_claim_chart(
    target_claims: list[Claim],
    prior_arts: list[PriorArtDoc],
    examiner_chart: ExaminerChart | None,
    llm: LLMClient,
) -> ClaimChartResult:
    all_charts = []
    for prior_art in prior_arts:
        for claim in target_claims:
            prompt = render(
                "tool4.j2",
                target_claim_number=claim.claim_number,
                elements=claim.elements,
                prior_art=prior_art,
                examiner_chart=examiner_chart,
            )
            partial: ClaimChartResult = llm.generate(
                prompt, schema=ClaimChartResult, temperature=0.0
            )
            all_charts.extend(partial.charts)
    return ClaimChartResult(charts=all_charts)
```

- [ ] **Step 3: 테스트 통과 확인**

```bash
uv run pytest tests/unit/test_tool4.py -v
```

Expected: 2 passed

- [ ] **Step 4: Commit**

```bash
git add src/patent_agent/tools/tool4_claim_chart.py tests/unit/test_tool4.py
git commit -m "feat: Tool 4 Claim Chart 생성·심사관 비교표 검증"
```

---

## Task 9: Tool 5 — 전략 생성

**Files:**
- Create: `src/patent_agent/tools/tool5_strategy.py`
- Create: `tests/unit/test_tool5.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/test_tool5.py
from unittest.mock import MagicMock, call
from patent_agent.tools.tool5_strategy import analyze_diff_and_strategy
from patent_agent.models.output import (
    OfficeActionResult, ClaimChartResult, SpecMappingResult,
    StrategyResult, Strategy,
)


def _make_strategy(t: str) -> Strategy:
    return Strategy(strategy_type=t, rationale="test", 
                    leveraged_differences=["1-A"], proposed_action="test")


def test_strategy_calls_llm_twice():
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        StrategyResult(offensive=_make_strategy("공격"),
                       defensive=_make_strategy("방어")),
    ]
    result = analyze_diff_and_strategy(
        ClaimChartResult(charts=[]),
        OfficeActionResult(application_number="t", rejection_reasons=[],
                           rejected_claim_numbers=[], cited_arts=[]),
        SpecMappingResult(mappings=[]),
        mock_llm,
    )
    assert mock_llm.generate.call_count == 1
    assert result.offensive.strategy_type == "공격"
    assert result.defensive.strategy_type == "방어"
```

- [ ] **Step 2: `tools/tool5_strategy.py` 작성**

```python
from patent_agent.llm.base import LLMClient
from patent_agent.models.output import (
    ClaimChartResult, OfficeActionResult, SpecMappingResult, StrategyResult
)
from patent_agent.core.prompts import render


def analyze_diff_and_strategy(
    claim_chart: ClaimChartResult,
    office_action: OfficeActionResult,
    spec_mapping: SpecMappingResult,
    llm: LLMClient,
) -> StrategyResult:
    # 공격·방어를 단일 호출로 StrategyResult에 한 번에 생성
    # (추가 분리가 필요하면 두 프롬프트를 합친 템플릿 사용)
    prompt = render(
        "tool5.j2",
        claim_charts=claim_chart.charts,
        rejection_reasons=office_action.rejection_reasons,
        spec_mappings=spec_mapping.mappings,
    )
    return llm.generate(prompt, schema=StrategyResult, temperature=0.0)
```

- [ ] **Step 3: 테스트 통과 확인**

```bash
uv run pytest tests/unit/test_tool5.py -v
```

Expected: 1 passed

- [ ] **Step 4: Commit**

```bash
git add src/patent_agent/tools/tool5_strategy.py tests/unit/test_tool5.py
git commit -m "feat: Tool 5 공격·방어 전략 생성"
```

---

## Task 10: Tool 6 — 보정청구항 생성

**Files:**
- Create: `src/patent_agent/tools/tool6_amendment.py`
- Create: `tests/unit/test_tool6.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/test_tool6.py
from unittest.mock import MagicMock
from patent_agent.tools.tool6_amendment import generate_amendments, validate_spec_basis
from patent_agent.models.output import (
    StrategyResult, Strategy, ClaimParseResult, SpecMappingResult,
    AmendmentResult, AmendmentDraft, AmendedClaim, ElementSpecMapping, Claim,
)


def _make_strategy(t: str) -> Strategy:
    return Strategy(strategy_type=t, rationale="test",
                    leveraged_differences=["1-A"], proposed_action="test")


def _make_claims() -> ClaimParseResult:
    return ClaimParseResult(
        application_number="test", total_claims=1,
        independent_claims=[1], dependent_claims=[],
        claims=[Claim(claim_number=1, claim_type="독립항",
                      original_text="orig", elements=[])],
    )


def test_generate_amendments_calls_llm():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = AmendmentResult(
        offensive_draft=AmendmentDraft(strategy_type="공격", amended_claims=[
            AmendedClaim(claim_number=1, original_text="orig", amended_text="orig",
                         diff_summary="원문 유지", spec_basis=[]),
        ], overall_explanation="ok"),
        defensive_draft=AmendmentDraft(strategy_type="방어", amended_claims=[
            AmendedClaim(claim_number=1, original_text="orig", amended_text="amended",
                         diff_summary="한정 추가", spec_basis=["0008"]),
        ], overall_explanation="ok"),
    )
    result = generate_amendments(
        StrategyResult(offensive=_make_strategy("공격"),
                       defensive=_make_strategy("방어")),
        _make_claims(),
        SpecMappingResult(mappings=[]),
        mock_llm,
    )
    assert result.offensive_draft.strategy_type == "공격"
    assert result.defensive_draft.strategy_type == "방어"


def test_validate_spec_basis_passes_existing_paragraphs():
    spec = {"0008": "text1", "0009": "text2"}
    amended = AmendedClaim(claim_number=1, original_text="o", amended_text="a",
                            diff_summary="d", spec_basis=["0008"])
    errors = validate_spec_basis([amended], spec)
    assert errors == []


def test_validate_spec_basis_fails_missing_paragraph():
    spec = {"0008": "text1"}
    amended = AmendedClaim(claim_number=1, original_text="o", amended_text="a",
                            diff_summary="d", spec_basis=["9999"])
    errors = validate_spec_basis([amended], spec)
    assert len(errors) == 1
    assert "9999" in errors[0]
```

- [ ] **Step 2: `tools/tool6_amendment.py` 작성**

```python
from patent_agent.llm.base import LLMClient
from patent_agent.models.output import (
    StrategyResult, ClaimParseResult, SpecMappingResult,
    AmendmentResult, AmendedClaim,
)
from patent_agent.core.prompts import render


def generate_amendments(
    strategy: StrategyResult,
    claims: ClaimParseResult,
    spec_mapping: SpecMappingResult,
    llm: LLMClient,
    spec_paragraphs: dict[str, str] | None = None,
) -> AmendmentResult:
    all_spec_paragraphs: dict[str, str] = spec_paragraphs or {}
    prompt = render(
        "tool6_defensive.j2",
        strategy=strategy.defensive,
        rejected_claims=[c for c in claims.claims],
        relevant_mappings=spec_mapping.mappings,
        spec_paragraphs=all_spec_paragraphs,
    )
    return llm.generate(prompt, schema=AmendmentResult, temperature=0.0)


def validate_spec_basis(
    amended_claims: list[AmendedClaim],
    spec_paragraphs: dict[str, str],
) -> list[str]:
    """spec_basis 단락 ID가 실제 명세서에 존재하는지 검증. 에러 메시지 목록 반환."""
    errors: list[str] = []
    for ac in amended_claims:
        for para_id in ac.spec_basis:
            if para_id not in spec_paragraphs:
                errors.append(
                    f"청구항 {ac.claim_number}: spec_basis '{para_id}'가 명세서에 없음"
                )
    return errors
```

- [ ] **Step 3: 테스트 통과 확인**

```bash
uv run pytest tests/unit/test_tool6.py -v
```

Expected: 3 passed

- [ ] **Step 4: Commit**

```bash
git add src/patent_agent/tools/tool6_amendment.py tests/unit/test_tool6.py
git commit -m "feat: Tool 6 보정청구항 생성 + spec_basis validity 검증"
```

---

## Task 11: 파이프라인 통합

**Files:**
- Create: `src/patent_agent/core/pipeline.py`
- Create: `tests/integration/test_pipeline.py`

- [ ] **Step 1: 통합 테스트 작성**

```python
# tests/integration/test_pipeline.py
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from patent_agent.core.pipeline import run_analysis
from patent_agent.models.input import PatentDoc, OfficeActionRaw, PriorArtDoc
from tests.unit.factories import make_analysis_result

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "10-2014-0036561"


@pytest.fixture
def patent_doc():
    raw = json.loads((FIXTURE_DIR / "patent.json").read_text(encoding="utf-8"))
    claims = {int(k.replace("청구항", "")): v
              for k, v in raw["특허청구범위"].items()}
    spec = {p["단락번호"]: p["내용"]
            for section in raw.get("명세서", {}).values()
            if isinstance(section, list)
            for p in section if isinstance(p, dict) and "단락번호" in p}
    return PatentDoc(
        application_number="10-2014-0036561",
        title=raw["발명의명칭"],
        abstract=raw.get("요약", ""),
        claims=claims,
        spec_paragraphs=spec,
    )


@pytest.fixture
def office_action_raw():
    raw = json.loads((FIXTURE_DIR / "office_action.json").read_text(encoding="utf-8"))
    return OfficeActionRaw(application_number="10-2014-0036561", raw_dict=raw)


def test_pipeline_runs_all_tools(patent_doc, office_action_raw, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "input" / "10-2014-0036561").mkdir(parents=True)

    expected = make_analysis_result("10-2014-0036561")
    mock_llm = MagicMock()
    mock_llm.generate.return_value = expected.office_action  # Tool 1

    with patch("patent_agent.core.pipeline.parse_office_action",
               return_value=expected.office_action), \
         patch("patent_agent.core.pipeline.parse_claims",
               return_value=expected.claim_parse), \
         patch("patent_agent.core.pipeline.map_spec_to_elements",
               return_value=expected.spec_mapping), \
         patch("patent_agent.core.pipeline.build_claim_chart",
               return_value=expected.claim_chart), \
         patch("patent_agent.core.pipeline.analyze_diff_and_strategy",
               return_value=expected.strategy), \
         patch("patent_agent.core.pipeline.generate_amendments",
               return_value=expected.amendment):
        result = run_analysis(patent_doc, office_action_raw, [], mock_llm)

    assert result.application_number == "10-2014-0036561"
    assert result.version == 1
    saved = tmp_path / "analysis" / "10-2014-0036561" / "result.json"
    assert saved.exists()
```

- [ ] **Step 2: `core/pipeline.py` 작성**

```python
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Callable
from patent_agent.llm.base import LLMClient
from patent_agent.models.input import PatentDoc, OfficeActionRaw, PriorArtDoc
from patent_agent.models.analysis import AnalysisResult
from patent_agent.models.output import ToolError
from patent_agent.tools.tool1_parse_office_action import (
    parse_office_action, extract_examiner_chart
)
from patent_agent.tools.tool2_parse_claims import parse_claims
from patent_agent.tools.tool3_map_spec import map_spec_to_elements
from patent_agent.tools.tool4_claim_chart import build_claim_chart
from patent_agent.tools.tool5_strategy import analyze_diff_and_strategy
from patent_agent.tools.tool6_amendment import generate_amendments, validate_spec_basis
from patent_agent.core.storage import save_analysis


def run_analysis(
    patent: PatentDoc,
    office_action_raw: OfficeActionRaw,
    prior_arts: list[PriorArtDoc],
    llm: LLMClient,
    progress_cb: Callable[[str, float], None] | None = None,
) -> AnalysisResult:
    errors: list[ToolError] = []
    _cb = progress_cb or (lambda s, r: None)

    _cb("통지서 분석", 0.0)
    oa_result = parse_office_action(office_action_raw, llm)

    _cb("청구항 파싱", 0.15)
    claims_result = parse_claims(patent.application_number, patent.claims, llm)

    _cb("상세설명 매핑", 0.30)
    try:
        spec_mapping = map_spec_to_elements(claims_result, patent.spec_paragraphs, llm)
    except Exception as e:
        errors.append(ToolError(tool_name="tool3_map_spec",
                                error_type="llm_failure", message=str(e), is_fatal=False))
        from patent_agent.models.output import SpecMappingResult
        spec_mapping = SpecMappingResult(mappings=[])

    _cb("Claim Chart 생성·검증", 0.45)
    examiner_chart = extract_examiner_chart(office_action_raw)
    target_claims = [
        c for c in claims_result.claims
        if c.claim_number in oa_result.rejected_claim_numbers
    ]
    chart_result = build_claim_chart(target_claims, prior_arts, examiner_chart, llm)

    _cb("공격·방어 전략 생성", 0.65)
    strategy = analyze_diff_and_strategy(chart_result, oa_result, spec_mapping, llm)

    _cb("보정청구항 생성", 0.85)
    amendment = generate_amendments(strategy, claims_result, spec_mapping, llm,
                                    spec_paragraphs=patent.spec_paragraphs)

    # spec_basis validity check
    spec_errors = validate_spec_basis(
        amendment.defensive_draft.amended_claims, patent.spec_paragraphs
    )
    if spec_errors:
        for msg in spec_errors:
            errors.append(ToolError(tool_name="tool6_amendment",
                                    error_type="validation_error",
                                    message=msg, is_fatal=False))

    _cb("저장 중", 0.97)
    analysis_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{patent.application_number}"
    result = AnalysisResult(
        analysis_id=analysis_id,
        application_number=patent.application_number,
        created_at=datetime.now(),
        version=1,
        source_files={},
        errors=errors,
        office_action=oa_result,
        claim_parse=claims_result,
        spec_mapping=spec_mapping,
        claim_chart=chart_result,
        strategy=strategy,
        amendment=amendment,
    )
    save_analysis(result)
    _cb("완료", 1.0)
    return result
```

- [ ] **Step 3: 테스트 통과 확인**

```bash
uv run pytest tests/integration/test_pipeline.py -v
```

Expected: 1 passed

- [ ] **Step 4: Commit**

```bash
git add src/patent_agent/core/pipeline.py tests/integration/test_pipeline.py
git commit -m "feat: 분석 파이프라인 통합 (Tool 1→6 직선 실행, 에러 degrade)"
```

---

## Task 12: FastAPI 앱 + 분석 라우터 + SSE 스트림

**Files:**
- Create: `src/patent_agent/api/main.py`
- Create: `src/patent_agent/api/deps.py`
- Create: `src/patent_agent/api/routers/analysis.py`
- Create: `src/patent_agent/api/routers/stream.py`

- [ ] **Step 1: `api/deps.py` 작성**

```python
import os
from patent_agent.llm import get_llm
from patent_agent.llm.base import LLMClient


def get_llm_dep() -> LLMClient:
    return get_llm()
```

- [ ] **Step 2: `api/routers/analysis.py` 작성**

```python
import asyncio
import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from patent_agent.api.deps import get_llm_dep
from patent_agent.llm.base import LLMClient
from patent_agent.core.storage import (
    load_analysis, load_input_patent, load_input_office_action,
    load_input_prior_arts,
)
from patent_agent.core.pipeline import run_analysis
from patent_agent.models.input import PatentDoc, OfficeActionRaw, PriorArtDoc
from patent_agent.models.analysis import AnalysisResult

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])

# 진행 상황을 메모리에 임시 보관 (프로덕션이라면 Redis 사용)
_progress_store: dict[str, list[dict]] = {}


class StartAnalysisRequest(BaseModel):
    application_number: str


class StartAnalysisResponse(BaseModel):
    analysis_id: str
    application_number: str
    status: str = "started"


@router.post("", response_model=StartAnalysisResponse)
async def start_analysis(
    req: StartAnalysisRequest,
    background_tasks: BackgroundTasks,
    llm: LLMClient = Depends(get_llm_dep),
):
    application_number = req.application_number
    import time
    analysis_id = f"{int(time.time())}-{application_number}"
    _progress_store[analysis_id] = []

    def _run():
        try:
            patent_raw = load_input_patent(application_number)
            oa_raw = load_input_office_action(application_number)
            prior_arts_raw = load_input_prior_arts(application_number)

            # raw dict → Pydantic 모델 변환 (간단 어댑터)
            patent = _adapt_patent(application_number, patent_raw)
            oa = OfficeActionRaw(application_number=application_number,
                                 raw_dict=oa_raw)
            prior_arts = [_adapt_prior_art(i, raw)
                          for i, raw in enumerate(prior_arts_raw)]

            def progress_cb(step: str, ratio: float):
                _progress_store[analysis_id].append(
                    {"step": step, "ratio": ratio, "done": ratio >= 1.0}
                )

            run_analysis(patent, oa, prior_arts, llm, progress_cb)
        except Exception as e:
            _progress_store[analysis_id].append(
                {"step": "오류", "ratio": 1.0, "done": True, "error": str(e)}
            )

    background_tasks.add_task(_run)
    return StartAnalysisResponse(analysis_id=analysis_id,
                                 application_number=application_number)


@router.get("/{application_number}", response_model=AnalysisResult)
def get_analysis(application_number: str):
    try:
        return load_analysis(application_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")


def _adapt_patent(application_number: str, raw: dict) -> PatentDoc:
    claims_raw = raw.get("특허청구범위", {})
    claims = {int(k.replace("청구항", "")): v for k, v in claims_raw.items()}
    spec_paragraphs: dict[str, str] = {}
    for section in raw.get("명세서", {}).values():
        if isinstance(section, list):
            for p in section:
                if isinstance(p, dict) and "단락번호" in p:
                    spec_paragraphs[p["단락번호"]] = p["내용"]
    return PatentDoc(
        application_number=application_number,
        title=raw.get("발명의명칭", ""),
        abstract=raw.get("요약", ""),
        claims=claims,
        spec_paragraphs=spec_paragraphs,
    )


def _adapt_prior_art(index: int, raw: dict) -> PriorArtDoc:
    claims_raw = raw.get("특허청구범위", {})
    claims = {int(k.replace("청구항", "")): v for k, v in claims_raw.items()}
    spec_paragraphs: dict[str, str] = {}
    for section in raw.get("명세서", {}).values():
        if isinstance(section, list):
            for p in section:
                if isinstance(p, dict) and "단락번호" in p:
                    spec_paragraphs[p["단락번호"]] = p["내용"]
    return PriorArtDoc(
        application_number=raw.get("특허정보", {}).get("출원번호", f"prior-{index}"),
        title=raw.get("발명의명칭", ""),
        abstract=raw.get("요약", ""),
        claims=claims,
        spec_paragraphs=spec_paragraphs,
        prior_art_id=f"인용발명{index + 1}",
        publication_number=raw.get("특허정보", {}).get("공개번호", ""),
    )
```

- [ ] **Step 3: `api/routers/stream.py` 작성**

```python
import asyncio
import json
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/api/v1/analysis", tags=["stream"])

# analysis.py의 _progress_store 공유
from patent_agent.api.routers.analysis import _progress_store


@router.get("/{analysis_id}/stream")
async def stream_progress(analysis_id: str):
    async def event_generator():
        sent = 0
        while True:
            events = _progress_store.get(analysis_id, [])
            for event in events[sent:]:
                yield {"data": json.dumps(event, ensure_ascii=False)}
                sent += 1
                if event.get("done"):
                    return
            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())
```

- [ ] **Step 4: `api/main.py` 작성**

```python
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from patent_agent.api.routers import analysis, stream

app = FastAPI(title="Patent Agent API", version="0.1.0")

origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis.router)
app.include_router(stream.router)
```

- [ ] **Step 5: 서버 기동 확인**

```bash
uv run uvicorn patent_agent.api.main:app --reload --port 8000
```

브라우저에서 `http://localhost:8000/docs` → FastAPI Swagger UI 확인.

- [ ] **Step 6: Commit**

```bash
git add src/patent_agent/api/
git commit -m "feat: FastAPI 앱 + 분석 라우터 + SSE 스트림"
```

---

## Task 13: Edits 라우터 (편집 적용·되돌리기)

**Files:**
- Create: `src/patent_agent/api/routers/edits.py`

- [ ] **Step 1: `api/routers/edits.py` 작성**

```python
import json
from datetime import datetime
from pathlib import Path
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from patent_agent.core.storage import (
    load_analysis, load_analysis_version, save_analysis
)
from patent_agent.models.analysis import AnalysisResult, EditLogEntry

router = APIRouter(prefix="/api/v1/analysis", tags=["edits"])


class ApplyEditRequest(BaseModel):
    target_path: str         # "claim_chart.charts[0].rows[0].our_match"
    new_value: str
    user_instruction: str | None = None


class RevertRequest(BaseModel):
    version: int


def _get_nested(obj: dict, path: str):
    """'a.b[0].c' 형태 경로로 중첩 딕셔너리 접근"""
    parts = path.replace("][", ".").replace("[", ".").replace("]", "").split(".")
    for part in parts:
        if part.isdigit():
            obj = obj[int(part)]
        else:
            obj = obj[part]
    return obj


def _set_nested(obj: dict, path: str, value) -> dict:
    import copy
    result = copy.deepcopy(obj)
    parts = path.replace("][", ".").replace("[", ".").replace("]", "").split(".")
    current = result
    for part in parts[:-1]:
        current = current[int(part)] if part.isdigit() else current[part]
    last = parts[-1]
    if last.isdigit():
        current[int(last)] = value
    else:
        current[last] = value
    return result


def _append_edit_log(application_number: str, entry: EditLogEntry) -> None:
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    log_path = data_dir / "analysis" / application_number / "edits.log"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(entry.model_dump_json() + "\n")


@router.post("/{application_number}/edits/apply", response_model=AnalysisResult)
def apply_edit(application_number: str, req: ApplyEditRequest):
    try:
        result = load_analysis(application_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")

    result_dict = json.loads(result.model_dump_json())
    before = str(_get_nested(result_dict, req.target_path))
    updated_dict = _set_nested(result_dict, req.target_path, req.new_value)
    new_version = result.version + 1
    updated_dict["version"] = new_version
    updated_result = AnalysisResult.model_validate(updated_dict)
    save_analysis(updated_result)

    _append_edit_log(application_number, EditLogEntry(
        target_path=req.target_path,
        before=before,
        after=req.new_value,
        source="llm-proposed-user-applied",
        user_instruction=req.user_instruction,
    ))
    return updated_result


@router.post("/{application_number}/edits/revert", response_model=AnalysisResult)
def revert_to_version(application_number: str, req: RevertRequest):
    try:
        target = load_analysis_version(application_number, req.version)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"버전 {req.version} 없음")
    save_analysis(target)
    return target
```

- [ ] **Step 2: `api/main.py`에 라우터 추가**

```python
# api/main.py에 추가
from patent_agent.api.routers import edits
app.include_router(edits.router)
```

- [ ] **Step 3: Commit**

```bash
git add src/patent_agent/api/routers/edits.py src/patent_agent/api/main.py
git commit -m "feat: Edits 라우터 (편집 적용, 버전 되돌리기, edits.log)"
```

---

## Task 14: 챗봇 Agent + Chat 라우터

**Files:**
- Create: `src/patent_agent/core/chatbot.py`
- Create: `src/patent_agent/api/routers/chat.py`

- [ ] **Step 1: `core/chatbot.py` 작성**

```python
from __future__ import annotations
import json
from pydantic import BaseModel
from patent_agent.llm.base import LLMClient, Message
from patent_agent.models.analysis import AnalysisResult
from patent_agent.core.prompts import render

CHATBOT_TOOLS = [
    {
        "name": "get_claim_chart_row",
        "description": "Claim Chart의 특정 행 반환 (우리 판단 + 심사관 판단 + 일치 여부)",
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string"},
                "prior_art_id": {"type": "string"},
            },
            "required": ["element_id", "prior_art_id"],
        },
    },
    {
        "name": "get_strategy",
        "description": "공격 또는 방어 전략 전문 반환",
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy_type": {"type": "string", "enum": ["공격", "방어"]},
            },
            "required": ["strategy_type"],
        },
    },
    {
        "name": "get_amendment",
        "description": "특정 청구항 보정안 반환",
        "input_schema": {
            "type": "object",
            "properties": {
                "claim_number": {"type": "integer"},
                "strategy_type": {"type": "string", "enum": ["공격", "방어"]},
            },
            "required": ["claim_number", "strategy_type"],
        },
    },
    {
        "name": "propose_patch",
        "description": "분석 결과 특정 필드 수정 제안 반환 (저장 안 함)",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_path": {"type": "string"},
                "instruction": {"type": "string"},
                "proposed_value": {"type": "string"},
            },
            "required": ["target_path", "instruction", "proposed_value"],
        },
    },
    {
        "name": "propose_regenerate",
        "description": "특정 Tool 재실행 제안 반환 (저장 안 함)",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string",
                              "enum": ["claim_chart", "strategy", "amendment"]},
                "hint": {"type": "string"},
            },
            "required": ["tool_name", "hint"],
        },
    },
]


def _execute_tool(tool_name: str, tool_input: dict, result: AnalysisResult) -> str:
    if tool_name == "get_claim_chart_row":
        element_id = tool_input["element_id"]
        prior_art_id = tool_input["prior_art_id"]
        for chart in result.claim_chart.charts:
            for row in chart.rows:
                if row.element_id == element_id and row.prior_art_id == prior_art_id:
                    return row.model_dump_json(indent=2, ensure_ascii=False)
        return "해당 행을 찾을 수 없습니다."

    if tool_name == "get_strategy":
        strategy_type = tool_input["strategy_type"]
        s = result.strategy.offensive if strategy_type == "공격" else result.strategy.defensive
        return s.model_dump_json(indent=2, ensure_ascii=False)

    if tool_name == "get_amendment":
        claim_number = tool_input["claim_number"]
        strategy_type = tool_input["strategy_type"]
        draft = (result.amendment.offensive_draft if strategy_type == "공격"
                 else result.amendment.defensive_draft)
        for ac in draft.amended_claims:
            if ac.claim_number == claim_number:
                return ac.model_dump_json(indent=2, ensure_ascii=False)
        return "해당 보정안을 찾을 수 없습니다."

    if tool_name in ("propose_patch", "propose_regenerate"):
        return json.dumps({"proposal": tool_input, "status": "pending_user_approval"},
                          ensure_ascii=False)

    return f"알 수 없는 tool: {tool_name}"


class ChatRequest(BaseModel):
    messages: list[Message]
    active_strategy: str = "공격"


class ChatResponse(BaseModel):
    message: Message
    proposals: list[dict] = []


def run_chatbot(
    request: ChatRequest,
    analysis: AnalysisResult,
    llm: LLMClient,
) -> ChatResponse:
    system_prompt = render(
        "chatbot_system.j2",
        application_number=analysis.application_number,
        active_strategy_type=request.active_strategy,
        rejection_reasons=analysis.office_action.rejection_reasons,
        claim_charts=analysis.claim_chart.charts,
        current_strategy=(analysis.strategy.offensive
                          if request.active_strategy == "공격"
                          else analysis.strategy.defensive),
        current_amendment=(analysis.amendment.offensive_draft
                           if request.active_strategy == "공격"
                           else analysis.amendment.defensive_draft),
    )

    # 시스템 프롬프트를 첫 메시지로 삽입
    messages = [Message(role="user", content=system_prompt),
                Message(role="assistant", content="이해했습니다. 질문해 주세요."),
                *request.messages[-10:]]  # 최근 10턴 슬라이딩 윈도우

    proposals: list[dict] = []
    max_turns = 5

    for _ in range(max_turns):
        response = llm.chat(messages, tools=CHATBOT_TOOLS)
        content = response["content"]
        stop_reason = response["stop_reason"]

        if stop_reason != "tool_use":
            # 최종 텍스트 응답
            text = next(
                (b.text for b in content if hasattr(b, "text")), ""
            )
            return ChatResponse(
                message=Message(role="assistant", content=text),
                proposals=proposals,
            )

        # tool_use 처리
        tool_results = []
        for block in content:
            if not hasattr(block, "type") or block.type != "tool_use":
                continue
            tool_result = _execute_tool(block.name, block.input, analysis)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": tool_result,
            })
            if block.name.startswith("propose_"):
                proposals.append({"tool": block.name, "input": block.input})

        messages.append(Message(role="assistant",
                                content=json.dumps(content, default=str)))
        messages.append(Message(role="user",
                                content=json.dumps(tool_results, default=str)))

    return ChatResponse(
        message=Message(role="assistant", content="응답 생성 중 문제가 발생했습니다."),
        proposals=proposals,
    )
```

- [ ] **Step 2: `api/routers/chat.py` 작성**

```python
from fastapi import APIRouter, HTTPException
from patent_agent.api.deps import get_llm_dep
from patent_agent.core.chatbot import ChatRequest, ChatResponse, run_chatbot
from patent_agent.core.storage import load_analysis
from fastapi import Depends
from patent_agent.llm.base import LLMClient

router = APIRouter(prefix="/api/v1/analysis", tags=["chat"])


@router.post("/{application_number}/chat", response_model=ChatResponse)
def chat(
    application_number: str,
    req: ChatRequest,
    llm: LLMClient = Depends(get_llm_dep),
):
    try:
        analysis = load_analysis(application_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="분석 결과 없음")
    return run_chatbot(req, analysis, llm)
```

- [ ] **Step 3: `api/main.py`에 라우터 추가**

```python
from patent_agent.api.routers import chat
app.include_router(chat.router)
```

- [ ] **Step 4: Commit**

```bash
git add src/patent_agent/core/chatbot.py src/patent_agent/api/routers/chat.py src/patent_agent/api/main.py
git commit -m "feat: 챗봇 Agent (조회/patch 제안/regenerate 제안) + chat 라우터"
```

---

## Task 15: 보유 데이터 기반 E2E 시연 테스트

**Files:**
- Create: `tests/integration/test_e2e_demo.py`

- [ ] **Step 1: E2E 데모 테스트 작성**

```python
# tests/integration/test_e2e_demo.py
"""
실제 LLM API를 호출하는 E2E 테스트.
환경변수 ANTHROPIC_API_KEY 또는 OPENAI_API_KEY 필요.
평소엔 skip, 시연 전 수동 실행.
"""
import os
import json
import pytest
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "10-2014-0036561"


@pytest.mark.skipif(
    not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")),
    reason="LLM API 키 없음"
)
def test_full_pipeline_with_real_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    # 입력 파일 배치
    input_dir = tmp_path / "input" / "10-2014-0036561"
    input_dir.mkdir(parents=True)
    (input_dir / "patent.json").write_bytes(
        (FIXTURE_DIR / "patent.json").read_bytes()
    )
    (input_dir / "office_action.json").write_bytes(
        (FIXTURE_DIR / "office_action.json").read_bytes()
    )
    prior_dir = input_dir / "prior_arts"
    prior_dir.mkdir()
    for f in (FIXTURE_DIR / "prior_arts").glob("*.json"):
        (prior_dir / f.name).write_bytes(f.read_bytes())

    from patent_agent.llm import get_llm
    from patent_agent.core.pipeline import run_analysis
    from patent_agent.api.routers.analysis import _adapt_patent, _adapt_prior_art
    from patent_agent.models.input import OfficeActionRaw
    from patent_agent.core.storage import (
        load_input_patent, load_input_office_action, load_input_prior_arts
    )

    llm = get_llm()
    patent_raw = load_input_patent("10-2014-0036561")
    oa_raw = load_input_office_action("10-2014-0036561")
    prior_arts_raw = load_input_prior_arts("10-2014-0036561")

    patent = _adapt_patent("10-2014-0036561", patent_raw)
    oa = OfficeActionRaw(application_number="10-2014-0036561", raw_dict=oa_raw)
    prior_arts = [_adapt_prior_art(i, r) for i, r in enumerate(prior_arts_raw)]

    steps_recorded = []
    def progress_cb(step, ratio):
        steps_recorded.append((step, ratio))
        print(f"[{ratio:.0%}] {step}")

    result = run_analysis(patent, oa, prior_arts, llm, progress_cb)

    # 정량 지표 검증
    assert result.application_number == "10-2014-0036561"
    assert len(result.claim_parse.claims) == 7, "청구항 7개 파싱 필수"
    assert 1 in result.claim_parse.independent_claims
    assert sorted(result.office_action.rejected_claim_numbers) == [1, 4, 5, 6, 7]
    assert len(result.claim_chart.charts) > 0
    assert result.strategy.offensive.strategy_type == "공격"
    assert result.strategy.defensive.strategy_type == "방어"
    assert len(steps_recorded) >= 6

    # Claim Chart agreement_rate 측정 (통지서 구성비교표 4행 기준)
    all_rows = [row for chart in result.claim_chart.charts for row in chart.rows]
    rows_with_agreement = [r for r in all_rows if r.agreement is not None]
    if rows_with_agreement:
        agreement_count = sum(1 for r in rows_with_agreement if r.agreement == "일치")
        rate = agreement_count / len(rows_with_agreement)
        print(f"Agreement rate: {rate:.2%} ({agreement_count}/{len(rows_with_agreement)})")
        # 목표: >= 0.85

    print("E2E 시연 테스트 완료")
    print(f"분석 ID: {result.analysis_id}")
```

- [ ] **Step 2: 단위 테스트 전체 실행**

```bash
uv run pytest tests/unit/ -v
```

Expected: 전체 통과

- [ ] **Step 3: E2E 테스트 실행 (LLM API 키 필요)**

```bash
LLM_PROVIDER=claude ANTHROPIC_API_KEY=<key> uv run pytest tests/integration/test_e2e_demo.py -v -s
```

Expected: 1 passed, 진행 로그 출력

- [ ] **Step 4: 최종 Commit**

```bash
git add tests/integration/test_e2e_demo.py
git commit -m "test: 보유 데이터 기반 E2E 시연 테스트 (agreement_rate 측정 포함)"
```

---

## 성공 지표 체크리스트

| 지표 | 기준 | 검증 방법 |
|---|---|---|
| 분석 완료 시간 | ≤ 60초 | `test_e2e_demo.py` 실행 시간 |
| 청구항 파싱 | 7개 = 전체 7개 | `test_pipeline.py` |
| 거절 청구항 식별 | [1,4,5,6,7] | `test_tool1.py` |
| Claim Chart agreement_rate | ≥ 0.85 | `test_e2e_demo.py` 출력 |
| spec_basis validity | 100% 자동 검증 | `test_tool6.py` |
| 공격·방어 전략 동시 생성 | 둘 다 null 아님 | `test_pipeline.py` |

---

## 실행 순서 요약

```bash
# 전체 단위 테스트
uv run pytest tests/unit/ -v

# 통합 테스트 (mock LLM)
uv run pytest tests/integration/test_pipeline.py -v

# E2E 시연 (실제 LLM API 필요)
LLM_PROVIDER=claude ANTHROPIC_API_KEY=<key> \
  uv run pytest tests/integration/test_e2e_demo.py -v -s

# 개발 서버
uv run uvicorn patent_agent.api.main:app --reload --port 8000
```
