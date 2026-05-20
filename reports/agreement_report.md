# LLM 구성 대비 일치율 비교 보고서

- 생성 시각: 2026-05-20 12:21
- 대상 문서: 10개 출원
- 대상 모델: 3개
- 비교 단위: 의견제출통지서 전체 청구항이 아니라, 심사관이 구성비교표 형태로 명시한 comparison row
- 일치 기준: `examiner_match == our_match`
- 라벨: 동일 / 유사 / 차이

## 대상 출원번호

`10-2014-0036561`, `10-2019-0156160`, `10-2020-0019150`, `10-2022-0039209`, `10-2020-0001439`, `10-2018-0029369`, `10-2012-0085288`, `10-2020-0051159`, `10-2011-0114638`, `10-2024-0003359`

## 대상 모델

- `google/gemini-3.1-pro-preview`
- `openai/gpt-5.4`
- `anthropic/claude-sonnet-4.6`

## 1. 모델별 전체 요약

| Model | Agreement | Matched | Mismatched | Comparable | Missing Examiner | Total |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.1-pro-preview | 0.0% | 0 | 0 | 0 | 0 | 0 |
| openai/gpt-5.4 | 0.0% | 0 | 0 | 0 | 0 | 0 |
| anthropic/claude-sonnet-4.6 | 0.0% | 0 | 0 | 0 | 0 | 0 |

## 2. 문서별 모델 일치율

| Application | google/gemini-3.1-pro-preview | openai/gpt-5.4 | anthropic/claude-sonnet-4.6 | Comparable Rows |
| --- | --- | --- | --- | --- |
| 10-2014-0036561 | 0.0% (0/0) | 0.0% (0/0) | 0.0% (0/0) | 0/0/0 |
| 10-2019-0156160 | 0.0% (0/0) | 0.0% (0/0) | 0.0% (0/0) | 0/0/0 |
| 10-2020-0019150 | 0.0% (0/0) | 0.0% (0/0) | 0.0% (0/0) | 0/0/0 |
| 10-2022-0039209 | 0.0% (0/0) | 0.0% (0/0) | 0.0% (0/0) | 0/0/0 |
| 10-2020-0001439 | 0.0% (0/0) | 0.0% (0/0) | 0.0% (0/0) | 0/0/0 |
| 10-2018-0029369 | 0.0% (0/0) | 0.0% (0/0) | 0.0% (0/0) | 0/0/0 |
| 10-2012-0085288 | 0.0% (0/0) | 0.0% (0/0) | 0.0% (0/0) | 0/0/0 |
| 10-2020-0051159 | 0.0% (0/0) | 0.0% (0/0) | 0.0% (0/0) | 0/0/0 |
| 10-2011-0114638 | 0.0% (0/0) | 0.0% (0/0) | 0.0% (0/0) | 0/0/0 |
| 10-2024-0003359 | 0.0% (0/0) | 0.0% (0/0) | 0.0% (0/0) | 0/0/0 |

## 3. 모델별 LLM 라벨 분포

| Model | 동일 | 유사 | 차이 | Total |
| --- | --- | --- | --- | --- |
| google/gemini-3.1-pro-preview | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 |
| openai/gpt-5.4 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 |
| anthropic/claude-sonnet-4.6 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 |

## 4. Examiner vs LLM Matrix

행은 심사관 판단, 열은 LLM 판단입니다. 대각선 값이 일치 row입니다.

### google/gemini-3.1-pro-preview

| Examiner \ LLM | 동일 | 유사 | 차이 |
| --- | --- | --- | --- |
| 동일 | 0 | 0 | 0 |
| 유사 | 0 | 0 | 0 |
| 차이 | 0 | 0 | 0 |

### openai/gpt-5.4

| Examiner \ LLM | 동일 | 유사 | 차이 |
| --- | --- | --- | --- |
| 동일 | 0 | 0 | 0 |
| 유사 | 0 | 0 | 0 |
| 차이 | 0 | 0 | 0 |

### anthropic/claude-sonnet-4.6

| Examiner \ LLM | 동일 | 유사 | 차이 |
| --- | --- | --- | --- |
| 동일 | 0 | 0 | 0 |
| 유사 | 0 | 0 | 0 |
| 차이 | 0 | 0 | 0 |


---

# 청구항 거절 결론 통계

> **비교 단위:** 거절된 개별 청구항 (신규성+진보성 동시 거절은 신규성 1건으로 집계)
> **라벨:** 동의 / 부분동의 / 반대
> **주의:** 위 구성요소 대비 통계(분모=row 수)와 이 섹션(분모=청구항 수)은 단위가 다르므로 수치를 합산하지 마십시오.

데이터 없음 — `uv run python scripts/enrich_claim_conclusion.py` 를 먼저 실행하세요.

## 5. 해석 메모

