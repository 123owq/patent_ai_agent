# 특허 심사대응 AI 플랫폼

**사용자 선택형 공격·방어 전략 기반 보정청구항 자동 생성 AI 플랫폼**

43조 | 종합설계 1 | 지도교수: 조은선 교수님

---

## 개요

특허 의견제출통지서를 입력하면 AI가 자사 특허와 인용문헌을 비교·분석하여 공격적/방어적 대응 전략과 보정청구항 초안을 자동으로 생성합니다. 사용자는 두 전략을 나란히 비교하고 원하는 방향을 선택할 수 있습니다.

```
의견제출통지서 + 자사특허 + 인용문헌
        ↓
   AI 분석 파이프라인 (Tool 1~6)
        ↓
 Claim Chart (심사관 판단 검증)
 공격 전략 ↔ 방어 전략 비교
 보정청구항 초안 자동 생성
        ↓
   챗봇으로 결과 질의·수정
```

---

## 주요 기능

| 기능 | 설명 |
|---|---|
| 통지서 분석 | 거절이유·인용발명·문제 청구항 자동 추출 |
| 청구항 파싱 | 구성요소 단위 분해 (element_id 부여) |
| 상세설명 매핑 | 각 구성요소와 명세서 단락 자동 연결 |
| Claim Chart | 자사 vs 인용발명 대비표 + 심사관 판단 검증 |
| 공격·방어 전략 | 두 전략 동시 생성, UI에서 토글 비교 |
| 보정청구항 생성 | 명세서 뒷받침 근거 포함 초안 자동 작성 |
| 챗봇 | 결과 질의·수정 제안·특정 Tool 재실행 |

---

## 기술 스택

- **언어**: Python 3.12
- **패키지 관리**: [uv](https://github.com/astral-sh/uv)
- **백엔드**: FastAPI + uvicorn
- **AI**: Claude API (Anthropic) / OpenAI API — 환경변수로 스위칭
- **스키마**: Pydantic v2
- **프론트엔드**: Next.js (별도 디렉토리, 미포함)

---

## 프로젝트 구조

```
patent-agent/
├── src/patent_agent/
│   ├── models/          # Pydantic 데이터 모델
│   ├── llm/             # LLM provider abstraction (Claude/OpenAI)
│   ├── prompts/         # Jinja2 프롬프트 템플릿 (.j2)
│   ├── tools/           # Tool 1~6 Pure Python 함수
│   ├── core/            # pipeline, storage, chatbot, prompts
│   └── api/             # FastAPI 앱 + 라우터
├── tests/
│   ├── fixtures/        # 테스트용 샘플 특허 데이터
│   ├── unit/            # Tool별 단위 테스트
│   └── integration/     # 파이프라인 통합 테스트 + E2E
├── data/
│   ├── input/           # 입력 JSON 파일 (특허, 통지서, 인용문헌)
│   └── analysis/        # 분석 결과 저장 (버전 관리)
├── docs/
│   ├── superpowers/specs/   # 설계 문서
│   └── superpowers/plans/   # 구현 계획서
└── pyproject.toml
```

---

## 빠른 시작

### 1. 의존성 설치

```bash
# uv 설치 (없는 경우)
pip install uv

# 프로젝트 의존성 설치
uv sync --extra dev
```

### 2. 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 API 키 입력
```

```bash
# .env
LLM_PROVIDER=claude          # claude 또는 openai
ANTHROPIC_API_KEY=sk-ant-... # Claude 사용 시
OPENAI_API_KEY=sk-...        # OpenAI 사용 시
DATA_DIR=./data
```

### 3. 입력 데이터 배치

```
data/input/{출원번호}/
├── patent.json          # 자사 특허
├── office_action.json   # 의견제출통지서
└── prior_arts/
    ├── 인용발명1.json
    └── 인용발명2.json
```

### 4. 서버 실행

```bash
uv run uvicorn patent_agent.api.main:app --reload --port 8000
```

Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## API 사용법

### 분석 시작

```bash
curl -X POST http://localhost:8000/api/v1/analysis \
  -H "Content-Type: application/json" \
  -d '{"application_number": "10-2014-0036561"}'
```

응답:
```json
{
  "analysis_id": "1714300000-10-2014-0036561",
  "application_number": "10-2014-0036561",
  "status": "started"
}
```

### 진행 상황 스트림 (SSE)

```bash
curl http://localhost:8000/api/v1/analysis/{analysis_id}/stream
```

```
data: {"step": "통지서 분석", "ratio": 0.0, "done": false}
data: {"step": "청구항 파싱", "ratio": 0.15, "done": false}
data: {"step": "완료", "ratio": 1.0, "done": true}
```

### 분석 결과 조회

```bash
curl http://localhost:8000/api/v1/analysis/10-2014-0036561
```

### 챗봇 질의

```bash
curl -X POST http://localhost:8000/api/v1/analysis/10-2014-0036561/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "1-A 구성요소 차이점 설명해줘"}],
    "active_strategy": "공격"
  }'
