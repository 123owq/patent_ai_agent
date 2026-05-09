
---

[프론트엔드 개발용 api 문서](docs/frontend-api-guide.md)

## 개요

```
의견제출통지서 + 자사특허 + 인용문헌
        ↓
   AI 분석 파이프라인 (Tool 1~6)
        ↓
 Claim Chart (심사관 판단 검증)
 공격 전략 ↔ 방어 전략 비교
 보정청구항 초안 자동 생성
        ↓
   챗봇으로 결과 질의·수정 (스트리밍)
```

---

## 빠른 시작

```bash
# 1. 의존성 설치
uv sync --extra dev

# 2. 환경변수 설정
cp .env.example .env   # .env 열어서 API 키 입력

# 3. 서버 실행
uv run uvicorn patent_agent.api.main:app --reload --port 8000
```

Swagger UI (API 직접 테스트): `http://localhost:8000/docs`

---

## 환경변수 (.env)

```bash
LLM_PROVIDER=claude              # claude | openai | recording

# Claude
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_BASE_URL=https://api.anthropic.com
CLAUDE_MODEL=claude-sonnet-4-6

# OpenAI (또는 호환 엔드포인트: Azure, 학교 포털 등)
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1

# recording 모드 전용
RECORDING_REAL_PROVIDER=claude   # 캐시 미스 시 실제로 호출할 provider
CASSETTE_DIR=tests/cassettes     # cassette 파일 저장 경로

DATA_DIR=./data
API_PORT=8000
CORS_ORIGINS=http://localhost:3000
```

커스텀 엔드포인트로 전환할 때는 `*_BASE_URL`만 바꾸면 됩니다.

---

## 입력 데이터 배치

```
data/input/{출원번호}/
├── patent.json          # 자사 특허
├── office_action.json   # 의견제출통지서
└── prior_arts/
    ├── 인용발명1.json
    └── 인용발명2.json
```

---

## 프론트엔드 연동 가이드

### CORS 설정

`.env`의 `CORS_ORIGINS`에 프론트엔드 주소를 추가합니다.

```bash
CORS_ORIGINS=http://localhost:3000,https://your-domain.com
```

### API 기본 주소

```
http://localhost:8000/api/v1
```

---

### 1. 분석 시작

```
POST /api/v1/analysis
Content-Type: application/json

{ "application_number": "10-2014-0036561" }
```

응답:
```json
{
  "analysis_id": "1714300000-10-2014-0036561",
  "application_number": "10-2014-0036561",
  "status": "started"
}
```

`analysis_id`를 받아 진행 상황 스트림을 구독합니다.

---

### 2. 분석 진행 상황 (SSE)

```
GET /api/v1/analysis/{analysis_id}/stream
```

서버가 단계별로 이벤트를 보냅니다:

```
data: {"step": "통지서 분석", "ratio": 0.0, "done": false}
data: {"step": "청구항 파싱", "ratio": 0.15, "done": false}
data: {"step": "Claim Chart 생성·검증", "ratio": 0.45, "done": false}
data: {"step": "공격·방어 전략 생성", "ratio": 0.65, "done": false}
data: {"step": "보정청구항 생성", "ratio": 0.85, "done": false}
data: {"step": "완료", "ratio": 1.0, "done": true}
```

```javascript
const es = new EventSource(
  `/api/v1/analysis/${analysisId}/stream`
)
es.onmessage = (e) => {
  const { step, ratio, done } = JSON.parse(e.data)
  updateProgressBar(ratio)
  if (done) es.close()
}
```

---

### 3. 분석 결과 조회

```
GET /api/v1/analysis/{application_number}
```

전체 `AnalysisResult` JSON을 반환합니다. 주요 필드:

```json
{
  "office_action": { "rejected_claim_numbers": [1,4,5,6,7], ... },
  "claim_parse":   { "claims": [...] },
  "claim_chart":   { "charts": [{ "target_claim_number": 1, "rows": [...] }] },
  "strategy": {
    "offensive": { "rationale": "...", "proposed_action": "..." },
    "defensive": { "rationale": "...", "proposed_action": "..." }
  },
  "amendment": {
    "offensive_draft": { "amended_claims": [...] },
    "defensive_draft": { "amended_claims": [...] }
  }
}
```

