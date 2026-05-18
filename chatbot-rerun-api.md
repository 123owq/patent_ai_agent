# 챗봇 & 파이프라인 재실행 API 명세

> **Base URL** `http://localhost:8001`  
> **Content-Type** `application/json` (SSE 엔드포인트 제외)  
> 모든 경로는 `/api/v1/analysis/{application_number}` 를 공통 prefix로 가진다.

---

## 목차

1. [전체 아키텍처 흐름](#1-전체-아키텍처-흐름)
2. [챗봇 API](#2-챗봇-api)
   - 2-1. 비스트리밍 챗 (하위 호환)
   - 2-2. 스트리밍 챗 (SSE) ← 프론트엔드 사용
3. [파이프라인 재실행 API](#3-파이프라인-재실행-api)
   - 3-1. 전략 재생성 (Tool 5 → 6)
   - 3-2. 보정청구항 재생성 (Tool 6 단독)
4. [참고: 기존 파이프라인 API](#4-참고-기존-파이프라인-api)
   - 4-1. 분석 시작
   - 4-2. 진행 상황 스트림
   - 4-3. 분석 결과 조회
5. [SSE 이벤트 전체 명세](#5-sse-이벤트-전체-명세)
6. [챗봇 내장 도구 (Chatbot Tools)](#6-챗봇-내장-도구-chatbot-tools)
7. [공통 스키마](#7-공통-스키마)
8. [프롬프트 주입 규칙](#8-프롬프트-주입-규칙)
9. [에러 응답](#9-에러-응답)

---

## 1. 전체 아키텍처 흐름

```
사용자 입력 (챗봇)
        │
        ▼
POST /chat/stream  ──────────────────────────────────────────┐
  SSE: token 이벤트 (텍스트 스트리밍)                          │
  SSE: proposals 이벤트 (LLM이 재실행 판단 시)                 │
        │                                                      │
        │  proposals 이벤트 수신                               │
        ▼                                                      │
프론트엔드: [재생성 실행] 버튼 표시                            │
        │                                                      │
        │  사용자 클릭                                          │
        ▼                                                      │
┌───────────────────────────────────────┐                     │
│  tool_name = "strategy"               │                     │
│    → POST /rerun-strategy             │                     │
│      (Tool 5 → Tool 6 순차 재실행)    │                     │
│                                       │                     │
│  tool_name = "amendment"              │                     │
│    → POST /rerun-amendment            │                     │
│      (Tool 6 단독 재실행)             │                     │
└───────────────────────────────────────┘                     │
        │                                                      │
        ▼                                                      │
응답: AnalysisResult (version +1)                             │
프론트엔드: SWR mutate() → 화면 자동 갱신                     │
                                                              │
     ┌────────────────────────────────────────────────────────┘
     │ (재실행 제안 없는 일반 질문)
     ▼
SSE: done 이벤트 → 챗봇 텍스트 응답만 표시
```

### 파이프라인 Tool 의존 관계

```
Tool 1: 통지서 분석    ──┐
Tool 2: 청구항 파싱    ──┤
Tool 3: 상세설명 매핑  ──┤─→ Tool 4: Claim Chart ──→ Tool 5: 전략 ──→ Tool 6: 보정안
                         │                                │
                         └─────────────────────────────────┘
```

| 재실행 유형 | 재실행 Tool | 재사용 (캐시) |
|---|---|---|
| `rerun-strategy` | Tool 5 → Tool 6 | Tool 1 ~ 4 결과 |
| `rerun-amendment` | Tool 6 | Tool 1 ~ 5 결과 |

---

## 2. 챗봇 API

### 2-1. 비스트리밍 챗 (하위 호환)

```
POST /api/v1/analysis/{application_number}/chat
```

> 단순 Q&A 목적. 스트리밍이 필요 없는 환경에서 사용.

#### Request Body

```json
{
  "messages": [
    { "role": "user", "content": "청구항 1-A 불일치 근거는?" }
  ],
  "active_strategy": "공격"
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `messages` | `Message[]` | ✅ | 대화 이력 (최근 10개 사용) |
| `active_strategy` | `"공격" \| "방어"` | ✅ | 현재 사용자가 선택한 전략 |

#### Response Body

```json
{
  "message": {
    "role": "assistant",
    "content": "구성요소 1-A의 슬러리 농도는 인용발명 대비..."
  },
  "proposals": [
    {
      "tool": "propose_regenerate",
      "input": {
        "tool_name": "amendment",
        "hint": "슬러리 농도 수치 한정 보강. 사용자 원문: '..."
      }
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `message` | `Message` | LLM 응답 메시지 |
| `proposals` | `object[]` | 재실행/수정 제안 목록. 없으면 빈 배열 |

---

### 2-2. 스트리밍 챗 (SSE) ← 프론트엔드 메인 사용

```
POST /api/v1/analysis/{application_number}/chat/stream
Content-Type: application/json
```

> 프론트엔드가 실제로 사용하는 엔드포인트.  
> `@microsoft/fetch-event-source` 로 연결하며, 토큰을 실시간으로 수신한다.

#### Request Body

비스트리밍과 동일.

```json
{
  "messages": [
    { "role": "user", "content": "전략을 방어 중심으로 다시 짜줘" }
  ],
  "active_strategy": "방어"
}
```

#### SSE 이벤트 스트림

이벤트는 순서대로 수신된다.

**① token 이벤트** — 텍스트 토큰 (반복 전송)

```
data: {"type": "token", "content": "알"}
data: {"type": "token", "content": "겠"}
data: {"type": "token", "content": "습"}
...
```

**② proposals 이벤트** — LLM이 재실행 판단 시 1회 전송 (없을 수 있음)

```
data: {
  "type": "proposals",
  "data": [
    {
      "tool": "propose_regenerate",
      "input": {
        "tool_name": "strategy",
        "hint": "방어적 전략을 중심으로 재수립. 현재 불일치 구성요소(1-A, 1-B)를 추가 한정하는 방향으로 강화. 사용자 원문: '전략을 방어 중심으로 다시 짜줘'"
      }
    }
  ]
}
```

| `tool_name` | 의미 | 프론트가 호출할 API |
|---|---|---|
| `"strategy"` | 전략 재생성 제안 | `POST /rerun-strategy` |
| `"amendment"` | 보정안 재생성 제안 | `POST /rerun-amendment` |

**③ done 이벤트** — 스트림 종료 (항상 마지막)

```
data: {"type": "done"}
```

#### 프론트엔드 처리 예시 (TypeScript)

```typescript
fetchEventSource(url, {
  method: 'POST',
  body: JSON.stringify(req),
  onmessage(ev) {
    const data = JSON.parse(ev.data);

    if (data.type === 'token') {
      // 텍스트 누적
      accumulated += data.content;
    }

    if (data.type === 'proposals') {
      // propose_regenerate 이벤트만 필터링
      const rerunProposals = data.data
        .filter(p => p.tool === 'propose_regenerate')
        .map(p => ({
          tool_name: p.input.tool_name,   // "strategy" | "amendment"
          instruction: p.input.hint,      // rerun API에 그대로 전달
        }));
      // → UI에 [실행] 버튼 표시
    }

    if (data.type === 'done') {
      ctrl.abort('done');
    }
  },
});
```

---

## 3. 파이프라인 재실행 API

> 두 엔드포인트 모두 **동기(sync)** 처리. LLM 호출이 포함되므로 응답까지 수십 초 소요 가능.  
> 프론트엔드는 로딩 오버레이를 표시하고 완료 후 `mutate()` 로 화면을 갱신한다.

### 3-1. 전략 재생성 — `POST /rerun-strategy`

```
POST /api/v1/analysis/{application_number}/rerun-strategy
```

**Tool 1~4 결과를 캐시로 유지하고, Tool 5(전략) → Tool 6(보정안) 을 순차 재실행한다.**

#### Request Body

```json
{
  "user_instruction": "방어적 전략을 중심으로 재수립. 현재 불일치 구성요소(1-A, 1-B)를 추가 한정하는 방향으로 강화. 사용자 원문: '전략을 방어 중심으로 다시 짜줘'"
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `user_instruction` | `string` | ✅ | 챗봇 `proposals.input.hint` 값을 그대로 전달. Tool 5 프롬프트의 `## ⚡ 사용자 추가 요청` 블록에 삽입됨 |

#### Response Body

`AnalysisResult` 전체 반환. `version` 이 +1 증가하고 `edit_log` 에 재실행 이력이 추가된다.

```json
{
  "analysis_id": "...",
  "application_number": "10-2014-0036561",
  "version": 3,
  "strategy": { "offensive": {...}, "defensive": {...} },
  "amendment": { "offensive_draft": {...}, "defensive_draft": {...} },
  "edit_log": [
    {
      "timestamp": "2026-05-16T10:30:00",
      "target_path": "strategy+amendment",
      "before": "(이전 전략·보정안)",
      "after": "(재생성)",
      "source": "llm-rerun",
      "user_instruction": "방어적 전략을 중심으로..."
    }
  ]
}
```

#### 내부 실행 순서

```python
# 1. 기존 분석 로드 (Tool 1~4 캐시)
current = load_analysis(application_number)

# 2. Tool 5 재실행 (user_instruction 프롬프트 삽입)
new_strategy = analyze_diff_and_strategy(
    claim_chart=current.claim_chart,     # Tool 4 결과 재사용
    office_action=current.office_action, # Tool 1 결과 재사용
    spec_mapping=current.spec_mapping,   # Tool 3 결과 재사용
    llm=llm,
    user_instruction=req.user_instruction,
)

# 3. Tool 6 재실행 (새 전략 기반)
new_amendment = generate_amendments(
    strategy=new_strategy,               # 새로 생성된 전략
    claims=current.claim_parse,          # Tool 2 결과 재사용
    spec_mapping=current.spec_mapping,
    llm=llm,
    spec_paragraphs=patent.spec_paragraphs,
)

# 4. 저장 (version+1)
save_analysis(updated)
```

---

### 3-2. 보정청구항 재생성 — `POST /rerun-amendment`

```
POST /api/v1/analysis/{application_number}/rerun-amendment
```

**Tool 1~5 결과를 캐시로 유지하고, Tool 6(보정안)만 재실행한다.**

#### Request Body

```json
{
  "user_instruction": "청구항 1의 슬러리 농도(구성요소 1-A)를 수치 범위로 구체적으로 한정하여 인용발명 대비 차별성을 명확히 할 것. 사용자 원문: '청구항 1 슬러리 농도를 수치로 한정해줘'"
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `user_instruction` | `string` | ✅ | Tool 6 프롬프트의 `## ⚡ 사용자 추가 요청` 블록에 삽입됨 |

#### Response Body

`AnalysisResult` 전체 반환. `strategy` 는 그대로이고 `amendment` 만 갱신된다.

```json
{
  "version": 4,
  "strategy": { ... },       // 변경 없음
  "amendment": { ... },      // 새로 생성됨
  "edit_log": [
    {
      "target_path": "amendment",
      "source": "llm-rerun",
      "user_instruction": "청구항 1의 슬러리 농도..."
    }
  ]
}
```

#### 내부 실행 순서

```python
# 1. 기존 분석 로드 (Tool 1~5 캐시)
current = load_analysis(application_number)

# 2. Tool 6만 재실행 (user_instruction 프롬프트 삽입)
new_amendment = generate_amendments(
    strategy=current.strategy,           # Tool 5 결과 재사용
    claims=current.claim_parse,
    spec_mapping=current.spec_mapping,
    llm=llm,
    spec_paragraphs=patent.spec_paragraphs,
    user_instruction=req.user_instruction,
)

# 3. 저장 (version+1)
save_analysis(updated)
```

---

## 4. 참고: 기존 파이프라인 API

### 4-1. 분석 시작

```
POST /api/v1/analysis
```

```json
{ "application_number": "10-2014-0036561" }
```

백그라운드 태스크로 Tool 1→6 전체를 실행한다. 완료 여부는 SSE 스트림으로 확인.

**Response:**

```json
{
  "analysis_id": "1747389600-10-2014-0036561",
  "application_number": "10-2014-0036561",
  "status": "started"
}
```

---

### 4-2. 진행 상황 스트림

```
GET /api/v1/analysis/{analysis_id}/stream
```

SSE 형식. 완료(`done: true`) 수신 시 연결이 자동 종료된다.

```
data: {"step": "통지서 분석", "ratio": 0.0,  "done": false}
data: {"step": "청구항 파싱", "ratio": 0.15, "done": false}
data: {"step": "상세설명 매핑", "ratio": 0.30, "done": false}
data: {"step": "Claim Chart 생성·검증", "ratio": 0.45, "done": false}
data: {"step": "공격·방어 전략 생성", "ratio": 0.65, "done": false}
data: {"step": "보정청구항 생성", "ratio": 0.85, "done": false}
data: {"step": "완료", "ratio": 1.0, "done": true}
```

오류 발생 시:

```
data: {"step": "오류", "ratio": 1.0, "done": true, "error": "...메시지..."}
```

---

### 4-3. 분석 결과 조회

```
GET /api/v1/analysis/{application_number}
```

`AnalysisResult` 전체 반환. `version` 필드로 최신 여부 확인 가능.

---

## 5. SSE 이벤트 전체 명세

### 챗봇 스트림 이벤트 (`/chat/stream`)

| `type` | 발생 조건 | 포함 필드 |
|---|---|---|
| `token` | 텍스트 토큰 수신 시 (반복) | `content: string` |
| `proposals` | LLM이 propose_* 도구 호출 시 (0~1회) | `data: ProposalItem[]` |
| `done` | 스트림 종료 (항상 마지막) | 없음 |

**ProposalItem 구조:**

```typescript
interface ProposalItem {
  tool: "propose_patch" | "propose_regenerate";
  input: {
    // propose_regenerate 인 경우
    tool_name: "strategy" | "amendment";
    hint: string;   // → rerun API의 user_instruction 으로 그대로 사용

    // propose_patch 인 경우
    target_path?: string;
    instruction?: string;
    proposed_value?: string;
  };
}
```

### 파이프라인 진행 스트림 이벤트 (`/{analysis_id}/stream`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `step` | `string` | 현재 실행 중인 단계명 |
| `ratio` | `number` | 진행률 0.0 ~ 1.0 |
| `done` | `boolean` | true 이면 완료 또는 오류 |
| `error` | `string?` | 오류 발생 시에만 존재 |

---

## 6. 챗봇 내장 도구 (Chatbot Tools)

챗봇 LLM이 내부적으로 사용할 수 있는 도구 목록. 직접 HTTP 호출 없이 LLM이 자율적으로 선택한다.

| 도구명 | 용도 | 핵심 입력 |
|---|---|---|
| `get_claim_chart_row` | 특정 구성요소의 Claim Chart 행 조회 | `element_id`, `prior_art_id` |
| `get_strategy` | 공격 또는 방어 전략 전문 반환 | `strategy_type: "공격"\|"방어"` |
| `get_amendment` | 특정 청구항 보정안 반환 | `claim_number`, `strategy_type` |
| `propose_patch` | 분석 결과 특정 필드 수정 제안 | `target_path`, `proposed_value` |
| `propose_regenerate` | **전략/보정안 재실행 제안** ← 핵심 | `tool_name`, `hint` |

#### `propose_regenerate` hint 작성 규칙

시스템 프롬프트(`chatbot_system.j2`)에 명시된 규칙:

1. **사용자 원문 포함 필수** — `사용자 원문: '...'` 형태로 hint 끝에 항상 포함
2. **컨텍스트 보강** — 청구항 번호, 구성요소 ID, 인용발명 ID 등 관련 정보 추가
3. **축약 금지** — 임의 요약 또는 추상화 불가

**예시:**
```
입력:  "청구항 1 슬러리 농도를 수치로 한정해줘"

hint:  "청구항 1의 슬러리 농도(구성요소 1-A)를 수치 범위로 구체적으로
        한정하여 인용발명 대비 차별성을 명확히 할 것.
        사용자 원문: '청구항 1 슬러리 농도를 수치로 한정해줘'"
```

---

## 7. 공통 스키마

### Message

```typescript
interface Message {
  role: "user" | "assistant";
  content: string;
}
```

### AnalysisResult (재실행 API 응답 타입)

```typescript
interface AnalysisResult {
  analysis_id: string;
  application_number: string;
  version: number;              // 재실행마다 +1
  created_at: string;           // ISO 8601
  office_action: OfficeActionResult;   // Tool 1
  claim_parse: ClaimParseResult;       // Tool 2
  spec_mapping: SpecMappingResult;     // Tool 3
  claim_chart: ClaimChartResult;       // Tool 4
  strategy: StrategyResult;            // Tool 5
  amendment: AmendmentResult;          // Tool 6
  edit_log: EditLogEntry[];
  errors: ToolError[];
}
```

### EditLogEntry

```typescript
interface EditLogEntry {
  timestamp: string;             // ISO 8601
  target_path: string;           // "amendment" | "strategy+amendment" | 필드 경로
  before: string;
  after: string;
  source: "user-direct"
        | "llm-proposed-user-applied"
        | "regenerate"
        | "llm-rerun";           // 챗봇 경유 재실행
  user_instruction: string | null;
}
```

### StrategyResult (Tool 5 출력)

```typescript
interface StrategyResult {
  offensive: Strategy;
  defensive: Strategy;
}

interface Strategy {
  strategy_type: "공격" | "방어";
  rationale: string;
  leveraged_differences: string[];   // 활용 구성요소 ID 목록
  proposed_action: string;
}
```

### AmendmentResult (Tool 6 출력)

```typescript
interface AmendmentResult {
  offensive_draft: AmendmentDraft;
  defensive_draft: AmendmentDraft;
}

interface AmendmentDraft {
  strategy_type: "공격" | "방어";
  amended_claims: AmendedClaim[];
  overall_explanation: string;
}

interface AmendedClaim {
  claim_number: number;
  original_text: string;
  amended_text: string;
  diff_summary: string;
  spec_basis: string[];   // 근거 명세서 단락 ID
}
```

---

## 8. 프롬프트 주입 규칙

재실행 시 `user_instruction` 은 각 Tool 프롬프트 템플릿(Jinja2)의 고정 위치에 삽입된다.

### Tool 5 (`tool5.j2`)

```jinja
...Claim Chart 분석 결과 및 거절이유 요약...

{% if user_instruction %}
## ⚡ 사용자 추가 요청 (최우선 반영)
{{ user_instruction }}

{% endif %}
## 공격적 전략 작성 지침
...
```

### Tool 6 (`tool6_offensive.j2`, `tool6_defensive.j2`)

```jinja
...전략 기조 및 원본 청구항...

{% if user_instruction %}
## ⚡ 사용자 추가 요청 (최우선 반영)
{{ user_instruction }}

{% endif %}
## 작성 지침
...
```

> **우선순위:** `## ⚡ 사용자 추가 요청` 블록은 `## 작성 지침` 앞에 위치하여 LLM이 최우선으로 읽도록 설계되었다.

---

## 9. 에러 응답

모든 엔드포인트는 FastAPI 표준 에러 형식을 따른다.

| HTTP 코드 | 발생 조건 | `detail` 예시 |
|---|---|---|
| `404` | `application_number` 에 해당하는 분석 결과 없음 | `"분석 결과 없음"` |
| `404` | 원본 특허 파일 없음 (재실행 시) | `"원본 특허 파일 없음"` |
| `422` | 요청 Body 형식 오류 | Pydantic validation error |
| `500` | LLM 호출 실패 또는 내부 오류 | 오류 메시지 |

```json
{
  "detail": "분석 결과 없음"
}
```

> 재실행 API는 동기 처리이므로 LLM 타임아웃(수십 초)이 발생할 수 있다.  
> 필요 시 백엔드에서 `asyncio.wait_for` 또는 별도 타임아웃 미들웨어 적용을 권장한다.