```

### 편집 적용

```bash
curl -X POST http://localhost:8000/api/v1/analysis/10-2014-0036561/edits/apply \
  -H "Content-Type: application/json" \
  -d '{
    "target_path": "claim_chart.charts[0].rows[0].our_match",
    "new_value": "차이",
    "user_instruction": "수치 범위가 실질적으로 다름"
  }'
```

---

## 전체 API 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/v1/analysis` | 분석 시작 |
| `GET` | `/api/v1/analysis/{id}/stream` | 진행 상황 SSE |
| `GET` | `/api/v1/analysis/{application_number}` | 결과 조회 |
| `POST` | `/api/v1/analysis/{id}/chat` | 챗봇 질의 |
| `POST` | `/api/v1/analysis/{id}/edits/apply` | 편집 적용 |
| `POST` | `/api/v1/analysis/{id}/edits/revert` | 버전 되돌리기 |

---

## 테스트

```bash
# 단위 테스트 + 통합 테스트 (mock LLM)
uv run pytest tests/unit/ tests/integration/test_pipeline.py -v

# E2E 시연 테스트 (실제 LLM API 호출)
LLM_PROVIDER=claude ANTHROPIC_API_KEY=<key> \
  uv run pytest tests/integration/test_e2e_demo.py -v -s
```

현재 테스트 현황: **24 passed** (단위 22 + 통합 2)

---

## LLM Provider 전환

동일한 코드로 Claude와 OpenAI를 환경변수로 스위칭합니다.

```bash
# Claude 사용
LLM_PROVIDER=claude ANTHROPIC_API_KEY=<key> uv run uvicorn ...

# OpenAI 사용
LLM_PROVIDER=openai OPENAI_API_KEY=<key> uv run uvicorn ...
```

---

## 분석 파이프라인

```
OfficeActionRaw ──→ Tool 1 ──→ OfficeActionResult
PatentDoc       ──→ Tool 2 ──→ ClaimParseResult
                    Tool 3 ──→ SpecMappingResult
PriorArtDocs    ──→ Tool 4 ──→ ClaimChartResult  (심사관 판단 검증 포함)
                    Tool 5 ──→ StrategyResult     (공격 + 방어 동시)
                    Tool 6 ──→ AmendmentResult    (보정청구항 초안)
                              ↓
                         AnalysisResult (JSON 저장)
```

- **Tool 3 실패 시**: degrade & continue (spec_mapping 빈 값으로 진행)
- **공격·방어 동시 생성**: UI에서 추가 LLM 호출 없이 토글

---

## 성공 지표

| 지표 | 목표 |
|---|---|
| 분석 완료 시간 | ≤ 60초 |
| 청구항 파싱 정확도 | 사람 검수 통과율 ≥ 80% |
| Claim Chart agreement_rate | ≥ 0.85 (시스템 vs 심사관) |
| 보정청구항 spec_basis 검증 | 100% 자동 (명세서 단락 존재 여부) |
| 보정청구항 품질 | IP 담당자 검수 통과율 ≥ 80% |

---

## 팀

| 이름 | 역할 |
|---|---|
| 박성준 | Product Owner, 파이프라인·Tool 5~6 |
| 김상철 | Scrum Master, LLM 추상화·Tool 2~3·챗봇 |
| 김상순 | 데이터 모델·Storage·Tool 1 |
| 박채영 | 입력 어댑터·Tool 4·API 연동 |