- 이 보고서는 거절 대상 청구항 전체 수가 아니라, 심사관이 명시적으로 구성 대비한 row를 기준으로 합니다.
- 따라서 통지서에 언급된 청구항 수보다 비교 row 수가 적을 수 있습니다.
- 모델별 row 수가 다르면 해당 모델의 result.json 생성 실패, 누락, 또는 old format row 여부를 확인해야 합니다.
- `Missing Examiner`가 0에 가까울수록 fixed examiner row 기반 비교가 안정적으로 수행된 것입니다.

## 6. 누락된 결과 파일

| Application | Model | Expected Path |
| --- | --- | --- |
| 10-2014-0036561 | google/gemini-3.1-pro-preview | data\analysis\10-2014-0036561\google__gemini-3.1-pro-preview\result.json |
| 10-2014-0036561 | openai/gpt-5.4 | data\analysis\10-2014-0036561\openai__gpt-5.4\result.json |
| 10-2014-0036561 | anthropic/claude-sonnet-4.6 | data\analysis\10-2014-0036561\anthropic__claude-sonnet-4.6\result.json |
| 10-2019-0156160 | google/gemini-3.1-pro-preview | data\analysis\10-2019-0156160\google__gemini-3.1-pro-preview\result.json |
| 10-2019-0156160 | openai/gpt-5.4 | data\analysis\10-2019-0156160\openai__gpt-5.4\result.json |
| 10-2019-0156160 | anthropic/claude-sonnet-4.6 | data\analysis\10-2019-0156160\anthropic__claude-sonnet-4.6\result.json |
| 10-2020-0019150 | google/gemini-3.1-pro-preview | data\analysis\10-2020-0019150\google__gemini-3.1-pro-preview\result.json |
| 10-2020-0019150 | openai/gpt-5.4 | data\analysis\10-2020-0019150\openai__gpt-5.4\result.json |
| 10-2020-0019150 | anthropic/claude-sonnet-4.6 | data\analysis\10-2020-0019150\anthropic__claude-sonnet-4.6\result.json |
| 10-2022-0039209 | google/gemini-3.1-pro-preview | data\analysis\10-2022-0039209\google__gemini-3.1-pro-preview\result.json |
| 10-2022-0039209 | openai/gpt-5.4 | data\analysis\10-2022-0039209\openai__gpt-5.4\result.json |
| 10-2022-0039209 | anthropic/claude-sonnet-4.6 | data\analysis\10-2022-0039209\anthropic__claude-sonnet-4.6\result.json |
| 10-2020-0001439 | google/gemini-3.1-pro-preview | data\analysis\10-2020-0001439\google__gemini-3.1-pro-preview\result.json |
| 10-2020-0001439 | openai/gpt-5.4 | data\analysis\10-2020-0001439\openai__gpt-5.4\result.json |
| 10-2020-0001439 | anthropic/claude-sonnet-4.6 | data\analysis\10-2020-0001439\anthropic__claude-sonnet-4.6\result.json |
| 10-2018-0029369 | google/gemini-3.1-pro-preview | data\analysis\10-2018-0029369\google__gemini-3.1-pro-preview\result.json |
| 10-2018-0029369 | openai/gpt-5.4 | data\analysis\10-2018-0029369\openai__gpt-5.4\result.json |
| 10-2018-0029369 | anthropic/claude-sonnet-4.6 | data\analysis\10-2018-0029369\anthropic__claude-sonnet-4.6\result.json |
| 10-2012-0085288 | google/gemini-3.1-pro-preview | data\analysis\10-2012-0085288\google__gemini-3.1-pro-preview\result.json |
| 10-2012-0085288 | openai/gpt-5.4 | data\analysis\10-2012-0085288\openai__gpt-5.4\result.json |
| 10-2012-0085288 | anthropic/claude-sonnet-4.6 | data\analysis\10-2012-0085288\anthropic__claude-sonnet-4.6\result.json |
| 10-2020-0051159 | google/gemini-3.1-pro-preview | data\analysis\10-2020-0051159\google__gemini-3.1-pro-preview\result.json |
| 10-2020-0051159 | openai/gpt-5.4 | data\analysis\10-2020-0051159\openai__gpt-5.4\result.json |
| 10-2020-0051159 | anthropic/claude-sonnet-4.6 | data\analysis\10-2020-0051159\anthropic__claude-sonnet-4.6\result.json |
| 10-2011-0114638 | google/gemini-3.1-pro-preview | data\analysis\10-2011-0114638\google__gemini-3.1-pro-preview\result.json |
| 10-2011-0114638 | openai/gpt-5.4 | data\analysis\10-2011-0114638\openai__gpt-5.4\result.json |
| 10-2011-0114638 | anthropic/claude-sonnet-4.6 | data\analysis\10-2011-0114638\anthropic__claude-sonnet-4.6\result.json |
| 10-2024-0003359 | google/gemini-3.1-pro-preview | data\analysis\10-2024-0003359\google__gemini-3.1-pro-preview\result.json |
| 10-2024-0003359 | openai/gpt-5.4 | data\analysis\10-2024-0003359\openai__gpt-5.4\result.json |
| 10-2024-0003359 | anthropic/claude-sonnet-4.6 | data\analysis\10-2024-0003359\anthropic__claude-sonnet-4.6\result.json |
