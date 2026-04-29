# 특허 심사대응 AI 플랫폼 — 설계 문서

- **프로젝트명**: 사용자 선택형 공격·방어 전략 기반 보정청구항 자동 생성 AI 플랫폼
- **팀**: 43조 (박성준 PO, 김상철 SM, 김상순, 박채영)
- **작성일**: 2026-04-28
- **버전**: v1.0 (Sprint 1~3 전체 설계)
- **우선 문서**: Product Backlog > 시스템 아키텍처 > guide1.md 순

---

## 1. 아키텍처 개요

### 1.1 계층 구조

```
┌─────────────────────────────────────────────────────────────────┐
│                   Web UI (Next.js, 별도 디렉토리)                  │
│   업로드 │ 분석 리포트 │ 근거 매핑 │ Claim Chart │ 전략 토글 │ 챗봇  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ REST/JSON + SSE
┌──────────────────────────────▼──────────────────────────────────┐
│                       FastAPI Backend (Python, uv)               │
│                                                                  │
│  ┌──────────────────────┐     ┌──────────────────────────────┐  │
│  │  Analysis Pipeline   │     │    Chatbot Agent             │  │
│  │  (결정적, 직선 실행)    │     │  (Claude/OpenAI tool-call)  │  │
│  │                      │     │                              │  │
│  │  Tool 1 통지서분석     │     │  모드 A: 조회               │  │
│  │  Tool 2 청구항파싱     │◀────│  모드 B: patch 제안         │  │
│  │  Tool 3 상세설명매핑   │     │  모드 C: regenerate 제안    │  │
│  │  Tool 4 ClaimChart    │     │                              │  │
│  │  Tool 5 차이·전략      │     │  RAG: AnalysisResult 전문   │  │
│  │  Tool 6 보정청구항     │     │  (공격·방어 동시 생성)        │  │
│  └──────────┬───────────┘     └──────────────────────────────┘  │
│             │                                                    │
│  ┌──────────▼──────────────────────────────────────────────┐    │
│  │  LLM Provider Abstraction                                │    │
│  │     ClaudeProvider  │  OpenAIProvider                   │    │
│  │     LLM_PROVIDER=claude|openai (환경변수 스위칭)          │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Data Layer — 파일시스템 JSON                             │    │
│  │  data/input/{출원번호}/  │  data/analysis/{출원번호}/    │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 핵심 원칙 4가지

**① Tool 1~6 = Pure Python 함수**
- 각 Tool은 `(입력 Pydantic 모델, llm: LLMClient) → 출력 Pydantic 모델` 시그니처.
- 외부 부작용 없음. `pytest`로 독립 단위 테스트 가능.
- guide1.md의 Tool 7 (차수 관리자)는 제외 — 1차 대응 단일 케이스만 처리.

**② 파이프라인은 결정적 직선 실행**
- Tool 1→2→3→4→5→6을 고정 순서로 실행. LLM이 순서를 변경하지 않음.
- "Agent"라는 개념은 챗봇에만 적용.

**③ 챗봇은 분석 전체를 재실행하지 않음**
- 이미 저장된 `AnalysisResult`를 RAG 컨텍스트로 사용.
- 사용자 명시적 요청 시에만 (b) 특정 필드 patch 또는 (c) Tool 1개 regenerate 제안.
- **적용은 항상 UI 버튼이 트리거** — LLM이 직접 저장하지 않음.
- 모든 변경은 `edits.log` 기록, 버전 되돌리기 지원.

**④ LLM Provider Abstraction**
- `LLMClient.generate(prompt, schema=PydanticModel)` 단일 인터페이스.
- `ClaudeProvider` / `OpenAIProvider` 구현체.
- 환경변수 `LLM_PROVIDER=claude|openai`로 스위칭.

---

## 2. 데이터 모델 (Pydantic)

### 2.1 입력 모델

```python
class PatentDoc(BaseModel):
    application_number: str           # "10-2014-0036561"
    title: str
    abstract: str
    claims: dict[int, str]            # {1: "웨트 마스터 배치...", ...}
    spec_paragraphs: dict[str, str]   # {"0001": "본 발명은...", ...}

class PriorArtDoc(PatentDoc):
    prior_art_id: str                 # "인용발명1"
    publication_number: str           # "10-2014-0030706"

class OfficeActionRaw(BaseModel):
    application_number: str
    raw_dict: dict                    # 한국어 키 그대로 보존