공격/방어 토글은 프론트엔드 state만 바꾸면 됩니다 — 추가 API 호출 없음.

---

### 4. 챗봇 (스트리밍)

```
POST /api/v1/analysis/{application_number}/chat/stream
Content-Type: application/json

{
  "messages": [
    { "role": "user", "content": "1-A 구성요소 차이점 설명해줘" }
  ],
  "active_strategy": "공격"
}
```

SSE로 토큰을 실시간 전송합니다:

```
data: {"type": "token", "content": "1-A"}
data: {"type": "token", "content": " 구성요소는"}
data: {"type": "token", "content": " 웨트 마스터 배치..."}
data: {"type": "proposals", "data": [...]}   ← 수정 제안 있을 때만
data: {"type": "done"}
```

```javascript
// fetch + ReadableStream으로 POST SSE 처리
const response = await fetch(
  `/api/v1/analysis/${appNo}/chat/stream`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, active_strategy: '공격' }),
  }
)

const reader = response.body.getReader()
const decoder = new TextDecoder()

while (true) {
  const { done, value } = await reader.read()
  if (done) break

  const lines = decoder.decode(value).split('\n')
  for (const line of lines) {
    if (!line.startsWith('data: ')) continue
    const event = JSON.parse(line.slice(6))

    if (event.type === 'token') appendToken(event.content)
    if (event.type === 'proposals') showProposals(event.data)
    if (event.type === 'done') break
  }
}
```

`active_strategy`를 `"공격"` 또는 `"방어"`로 전달하면 챗봇이 해당 전략 기준으로 답변합니다.

---

### 5. 분석 결과 편집

사용자가 Claim Chart 판정이나 보정청구항을 수정할 때:

```
POST /api/v1/analysis/{application_number}/edits/apply
Content-Type: application/json

{
  "target_path": "claim_chart.charts[0].rows[0].our_match",
  "new_value": "차이",
  "user_instruction": "수치 범위가 실질적으로 다름"
}
```

응답으로 갱신된 `AnalysisResult`(버전+1)를 반환합니다.

버전 되돌리기:

```
POST /api/v1/analysis/{application_number}/edits/revert
Content-Type: application/json

{ "version": 1 }
```

---

### 6. 단계별 조회·재실행·채팅

`step_name` 유효값: `office_action` · `claim_parse` · `spec_mapping` · `claim_chart` · `strategy` · `amendment`

```
GET  /api/v1/analysis/{application_number}/steps/{step_name}
```
해당 단계 결과만 반환합니다.

```
POST /api/v1/analysis/{application_number}/steps/{step_name}/regenerate
```
해당 단계부터 끝까지 재실행합니다. `regen_id`를 반환하며, 기존 스트림 엔드포인트로 진행 상황을 구독합니다.

```json
{ "regen_id": "1714300000-10-2014-0036561", "step_name": "strategy", "status": "started" }
```

```javascript
// 재실행 진행 상황 구독 — 기존 SSE 그대로 사용
const es = new EventSource(`/api/v1/analysis/${regenId}/stream`)
```

```
POST /api/v1/analysis/{application_number}/steps/{step_name}/chat
POST /api/v1/analysis/{application_number}/steps/{step_name}/chat/stream
```
해당 단계 컨텍스트만 참고하는 채팅입니다. 요청/응답 형식은 전체 챗봇과 동일합니다.

---

