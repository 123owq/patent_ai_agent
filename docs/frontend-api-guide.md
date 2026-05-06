# Patent Agent API

**Base URL:** `http://localhost:8000`  
<!-- **Swagger:** `http://localhost:8000/docs` -->

---

## 용어

| 용어 | 설명 |
|------|------|
| `application_number` | 특허 출원번호. 조회·편집·챗봇 모두 이 값 사용 |
| `analysis_id` | 진행률 SSE 전용 임시 ID. 스트림 연결에만 사용 |
| `active_strategy` | `"공격"` \| `"방어"` |
| `proposals` | 챗봇이 제안만 하고 저장 안 한 수정안. 수락 시 `/edits/apply` 호출 |

---

## 호출 순서 (순서 지켜야함)

```
POST   /api/v1/analysis                                   → analysis_id 받기
GET    /api/v1/analysis/{analysis_id}/stream              → SSE 진행률, done:true 시 종료
GET    /api/v1/analysis/{application_number}              → 분석 결과 조회
POST   /api/v1/analysis/{application_number}/chat/stream  → 챗봇 (SSE)
POST   /api/v1/analysis/{application_number}/edits/apply  → 결과 수정
POST   /api/v1/analysis/{application_number}/edits/revert → 버전 되돌리기
```

---

## API

### `POST /api/v1/analysis`

Tool 1~6 전체를 백그라운드에서 순차 실행. 즉시 반환.

**요청**
```json
{ "application_number": "10-2023-0001234" }
```

**응답**
```json
{
  "analysis_id": "1746518400-10-2023-0001234",
  "application_number": "10-2023-0001234",
  "status": "started"
}
```

---

### `GET /api/v1/analysis/{analysis_id}/stream` — SSE

진행률 스트림. GET이므로 `EventSource` 사용 가능.

**이벤트**
```jsonc
{ "step": "Claim Chart 생성 중", "ratio": 0.5, "done": false }
{ "step": "완료", "ratio": 1.0, "done": true }   // done:true → 연결 종료
// 오류 시: { "step": "오류", "ratio": 1.0, "done": true, "error": "..." }
```

```javascript
const es = new EventSource(`/api/v1/analysis/${analysisId}/stream`);
es.onmessage = (e) => {
  const { step, ratio, done, error } = JSON.parse(e.data);
  if (done) { es.close(); error ? onError(error) : onComplete(); }
};
```

---

### `GET /api/v1/analysis/{application_number}`

**응답 — `AnalysisResult`**
```
{
  analysis_id, application_number, created_at, version,
  errors[],          // 비어있지 않으면 부분 실패 (아래 참고)
  office_action {
    rejection_reasons[{ article, rejection_type, target_claim_numbers[], cited_art_ids[], examiner_reasoning }]
    cited_arts[{ cited_art_id, document_number }]
  }
  claim_parse {
    claims[{ claim_number, claim_type, original_text, elements[{ element_id, element_order, text }] }]
  }
  claim_chart {
    charts[{
      target_claim_number,
      rows[{ element_id, element_text, prior_art_id,
             our_match, our_explanation,
             examiner_match, examiner_explanation,
             agreement, disagreement_rationale }]
    }]
  }
  strategy {
    offensive { rationale, leveraged_differences[], proposed_action }
    defensive { ... }
  }
  amendment {
    offensive_draft {
      overall_explanation,
      amended_claims[{ claim_number, original_text, amended_text, diff_summary, spec_basis[] }]
    }
    defensive_draft { ... }
  }
}
```

`our_match` / `examiner_match`: `"동일"` | `"유사"` | `"차이"`  
`agreement`: `"일치"` | `"불일치"` | `null`  
`rejection_type`: `"진보성"` | `"신규성"` | `"기재불비"` | `"기타"`

---

### `POST /api/v1/analysis/{application_number}/chat/stream` — SSE

POST라서 `EventSource` 불가. `fetch + ReadableStream` 사용.