```

### 2.2 Tool 1 출력 — 통지서 분석

```python
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
```

### 2.3 Tool 2 출력 — 청구항 파싱·구성요소 분해

```python
class ClaimElement(BaseModel):
    element_id: str           # "1-A", "1-B"
    element_order: int
    text: str
    label: str | None         # 의미 라벨 (LLM 부여)

class Claim(BaseModel):
    claim_number: int
    claim_type: Literal["독립항", "종속항"]
    depends_on: list[int] = []
    preamble: str | None
    original_text: str
    elements: list[ClaimElement]

class ClaimParseResult(BaseModel):
    application_number: str
    total_claims: int
    independent_claims: list[int]
    dependent_claims: list[int]
    claims: list[Claim]
```

### 2.4 Tool 3 출력 — 상세설명 매핑

```python
class ElementSpecMapping(BaseModel):
    element_id: str
    paragraph_ids: list[str]
    rationale: str
    confidence: float

class SpecMappingResult(BaseModel):
    mappings: list[ElementSpecMapping]
```

### 2.5 Tool 4 출력 — Claim Chart (생성·검증)

```python
class ClaimChartRow(BaseModel):
    element_id: str
    element_text: str
    prior_art_id: str
    prior_art_element: str | None
    prior_art_location: str | None

    # 시스템 자체 판단
    our_match: Literal["동일", "유사", "차이"]
    our_explanation: str

    # 심사관 판단 (통지서 구성비교표 있을 때만)
    examiner_match: Literal["동일", "유사", "차이"] | None
    examiner_explanation: str | None

    # 검증 결과
    agreement: Literal["일치", "불일치"] | None
    disagreement_rationale: str | None

class ClaimChart(BaseModel):
    target_claim_number: int
    rows: list[ClaimChartRow]

class ClaimChartResult(BaseModel):
    charts: list[ClaimChart]
```

> **Tool 4의 핵심 가치**: 통지서 구성비교표를 사용자 우리 측에 유리하게 반박할 근거 발굴.
> `agreement=불일치` + `our_match=차이` + `examiner_match=동일` 행 = 공격 전략 핵심 무기.

### 2.6 Tool 5 출력 — 전략 생성

```python
class Strategy(BaseModel):
    strategy_type: Literal["공격", "방어"]
    rationale: str
    leveraged_differences: list[str]   # 활용한 element_id 목록
    proposed_action: str

class StrategyResult(BaseModel):
    offensive: Strategy
    defensive: Strategy
```

### 2.7 Tool 6 출력 — 보정청구항 생성

```python
class AmendedClaim(BaseModel):
    claim_number: int
    original_text: str
    amended_text: str
    diff_summary: str
    spec_basis: list[str]              # 뒷받침 단락 ID

class AmendmentDraft(BaseModel):
    strategy_type: Literal["공격", "방어"]
    amended_claims: list[AmendedClaim]
    overall_explanation: str

class AmendmentResult(BaseModel):
    offensive_draft: AmendmentDraft    # 사용자 토글 A
    defensive_draft: AmendmentDraft    # 사용자 토글 B
```

### 2.8 보조 모델

```python
class ExaminerChart(BaseModel):
    """통지서 구성비교표 — extract_examiner_chart()가 raw_dict에서 결정적으로 추출"""
    rows: list[ExaminerChartRow]

class ExaminerChartRow(BaseModel):
    element_label: str                 # "구성1", "구성2" 등 심사관 표기
    our_claim_text: str                # 이 출원 측 내용
    prior_art_text: str                # 인용발명 측 내용
    prior_art_id: str                  # "인용발명1"
    examiner_match: Literal["동일", "유사", "차이"]
    note: str | None                   # 비고 원문

class ToolError(BaseModel):
    tool_name: str                     # "tool3_map_spec"
    error_type: Literal["llm_failure", "validation_error", "timeout"]
    message: str
    is_fatal: bool                     # False = degrade & continue
```

### 2.9 최종 통합 — AnalysisResult

```python
class AnalysisResult(BaseModel):
    analysis_id: str                   # "20260428-153012-1020140036561"
    application_number: str
    created_at: datetime
    version: int = 1
    source_files: dict[str, str]
    errors: list[ToolError] = []       # 부분 실패 기록

    office_action: OfficeActionResult
    claim_parse: ClaimParseResult
    spec_mapping: SpecMappingResult
    claim_chart: ClaimChartResult
    strategy: StrategyResult
    amendment: AmendmentResult

