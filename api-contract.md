# API Contract — 프론트엔드 ↔ 백엔드

> 프론트엔드(`patent-frontend`)가 백엔드(`patent_ai_agent`)에 요청하거나
> 백엔드로부터 수신하는 모든 API 명세를 정리한 문서.
>
> - **백엔드 Base URL**: `http://localhost:8001` (`.env.local` → `NEXT_PUBLIC_API_BASE_URL`)
> - **인증**: 없음 (로컬 개발 전용)
> - **Content-Type**: `application/json` (SSE 제외)
> - **CORS**: 백엔드가 `http://localhost:\d+` 정규식으로 모든 로컬 포트 허용

---

## 목차

1. [분석 시작](#1-분석-시작)
2. [분석 결과 조회](#2-분석-결과-조회)
3. [진행 상황 스트림 (SSE)](#3-진행-상황-스트림-sse)
4. [인용발명 상세 조회](#4-인용발명-상세-조회)
5. [청구항 편집 적용](#5-청구항-편집-적용)
6. [편집 이전 버전으로 복원](#6-편집-이전-버전으로-복원)
7. [챗봇 질의](#7-챗봇-질의)
8. [공통 응답 타입](#8-공통-응답-타입)
9. [전체 API 호출 흐름](#9-전체-api-호출-흐름)
10. [에러 처리](#10-에러-처리)
11. [Mock 모드](#11-mock-모드)
12. [미구현·예약 API](#12-미구현예약-api)

---

## 1. 분석 시작

분석 파이프라인(Tool 1~6)을 백그라운드로 실행시키고 `analysis_id`를 즉시 반환한다.  
실제 결과는 [진행 상황 스트림](#3-진행-상황-스트림-sse)으로 모니터링하고, 완료 후 [분석 결과 조회](#2-분석-결과-조회)로 취득한다.

```
POST /api/v1/analysis
```

### Request Body

```ts
interface StartAnalysisRequest {
  application_number: string;          // 예: "10-2014-0036561"
  patent_file_key?: string | null;     // (미사용) 파일 업로드 확장 예약
  office_action_file_key?: string | null;
  prior_art_file_keys?: string[] | null;
}
```

### Response `200 OK`

```ts
interface StartAnalysisResponse {
  analysis_id: string;          // 예: "1777880470-10-2014-0036561"
  application_number: string;
  status: 'started';
}
```

### 프론트엔드 사용 위치

- `lib/api/analysis.ts` → `startAnalysis()`
- `app/upload/page.tsx` → 분석 시작 버튼 클릭 시 호출, `analysis_id`를 `sessionStorage`에 저장 후 `/progress` 페이지로 이동

---

## 2. 분석 결과 조회

완료된 분석의 전체 결과를 가져온다. 분석이 아직 완료되지 않았으면 `404`를 반환한다.

```
GET /api/v1/analysis/{application_number}
```

### Path Parameter

| 파라미터 | 타입 | 예시 |
|---|---|---|
| `application_number` | `string` (URL 인코딩) | `10-2014-0036561` |

### Response `200 OK`

```ts
interface AnalysisResult {
  analysis_id: string;
  application_number: string;
  version: number;                  // 편집 시 증가
  created_at: string;               // ISO 8601

  office_action: OfficeActionResult;   // Tool 1 결과
  claim_parse: ClaimParseResult;       // Tool 2 결과
  spec_mapping: SpecMappingResult;     // Tool 3 결과
  claim_chart: ClaimChartResult;       // Tool 4 결과
  strategy: StrategyResult;            // Tool 5 결과
  amendment: AmendmentResult;          // Tool 6 결과

  edit_log?: EditLogEntry[];           // 편집 이력 (별도 파일 저장, 선택적)
}
```

### Response `404`

분석 결과 파일(`data/analysis/{application_number}/result.json`)이 없을 때.

### 프론트엔드 사용 위치

- `lib/api/analysis.ts` → `getAnalysis()`
- `lib/providers/AnalysisProvider.tsx` → SWR로 주기적 폴링, 모든 결과 탭에서 공유

---

## 3. 진행 상황 스트림 (SSE)

분석 파이프라인의 실시간 진행률을 Server-Sent Events로 수신한다.

```
GET /api/v1/analysis/{analysis_id}/stream
```

### Path Parameter

| 파라미터 | 타입 | 예시 |
|---|---|---|
| `analysis_id` | `string` | `1777880470-10-2014-0036561` |

### SSE 이벤트 형식

```
data: {"step": "통지서 분석", "ratio": 0.15, "done": false}
data: {"step": "청구항 파싱", "ratio": 0.35, "done": false}
...
data: {"step": "완료", "ratio": 1.0, "done": true}
```

```ts
interface ProgressEvent {
  step: string;           // 현재 단계 이름 (예: "전략 수립")
  ratio: number;          // 0.0 ~ 1.0
  done: boolean;          // true이면 분석 완료
  error?: string | null;  // 오류 발생 시 채워짐
}
```

### 파이프라인 단계

| step | ratio |
|---|---|
| 통지서 분석 | 0.15 |
| 청구항 파싱 | 0.30 |
| 명세서 매핑 | 0.45 |
| Claim Chart | 0.65 |
| 전략 수립 | 0.80 |
| 보정안 생성 | 0.95 |
| 완료 | 1.00 |

### 프론트엔드 사용 위치

- `lib/api/stream.ts` → `subscribeProgress()`
- `@microsoft/fetch-event-source` 라이브러리 사용 (표준 `EventSource` 미사용 — AbortController 지원 필요)
- `app/analysis/[id]/progress/page.tsx` → 진행 화면에서 구독, `done: true` 수신 시 결과 페이지로 이동

---

## 4. 인용발명 상세 조회

분석 요약 화면에서 인용발명 클릭 시 상세 정보를 조회한다.  
백엔드는 `data/input/{application_number}/prior_arts/{cited_art_id}.json` 파일을 읽어 반환한다.

```
GET /api/v1/analysis/{application_number}/prior-art/{cited_art_id}
```

### Path Parameters

| 파라미터 | 타입 | 예시 |
|---|---|---|
| `application_number` | `string` | `10-2014-0036561` |
| `cited_art_id` | `string` | `인용발명1` |

### Response `200 OK`

```ts
interface CitedArtDetail {
  cited_art_id: string;           // 예: "인용발명1"
  document_number: string;        // 공개번호 또는 등록번호
  title: string;                  // 발명의 명칭
  applicant: string;              // 특허권자 명칭
  filing_date: string;            // 출원일자 (예: "2013-05-09")
  abstract: string;               // 발명의 요약
  key_claims: CitedArtClaim[];    // 주요 청구항 (최대 5개)
  relevant_paragraphs: CitedArtParagraph[];  // 관련 명세서 단락 (최대 5개)
}

interface CitedArtClaim {
  claim_number: number;
  text: string;
}

interface CitedArtParagraph {
  paragraph_id: string;   // 예: "0023"
  text: string;
}
```

### Response `404`

`cited_art_id`에 해당하는 파일이 없을 때.

### 프론트엔드 사용 위치

- `lib/api/analysis.ts` → `getCitedArtDetail(applicationNumber, citedArtId)`
- `app/analysis/[id]/(results)/summary/page.tsx` → 인용문헌 행 클릭 시 호출
- `components/summary/CitedArtModal.tsx` → 드로어 패널로 표시

---

## 5. 청구항 편집 적용

사용자 또는 챗봇이 제안한 수정을 분석 결과에 적용한다.  
`target_path`는 점(`.`) 표기법으로 중첩 객체 경로를 지정한다.

```
POST /api/v1/analysis/{application_number}/edits/apply
```

### Path Parameter

| 파라미터 | 타입 | 예시 |
|---|---|---|
| `application_number` | `string` | `10-2014-0036561` |

### Request Body

```ts
interface ApplyEditRequest {
  target_path: string;              // 예: "amendment.defensive_draft.amended_claims.0.amended_text"
  new_value: string;                // 교체할 새 값
  user_instruction?: string | null; // 수정 이유 (선택)
}
```

### Response `200 OK`

수정이 반영된 `AnalysisResult` 전체 (버전 +1 증가).

### Response `404`

분석 결과가 없을 때.

### 프론트엔드 사용 위치

- `lib/api/edits.ts` → `applyEdit()`
- 챗봇 `EditProposal` 수락 시 호출

---

## 6. 편집 이전 버전으로 복원

지정한 버전으로 분석 결과를 롤백한다.

```
POST /api/v1/analysis/{application_number}/edits/revert
```

### Path Parameter

| 파라미터 | 타입 | 예시 |
|---|---|---|
| `application_number` | `string` | `10-2014-0036561` |

### Request Body

```ts
interface RevertEditRequest {
  version: number;   // 복원 대상 버전 번호
}
```

### Response `200 OK`

복원된 버전의 `AnalysisResult` 전체.

### Response `404`

해당 버전 파일(`result.v{n}.json`)이 없을 때.

### 프론트엔드 사용 위치

- `lib/api/edits.ts` → `revertEdit()`

---

## 7. 챗봇 질의

분석 결과를 컨텍스트로 활용하는 AI 챗봇에 메시지를 전송한다.

```
POST /api/v1/analysis/{application_number}/chat
```

### Path Parameter

| 파라미터 | 타입 | 예시 |
|---|---|---|
| `application_number` | `string` | `10-2014-0036561` |

### Request Body

```ts
interface ChatRequest {
  messages: Message[];              // 전체 대화 이력 (role: user | assistant)
  active_strategy: '공격' | '방어'; // 현재 활성 전략 탭
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
}
```

### Response `200 OK`

```ts
interface ChatResponse {
  message: Message;           // 챗봇 응답 메시지
  proposals: EditProposal[];  // 수정 제안 목록 (없으면 빈 배열)
}

interface EditProposal {
  target_path: string;   // 수정 대상 경로 (편집 API의 target_path와 동일 형식)
  new_value: string;     // 제안하는 새 값
  reason: string;        // 제안 근거
}
```

> **참고**: 스트리밍 버전(`POST /{application_number}/chat/stream`)도 백엔드에 존재하나
> 현재 프론트엔드는 비스트리밍 엔드포인트만 사용한다.

### 프론트엔드 사용 위치

- `lib/api/chat.ts` → `chat()`
- `components/chatbot/ChatbotFab.tsx` 및 챗봇 패널 컴포넌트

---

## 8. 공통 응답 타입

### AnalysisResult 세부 구조

```
AnalysisResult
├── office_action: OfficeActionResult      (Tool 1)
│   ├── application_number
│   ├── rejection_reasons: RejectionReason[]
│   │   ├── article                        예: "특허법 제29조 제2항"
│   │   ├── rejection_type                 '진보성' | '신규성' | '기재불비' | '기타'
│   │   ├── target_claim_numbers: number[]
│   │   ├── cited_art_ids: string[]
│   │   └── examiner_reasoning
│   ├── rejected_claim_numbers: number[]
│   ├── cited_arts: CitedArtRef[]
│   │   ├── cited_art_id                   예: "인용발명1"
│   │   └── document_number
│   └── examiner_chart?: ExaminerChartRow[]  (통지서에 구성비교표 있을 때만)
│
├── claim_parse: ClaimParseResult          (Tool 2)
│   ├── application_number
│   ├── total_claims
│   ├── independent_claims: number[]
│   ├── dependent_claims: number[]
│   └── claims: Claim[]
│       ├── claim_number
│       ├── claim_type                     '독립항' | '종속항'
│       ├── depends_on: number[]
│       ├── preamble: string | null
│       ├── original_text
│       └── elements: ClaimElement[]
│           ├── element_id                 예: "1-A", "1-B"
│           ├── element_order
│           ├── text
│           └── label: string | null
│
├── spec_mapping: SpecMappingResult        (Tool 3)
│   └── mappings: ElementSpecMapping[]
│       ├── element_id
│       ├── paragraph_ids: string[]        예: ["0023", "0031"]
│       ├── rationale
│       └── confidence                     0.0 ~ 1.0
│
├── claim_chart: ClaimChartResult          (Tool 4)
│   └── charts: ClaimChart[]
│       ├── target_claim_number
│       └── rows: ClaimChartRow[]
│           ├── element_id
│           ├── element_text
│           ├── prior_art_id
│           ├── prior_art_element: string | null
│           ├── prior_art_location: string | null
│           ├── our_match                  '동일' | '유사' | '차이'
│           ├── our_explanation
│           ├── examiner_match: Match | null
│           ├── examiner_explanation: string | null
│           ├── agreement: '일치' | '불일치' | null
│           └── disagreement_rationale: string | null
│
├── strategy: StrategyResult               (Tool 5)
│   ├── offensive: Strategy
│   └── defensive: Strategy
│       ├── strategy_type                  '공격' | '방어'
│       ├── rationale
│       ├── leveraged_differences: string[]  element_id 참조
│       └── proposed_action
│
└── amendment: AmendmentResult             (Tool 6)
    ├── offensive_draft: AmendmentDraft
    └── defensive_draft: AmendmentDraft
        ├── strategy_type
        ├── overall_explanation
        └── amended_claims: AmendedClaim[]
            ├── claim_number
            ├── original_text
            ├── amended_text: string | null
            ├── diff_summary
            └── spec_basis: string[]
```

### ToolError

```ts
interface ToolError {
  tool_name: string;
  error_type: 'llm_failure' | 'validation_error' | 'timeout';
  message: string;
  is_fatal: boolean;
}
```

---

---

## 9. 전체 API 호출 흐름

사용자가 업로드 화면에서 분석을 시작해 결과를 확인하기까지의 순서.

```
[사용자]           [프론트엔드]                      [백엔드]
   │                    │                               │
   │ 출원번호 입력 후     │                               │
   │ "분석 시작" 클릭    │                               │
   │──────────────────>│                               │
   │                   │── POST /api/v1/analysis ─────>│
   │                   │<── { analysis_id, status }  ──│
   │                   │                               │ (백그라운드 파이프라인 시작)
   │                   │  /progress 페이지 이동         │
   │                   │                               │
   │                   │── GET /api/v1/analysis        │
   │                   │       /{analysis_id}/stream ─>│ (SSE 구독)
   │                   │<── data: {step, ratio, done} ─│  ×반복
   │  진행바 업데이트 <──│                               │
   │                   │         (done: true 수신)      │
   │                   │                               │
   │                   │── GET /api/v1/analysis        │
   │                   │       /{application_number} ─>│
   │                   │<── AnalysisResult ────────────│
   │                   │  결과 페이지(/summary)로 이동  │
   │  결과 화면 표시 <──│                               │
   │                   │                               │
   │ 인용발명 클릭      │                               │
   │──────────────────>│                               │
   │                   │── GET /api/v1/analysis        │
   │                   │   /{app_num}/prior-art/{id} ─>│
   │                   │<── CitedArtDetail ────────────│
   │  상세 모달 표시 <──│                               │
   │                   │                               │
   │ 챗봇에 질문       │                               │
   │──────────────────>│                               │
   │                   │── POST /api/v1/analysis       │
   │                   │       /{app_num}/chat ────────>│
   │                   │<── { message, proposals } ────│
   │  챗봇 응답 표시 <──│                               │
   │                   │                               │
   │ 수정 제안 수락     │                               │
   │──────────────────>│                               │
   │                   │── POST /api/v1/analysis       │
   │                   │   /{app_num}/edits/apply ─────>│
   │                   │<── AnalysisResult (version+1)─│
   │  화면 갱신 <───────│                               │
```

### 페이지별 사용 API 요약

| 페이지 | 경로 | 사용 API |
|---|---|---|
| 업로드 | `/upload` | `POST /api/v1/analysis` |
| 진행 | `/analysis/{id}/progress` | `GET /api/v1/analysis/{id}/stream` (SSE) |
| 분석 요약 | `/analysis/{id}/summary` | `GET /api/v1/analysis/{id}` (SWR 폴링)<br>`GET /api/v1/analysis/{id}/prior-art/{art_id}` |
| Claim Chart | `/analysis/{id}/chart` | `GET /api/v1/analysis/{id}` (캐시 공유) |
| 전략 | `/analysis/{id}/strategy` | `GET /api/v1/analysis/{id}` (캐시 공유) |
| 보정청구항 | `/analysis/{id}/amendments` | `GET /api/v1/analysis/{id}` (캐시 공유)<br>`POST /api/v1/analysis/{id}/edits/apply` |
| 챗봇 (FAB) | 모든 결과 페이지 | `POST /api/v1/analysis/{id}/chat`<br>`POST /api/v1/analysis/{id}/edits/apply` |

---

## 10. 에러 처리

### HTTP 상태 코드

| 코드 | 의미 | 주요 발생 엔드포인트 |
|---|---|---|
| `200 OK` | 정상 | 모든 엔드포인트 |
| `404 Not Found` | 분석 결과 없음 / 인용발명 파일 없음 | `GET /analysis/{id}`, `GET /prior-art/{id}`, `POST /edits/*`, `POST /chat` |
| `422 Unprocessable Entity` | Request Body 형식 오류 (Pydantic 검증 실패) | 모든 POST 엔드포인트 |
| `500 Internal Server Error` | 파이프라인 예외 또는 LLM 호출 실패 | `GET /stream` (SSE 오류 이벤트로도 전달) |

### 프론트엔드 에러 클래스

`lib/api/client.ts`에 정의된 커스텀 에러 클래스.

```ts
class ApiError extends Error {
  status: number;    // HTTP 상태 코드
  // message: string — 서버 응답 본문 또는 statusText
}

class TimeoutError extends Error {
  // 기본 타임아웃: 30,000ms
  // message: "Request timed out after 30000ms"
}
```

### SSE 오류 이벤트

분석 중 백엔드 파이프라인이 실패하면 SSE 스트림에 오류 이벤트가 전송된다.

```json
{ "step": "오류", "ratio": 1.0, "done": true, "error": "LLM 응답 파싱 실패" }
```

프론트엔드는 `done: true` + `error` 필드가 있으면 에러 상태로 처리한다.

### ToolError (분석 결과 내 에러)

파이프라인 일부 Tool이 실패해도 전체가 중단되지 않을 경우, `AnalysisResult.errors` 배열에 기록된다.

```ts
interface ToolError {
  tool_name: string;
  error_type: 'llm_failure' | 'validation_error' | 'timeout';
  message: string;
  is_fatal: boolean;   // true면 해당 Tool 결과가 없음
}
```

---

## 11. Mock 모드

`NEXT_PUBLIC_USE_MOCK=true` 환경변수 설정 시 백엔드 없이 프론트엔드만 단독으로 실행된다.

### 동작 원리

```
lib/api/index.ts
  config.useMock === true
    → mockApi (lib/mock/handlers.ts) 사용
  config.useMock === false
    → realApi (lib/api/*.ts) 사용
```

`ApiSurface` 인터페이스로 두 구현이 동일한 시그니처를 갖도록 강제한다.

```ts
// lib/api/index.ts
export interface ApiSurface {
  startAnalysis:      (req: StartAnalysisRequest)          => Promise<StartAnalysisResponse>;
  getAnalysis:        (applicationNumber: string)           => Promise<AnalysisResult>;
  subscribeProgress:  (analysisId: string, cbs: StreamCallbacks) => () => void;
  applyEdit:          (appNum: string, req: ApplyEditRequest) => Promise<AnalysisResult>;
  revertEdit:         (appNum: string, req: RevertEditRequest) => Promise<AnalysisResult>;
  chat:               (appNum: string, req: ChatRequest)     => Promise<ChatResponse>;
  getCitedArtDetail:  (appNum: string, citedArtId: string)  => Promise<CitedArtDetail>;
}
```

### Mock 데이터 위치

| 파일 | 역할 |
|---|---|
| `lib/mock/data.ts` | `MOCK_ANALYSIS` (AnalysisResult 전체), `MOCK_CITED_ART_DETAILS` |
| `lib/mock/handlers.ts` | API 함수 구현 (지연 시뮬레이션 포함, 200~800ms) |
| `lib/mock/stream-simulator.ts` | SSE 진행 이벤트 시뮬레이션 |

### Mock vs Real 차이점

| 항목 | Mock | Real |
|---|---|---|
| 업로드 화면 초기값 | 데모 파일 4개 + 출원번호 자동입력 | 빈 상태 |
| 분석 소요 시간 | ~6초 (시뮬레이션) | 실제 LLM 처리 시간 (30~120초) |
| `AmendedClaim.is_same` | 지원 (diff 토큰 포함) | 미지원 (`amended_text`로 판단) |
| `AmendedClaim.diff` | diff 토큰 배열 반환 | 미반환 |
| `AnalysisResult.edit_log` | 배열 포함 | 별도 파일 저장, 미포함 |
| 챗봇 응답 | 고정 템플릿 응답 | 실제 LLM 응답 |

### Mock 모드 실행

```bash
# package.json 스크립트
npm run dev:mock   # NEXT_PUBLIC_USE_MOCK=true, 포트 3000
npm run dev:real   # NEXT_PUBLIC_USE_MOCK=false, 백엔드 http://localhost:8001 연결
```

---

## 12. 미구현·예약 API

백엔드에는 존재하지만 현재 프론트엔드에서 사용하지 않는 엔드포인트.

### 챗봇 스트리밍

```
POST /api/v1/analysis/{application_number}/chat/stream
```

응답이 SSE 형식으로 토큰 단위 실시간 전송. 현재 프론트엔드는 비스트리밍 `/chat`만 사용.

```
data: {"type": "token",     "content": "이 청구항은..."}
data: {"type": "proposals", "data": [{target_path, new_value, reason}]}
data: {"type": "done"}
```

### 파일 직접 업로드 (예약)

`StartAnalysisRequest`에 `patent_file_key`, `office_action_file_key`, `prior_art_file_keys` 필드가 예약되어 있으나 현재 백엔드는 `DATA_DIR` 파일 시스템에서 직접 읽는다. 향후 멀티파트 파일 업로드 지원 시 사용 예정.

---

## 환경 설정

| 변수 | 위치 | 기본값 | 설명 |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `frontend/.env.local` | `http://localhost:8001` | 백엔드 주소 |
| `NEXT_PUBLIC_USE_MOCK` | `frontend/.env.local` | `false` | `true`이면 실제 API 대신 Mock 사용 |
| `API_PORT` | `backend/.env` | `8001` | 백엔드 포트 |
| `CORS_ORIGINS` | `backend/.env` | (정규식으로 대체) | localhost 전체 허용 |
| `DATA_DIR` | `backend/.env` | `./data` | 입력/분석 파일 루트 경로 |

## 데이터 디렉토리 구조

```
backend/data/
├── input/
│   └── {application_number}/
│       ├── patent.json          ← 출원 특허 원문
│       ├── office_action.json   ← 거절이유통지서
│       └── prior_arts/
│           ├── 인용발명1.json
│           └── 인용발명2.json
└── analysis/
    └── {application_number}/
        ├── result.json          ← 최신 분석 결과
        ├── result.v1.json       ← 버전별 스냅샷
        └── edits.log            ← 편집 이력 (JSONL)
```