**요청**
```json
{
  "messages": [
    { "role": "user", "content": "청구항 1 차이점 설명해줘" }
  ],
  "active_strategy": "공격"
}
```

- `messages`: 대화 히스토리 전체를 매번 전송. 서버는 마지막 10개만 처리
- 서버는 stateless — 히스토리 저장 없음, 프론트가 직접 누적 관리
- `active_strategy` 변경 시 히스토리 초기화 불필요

**이벤트**
```jsonc
{ "type": "token", "content": "텍스트 조각..." }
{ "type": "proposals", "data": [...] }   // 수정 제안 시에만
{ "type": "done" }
```

```javascript
const res = await fetch(`/api/v1/analysis/${appNum}/chat/stream`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ messages, active_strategy: "공격" }),
});
const reader = res.body.getReader();
const decoder = new TextDecoder();
let buffer = "";
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split("\n"); buffer = lines.pop();
  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    const ev = JSON.parse(line.slice(6));
    if (ev.type === "token") appendText(ev.content);
    if (ev.type === "proposals") handleProposals(ev.data);
    if (ev.type === "done") break;
  }
}
```

**proposals 이벤트 구조**
```jsonc
[
  {
    "tool": "propose_patch",
    "input": { "target_path": "amendment.offensive_draft.amended_claims[0].amended_text",
               "instruction": "...", "proposed_value": "..." }
  },
  {
    "tool": "propose_regenerate",
    "input": { "tool_name": "claim_chart", "hint": "..." }
                // tool_name: "claim_chart" | "strategy" | "amendment"
  }
]
```

수락 시 `propose_patch` → `/edits/apply` 호출.  
`propose_regenerate` 수락 시 **부분 재실행 API 없음** → `POST /api/v1/analysis`로 전체 재분석만 가능.

---

### `POST /api/v1/analysis/{application_number}/edits/apply`

저장된 결과의 특정 필드를 덮어씀. **하위 tool은 자동 재실행되지 않음.**

**요청**
```json
{
  "target_path": "amendment.offensive_draft.amended_claims[0].amended_text",
  "new_value": "수정된 텍스트",
  "user_instruction": "메모 (선택)"
}
```

`target_path` 예시:

| 대상 | target_path |
|------|-------------|
| 공격 전략 설명 | `strategy.offensive.rationale` |
| 공격 보정안 1번째 청구항 | `amendment.offensive_draft.amended_claims[0].amended_text` |
| 방어 보정안 전체 설명 | `amendment.defensive_draft.overall_explanation` |

**응답** — 수정된 `AnalysisResult` 전체. `version` +1.

---

### `POST /api/v1/analysis/{application_number}/edits/revert`

**요청**
```json
{ "version": 2 }
```

**응답** — 해당 버전의 `AnalysisResult`.

---

## 에러

| 상태 | 상황 |
|------|------|
| `404` | 분석 결과 없음 / 해당 버전 없음 |
| `422` | 요청 형식 오류 |

**부분 실패** — `200`이지만 `errors[]`가 비어있지 않은 경우:
```jsonc
// errors[] 항목
{ "tool_name": "claim_chart", "error_type": "llm_failure", "message": "...", "is_fatal": false }
// error_type: "llm_failure" | "validation_error" | "timeout"
```

---

## 빠른 시작

```typescript
const BASE = "http://localhost:8000";
const APP = "10-2023-0001234";

const { analysis_id } = await fetch(`${BASE}/api/v1/analysis`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ application_number: APP }),
}).then(r => r.json());

await new Promise<void>((resolve, reject) => {
  const es = new EventSource(`${BASE}/api/v1/analysis/${analysis_id}/stream`);
  es.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.done) { es.close(); ev.error ? reject(ev.error) : resolve(); }
  };
});

const result = await fetch(`${BASE}/api/v1/analysis/${APP}`).then(r => r.json());
```