class EditLogEntry(BaseModel):
    timestamp: datetime
    target_path: str
    before: str
    after: str
    source: Literal["user-direct", "llm-proposed-user-applied", "regenerate"]
    user_instruction: str | None
```

---

## 3. Tool 기능 명세

모든 Tool은 아래 공통 시그니처를 따른다.

```python
def tool_N(*inputs, llm: LLMClient) -> ToolNOutput:
    prompt = render_prompt_template("tool_N.j2", **inputs)
    return llm.generate(prompt, schema=ToolNOutput, temperature=0.0)
```

- 프롬프트는 `prompts/tool_{1..6}.j2` Jinja2 파일로 분리.
- `temperature=0.0` 기본값 (재현성 확보).
- 챗봇만 `temperature=0.3`.

### Tool 1 — `parse_office_action()`
| 항목 | 내용 |
|---|---|
| US | US-10, US-11, US-12 |
| 입력 | `OfficeActionRaw` |
| 출력 | `OfficeActionResult` |
| LLM | 부분 — "제1항, 제4항 내지 제7항" → `list[int]` 파싱, 거절유형 분류 |
| 결정적 변환 | raw_dict 한국어 키 → Pydantic 필드 어댑터 (LLM 없음) |
| 테스트 | `rejected_claim_numbers == [1,4,5,6,7]`, `rejection_reasons[1].rejection_type == "기재불비"` |

### Tool 2 — `parse_claims()`
| 항목 | 내용 |
|---|---|
| US | US-07, US-08 |
| 입력 | `dict[int, str]` (청구항 원문) |
| 출력 | `ClaimParseResult` |
| LLM | 전체 — 구성요소 분해, 종속관계 파싱, element_id 부여, 의미 라벨 |
| 프롬프트 전략 | 보유 patent.json 청구항1을 few-shot seed example로 사용 |
| 테스트 | `total_claims == 7`, `claims[6].depends_on == [1,2,3,4,5,6]` |

### Tool 3 — `map_spec_to_elements()`
| 항목 | 내용 |
|---|---|
| US | US-09 |
| 입력 | `ClaimParseResult` + `dict[str, str]` (단락번호→텍스트) |
| 출력 | `SpecMappingResult` |
| LLM | 전체 — 명세서 단락 전체를 컨텍스트에 넣고 단일 호출로 매핑 (임베딩 미사용) |
| 테스트 | seed 매핑 5건 사람 작성 → `confidence ≥ 0.7` |

### Tool 4 — `build_claim_chart()`
| 항목 | 내용 |
|---|---|
| US | US-13, US-14, US-15, US-18 |
| 입력 | `list[Claim]` (거절 청구항) + `list[PriorArtDoc]` + `ExaminerChart | None` |
| 출력 | `ClaimChartResult` |
| LLM | 전체 — `our_match` 생성, 심사관 비교표와 대조 |
| 핵심 역할 | 심사관 구성비교표가 타당한지 검증. `disagreement` 발굴 = 대응 전략 핵심 입력 |
| ExaminerChart 추출 | `extract_examiner_chart()` — LLM 없는 dict 변환, Tool 4 실행 전 호출 |
| 테스트 | `agreement_rate ≥ 0.85` (보유 통지서 구성비교표 4행 기준) |

### Tool 5 — `analyze_diff_and_strategy()`
| 항목 | 내용 |
|---|---|
| US | US-16, US-17 |
| 입력 | `ClaimChartResult` + `OfficeActionResult` + `SpecMappingResult` |
| 출력 | `StrategyResult` |
| LLM | 2회 — 공격용 프롬프트(`tool5_offensive.j2`) / 방어용(`tool5_defensive.j2`) |
| 공격 신호 | `agreement=불일치` + `our_match=차이` + `examiner_match=동일` rows 우선 활용 |
| 방어 신호 | `our_match=동일/유사` rows + `SpecMapping.paragraph_ids` 뒷받침 확인 |

### Tool 6 — `generate_amendments()`
| 항목 | 내용 |
|---|---|
| US | US-19 |
| 입력 | `StrategyResult` + `ClaimParseResult` + `SpecMappingResult` |
| 출력 | `AmendmentResult` (offensive_draft + defensive_draft) |
| LLM | 2회 — `tool6_offensive.j2` / `tool6_defensive.j2` |
| 공격 안 | ClaimChart `disagreement` 항목이 충분하면 청구항 텍스트 유지 + 의견서 주장. `disagreement` 없으면 LLM이 부분 한정 보정안 생성. (`amended_text == original_text` 가능) |
| 방어 안 | 거절 청구항에 추가 한정. **"최초 명세서 기재 사항 범위 내" 프롬프트 강제** |
| 자동 검증 | `spec_basis` 단락 ID가 실제 명세서에 존재하는지 validity check (LLM 없음) |

---

## 4. 파이프라인 오케스트레이션

### 4.1 실행 흐름

```python
def run_analysis(patent, office_action_raw, prior_arts, llm, progress_cb=None):
    oa_result     = parse_office_action(office_action_raw, llm)        # Tool 1
    claims_result = parse_claims(patent.claims, llm)                   # Tool 2
    spec_mapping  = map_spec_to_elements(claims_result,
                                         patent.spec_paragraphs, llm)  # Tool 3
    examiner_chart = extract_examiner_chart(office_action_raw)          # 결정적 변환
    target_claims  = filter_rejected(claims_result, oa_result)
    chart_result  = build_claim_chart(target_claims, prior_arts,
                                      examiner_chart, llm)              # Tool 4
    strategy      = analyze_diff_and_strategy(chart_result,
                                              oa_result, spec_mapping,
                                              llm)                      # Tool 5 (2회)
    amendment     = generate_amendments(strategy, claims_result,
                                        spec_mapping, llm)              # Tool 6 (2회)
    result = AnalysisResult(...)
    save_analysis(result)
    return result