### 7. 전체 엔드포인트 요약

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/v1/analysis` | 분석 시작 → `analysis_id` 반환 |
| `GET` | `/api/v1/analysis/{id}/stream` | 파이프라인 진행 상황 SSE |
| `GET` | `/api/v1/analysis/{application_number}` | 분석 결과 전체 조회 |
| `GET` | `/api/v1/analysis/{application_number}/prior-art/{id}` | 인용발명 상세 조회 |
| `POST` | `/api/v1/analysis/{id}/chat` | 챗봇 (비스트리밍, 하위 호환) |
| `POST` | `/api/v1/analysis/{id}/chat/stream` | 챗봇 스트리밍 SSE ← 권장 |
| `POST` | `/api/v1/analysis/{id}/edits/apply` | 결과 필드 수정 적용 |
| `POST` | `/api/v1/analysis/{id}/edits/revert` | 이전 버전으로 되돌리기 |
| `GET` | `/api/v1/analysis/{id}/steps/{step_name}` | 단계 결과 조회 |
| `POST` | `/api/v1/analysis/{id}/steps/{step_name}/regenerate` | 해당 단계부터 재실행 |
| `POST` | `/api/v1/analysis/{id}/steps/{step_name}/chat` | 단계 범위 챗봇 |
| `POST` | `/api/v1/analysis/{id}/steps/{step_name}/chat/stream` | 단계 범위 챗봇 스트리밍 |

---

## 테스트

```bash
# 단위 + 통합 테스트 (mock LLM, API 키 불필요)
uv run pytest tests/unit/ tests/integration/test_pipeline.py -v

# E2E 시연 테스트 (실제 LLM API 호출)
uv run pytest tests/integration/test_e2e_demo.py -v -s
```

현재: **24 passed** (단위 22 + 통합 2)

---

## recording 모드 (LLM 캐싱)

파이프라인 전체 실행이 30분 이상 걸리는 문제를 해결하기 위해 **recording 모드**를 지원합니다.

**동작 방식**: LLM에 보내는 프롬프트를 해시해서 `cassettes/` 폴더에서 찾음 → 있으면 즉시 반환, 없으면 실제 LLM 호출 후 저장.

```bash
# 처음 한 번: 실제 LLM 호출하면서 cassette 저장
LLM_PROVIDER=recording RECORDING_REAL_PROVIDER=claude uv run uvicorn patent_agent.api.main:app --reload

# 이후: 캐시 우선 (미스 시에만 실제 LLM 호출)
LLM_PROVIDER=recording uv run uvicorn patent_agent.api.main:app --reload
```

- 파이프라인 tool1~6: 프롬프트가 바뀌지 않으면 항상 캐시 히트 → 즉시 응답
- 챗봇: 새 질문은 실제 LLM 호출, 같은 질문 재시도 시 캐시 히트
- 프롬프트 수정 시: 해시가 달라져 자동으로 새로 LLM 호출 + 저장
- cassette 파일은 `tests/cassettes/*.json`에 저장 (경로는 `CASSETTE_DIR`로 변경 가능)

---

## 분석 파이프라인

```
OfficeActionRaw ──→ Tool 1 ──→ OfficeActionResult  (거절이유·인용발명 추출)
PatentDoc       ──→ Tool 2 ──→ ClaimParseResult    (구성요소 분해)
                    Tool 3 ──→ SpecMappingResult    (명세서 단락 매핑)
PriorArtDocs    ──→ Tool 4 ──→ ClaimChartResult    (심사관 판단 검증)
                    Tool 5 ──→ StrategyResult       (공격 + 방어 동시 생성)
                    Tool 6 ──→ AmendmentResult      (보정청구항 초안)
                              ↓
                         AnalysisResult (JSON 파일 저장, 버전 관리)
```

- Tool 3 실패 시: degrade & continue
- 공격·방어 두 전략은 항상 동시에 생성 — UI 토글 시 LLM 재호출 없음

---

## 프로젝트 구조

```
src/patent_agent/
├── models/          # Pydantic 데이터 모델
├── llm/             # Claude / OpenAI / Recording provider
├── prompts/         # Jinja2 프롬프트 템플릿 (.j2)
├── tools/           # Tool 1~6 순수 함수
├── core/            # pipeline, storage, chatbot, step_chatbot
└── api/
    └── routers/     # analysis, stream, edits, chat, steps
```