```

**총 LLM 호출**: 약 10~12회 / 예상 소요 30~60초.

### 4.2 에러 처리 정책

| 단계 실패 | 정책 |
|---|---|
| Tool 1 실패 | 전체 abort |
| Tool 2 실패 | 전체 abort |
| Tool 3 실패 | degrade & continue — `spec_mapping` 빈 결과, 경고 첨부 |
| Tool 4 특정 청구항 실패 | 해당 청구항만 skip, `errors[]` 기록 |
| Tool 5/6 공격·방어 한쪽 실패 | 성공한 쪽만 결과 채우고 실패 쪽은 `null` + `errors[]` |

### 4.3 진행상황 — Server-Sent Events

```
POST /api/v1/analysis          → analysis_id 즉시 반환
GET  /api/v1/analysis/{id}/stream   (SSE)
   data: {"step": "통지서 분석", "ratio": 0.0}
   data: {"step": "청구항 파싱", "ratio": 0.15}
   data: {"step": "상세설명 매핑", "ratio": 0.30}
   data: {"step": "Claim Chart 생성·검증", "ratio": 0.45}
   data: {"step": "공격·방어 전략 생성", "ratio": 0.65}
   data: {"step": "보정청구항 생성", "ratio": 0.85}
   data: {"step": "완료", "ratio": 1.0, "result_url": "/api/v1/analysis/{id}"}
```

### 4.4 사용자 선택형 전략 토글

- 파이프라인이 공격·방어 전략과 보정청구항을 **항상 동시에** 생성.
- UI에서 라디오 버튼으로 토글 → 추가 LLM 호출 없음 (React state만 변경).
- 동시보기 모드: 공격안과 방어안을 좌우 분할 화면에 표시 (US-22).
- 현재 토글 상태는 챗봇 RAG 컨텍스트에 전달 (`active_strategy_type`).

---

## 5. 챗봇 Agent

### 5.1 Tool Catalog

**조회 전용**
- `get_claim_element(element_id)` — 구성요소 원문 + 상세설명 매핑
- `get_claim_chart_row(element_id, prior_art_id)` — 우리 판단 + 심사관 판단 + 일치 여부
- `get_strategy(strategy_type)` — 전략 전문
- `get_amendment(claim_number, strategy_type)` — 보정안
- `get_prior_art_paragraph(prior_art_id, paragraph_id)` — 인용발명 단락 원문

**mutation 제안 전용 (저장 안 함)**
- `propose_patch(target_path, instruction)` → `EditProposal` (diff만 반환)
- `propose_regenerate(tool_name, hint)` → `EditProposal`

**적용은 UI 버튼이 트리거**
- `POST /api/v1/analysis/{id}/edits/apply` — 편집 적용, `result.v{n+1}.json` 생성
- `POST /api/v1/analysis/{id}/edits/revert` — 버전 되돌리기

### 5.2 System Prompt 구조

```
[고정 지시사항]
당신은 특허 심사대응 AI입니다.
분석 결과를 기반으로 IP 담당자의 질문에 답변하고,
필요 시 수정 제안을 제시합니다. 법적 판단을 확정하지 않습니다.

[현재 분석 컨텍스트]
출원번호: {application_number}
현재 보고 있는 전략: {active_strategy_type}
거절이유 요약: {OfficeActionResult 요약}
Claim Chart 불일치 항목: {disagreement rows 전문}
{active_strategy_type} 전략: {Strategy 전문}
보정청구항 ({active_strategy_type}): {AmendmentResult 해당 draft}
```

**토큰 관리**
- 인용발명 명세서 전문은 컨텍스트 미포함 → `get_prior_art_paragraph` tool-call로 필요 시만 로드.
- 대화 이력: 최근 10턴 슬라이딩 윈도우.
- 총 컨텍스트 예상: 5~15K 토큰.

### 5.3 편집 흐름 예시

```
사용자: 방어 전략을 가공오일 한정 말고 카본블랙 한정 방향으로 다시 만들어줘
→ propose_regenerate(tool_name="amendment", hint="카본블랙 요오드흡착가 범위 한정 활용")
→ UI에 "Tool 6 재실행 예정 (방어안)" diff 카드 표시
→ 사용자 [적용] → POST /edits/regenerate → Tool 6 방어안만 재실행 → result.v2.json
```

---

## 6. 프로젝트 구조

### 6.1 디렉토리

```
patent-agent/
├── pyproject.toml
├── uv.lock
├── .python-version          # 3.12
├── .env.example
├── src/patent_agent/
│   ├── models/
│   │   ├── input.py         # PatentDoc, PriorArtDoc, OfficeActionRaw
│   │   ├── output.py        # Tool 1~6 출력 모델
│   │   └── analysis.py      # AnalysisResult, EditLogEntry
│   ├── llm/
│   │   ├── base.py          # LLMClient Protocol
│   │   ├── claude.py        # ClaudeProvider
│   │   ├── openai.py        # OpenAIProvider
│   │   └── __init__.py      # get_llm() factory
│   ├── prompts/             # Jinja2 템플릿
│   │   ├── tool1.j2 ~ tool6_defensive.j2
│   │   └── chatbot_system.j2
│   ├── tools/
│   │   ├── tool1_parse_office_action.py
│   │   ├── tool2_parse_claims.py
│   │   ├── tool3_map_spec.py
│   │   ├── tool4_claim_chart.py
│   │   ├── tool5_strategy.py
│   │   └── tool6_amendment.py
│   ├── core/
│   │   ├── pipeline.py      # run_analysis()
│   │   ├── chatbot.py       # chatbot agent loop
│   │   └── storage.py       # save/load/version AnalysisResult
│   └── api/
│       ├── main.py
│       ├── deps.py
│       └── routers/
│           ├── analysis.py
│           ├── stream.py    # SSE
│           ├── edits.py
│           └── chat.py
├── data/
│   ├── input/10-2014-0036561/
│   │   ├── patent.json
│   │   ├── office_action.json
│   │   └── prior_arts/
│   │       ├── 인용발명1.json
│   │       └── 인용발명2.json
│   └── analysis/10-2014-0036561/
│       ├── result.v1.json
│       ├── result.json      # 최신본
│       └── edits.log
├── tests/
│   ├── fixtures/            # 보유 JSON 복사본
│   ├── unit/                # Tool별 단위 테스트
│   └── integration/         # 파이프라인 E2E
└── web/                     # Next.js (별도 UI 설계)
    └── ...
```

### 6.2 환경변수

```bash
LLM_PROVIDER=claude            # claude | openai
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-6
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1
DATA_DIR=./data
API_PORT=8000
CORS_ORIGINS=http://localhost:3000
```

### 6.3 API 엔드포인트 (UI 팀 계약)

| Method | Path | 역할 |
|---|---|---|
| `POST` | `/api/v1/analysis` | 분석 시작 → `analysis_id` 즉시 반환. body: `{"application_number": "10-2014-0036561"}`. 입력 JSON은 `data/input/{출원번호}/` 디렉토리에 미리 배치되어 있어야 함. |
| `GET` | `/api/v1/analysis/{id}/stream` | 진행상황 SSE |
| `GET` | `/api/v1/analysis/{id}` | 분석 결과 전체 |
| `GET` | `/api/v1/analysis/{id}/claim-chart` | Claim Chart만 |
| `GET` | `/api/v1/analysis/{id}/strategy` | 전략 + 보정청구항 |
| `POST` | `/api/v1/analysis/{id}/chat` | 챗봇 대화 |
| `POST` | `/api/v1/analysis/{id}/edits/apply` | 편집 적용 |
| `POST` | `/api/v1/analysis/{id}/edits/revert` | 버전 되돌리기 |
| `POST` | `/api/v1/analysis/{id}/regenerate` | Tool 재실행 |

---

## 7. Sprint 매핑 & 성공 지표

### 7.1 US ↔ 코드 모듈 매핑

| Sprint | US | 코드 모듈 | 비고 |
|---|---|---|---|
| **S1** | US-01 파일 업로드 | `POST /api/v1/analysis`, `storage.py` | JSON 기본, PDF 보조 |
| | US-02 입력형식 검증 | `models/input.py` Pydantic validation | |
| | US-03 선행특허 자동탐색 | **보류** — `data/input/prior_arts/` 수동 배치 대체 | Could 우선순위 |
| | US-04 관련데이터 저장 | `core/storage.py` | |
| | US-05 텍스트 추출 | `pdfplumber` 래퍼 | 보조 지원 |
| | US-06 문서구간 분리 | Tool 1 전처리 + 입력 어댑터 | |
| **S2** | US-07 청구항 파싱 | `tools/tool2_parse_claims.py` | |
| | US-08 구성요소 분해 | Tool 2 (`ClaimElement`) | |
| | US-09 상세설명 매핑 | `tools/tool3_map_spec.py` | |
| | US-10 거절사유 추출 | `tools/tool1_parse_office_action.py` | |
| | US-11 인용문헌 분석 | Tool 1 (`CitedArtRef`) + 인용발명 로딩 | |
| | US-12 문제 청구항 식별 | Tool 1 (`rejected_claim_numbers`) | |
| | US-13 특허 비교 분석 | `tools/tool4_claim_chart.py` | |
| | US-14 구성요소 매칭 | Tool 4 (`ClaimChartRow.our_match`) | |
| | US-15 차이점 도출 | Tool 4 (`agreement=불일치`) + Tool 5 | |
| **S3** | US-16 공격전략 | `tools/tool5_strategy.py` (offensive) | |
| | US-17 방어전략 | Tool 5 (defensive) | |
| | US-18 Claim Chart 생성 | Tool 4 + `GET /claim-chart` | |
| | US-19 보정청구항 | `tools/tool6_amendment.py` | |
| | US-20 전략결과 생성 | Tool 5+6 + `GET /strategy` | |
| | US-21~23 UI | **별도 UI 설계** | |
| | US-24 챗봇 | `core/chatbot.py` + `POST /chat` | |

### 7.2 성공 지표 (갱신)

| 지표 | 정량 기준 | 측정 방법 |
|---|---|---|
| 분석 시간 | `run_analysis()` ≤ 60초 | 자동 측정 |
| 구성요소 분해 품질 | 사람 검수 통과율 ≥ 80% | 보유 patent.json 청구항1 기준 |
| Claim Chart 판정 | `agreement_rate ≥ 0.85` | 보유 통지서 구성비교표 4행 vs `our_match` |
| Claim Chart 불일치 근거 | 사람 검수 통과율 ≥ 80% | `disagreement_rationale` 품질 |
| 보정청구항 자동 검증 | `spec_basis` validity check 100% | 단락 ID 존재 여부 자동 |
| 보정청구항 품질 | IP 담당자 검수 통과율 ≥ 80% | 사람 검수 |

### 7.3 분업 제안

| 담당 | Sprint 1 | Sprint 2 | Sprint 3 |
|---|---|---|---|
| 박성준 (PO) | 환경세팅, `pyproject.toml`, `pipeline.py` 뼈대 | Tool 5 전략생성 | Tool 6 보정청구항 + 통합 테스트 |
| 김상순 | `models/` 전체, `storage.py` | Tool 1 통지서 분석 | API 엔드포인트 마무리 |
| 김상철 (SM) | `llm/` provider abstraction | Tool 2 청구항파싱 + Tool 3 상세설명매핑 | `core/chatbot.py` |
| 박채영 | 입력 어댑터, PDF 보조 | Tool 4 Claim Chart | UI API 연동 + SSE |

---

## 8. 범위 외 (Won't)

- 실시간 KIPRIS 완전 연동 (US-03 수동 대체)
- 모든 이미지 기반 PDF OCR 완전 보장
- 법적 판단 확정 / 자동 보정서 제출
- 차수 관리 (보정이력) — 1차 대응 단일 케이스만
- 완성형 상용 UI (시연용 수준)
- 모든 기술 분야 특허 일반화
