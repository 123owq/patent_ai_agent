import re
from patent_agent.llm.base import LLMClient
from patent_agent.models.input import OfficeActionRaw
from patent_agent.models.output import (
    OfficeActionResult,
    ExaminerChart,
    ExaminerChartRow,
)
from patent_agent.core.prompts import render


def extract_claim_numbers(text: str) -> list[int]:
    """'제1항, 제4항 내지 제7항' → [1, 4, 5, 6, 7]"""
    result: set[int] = set()
    for m in re.finditer(r"제(\d+)항\s*내지\s*제(\d+)항", text):
        result.update(range(int(m.group(1)), int(m.group(2)) + 1))
    cleaned = re.sub(r"제\d+항\s*내지\s*제\d+항", "", text)
    for m in re.finditer(r"제(\d+)항", cleaned):
        result.add(int(m.group(1)))
    return sorted(result)


def extract_examiner_chart(oa_raw: OfficeActionRaw) -> ExaminerChart | None:
    """통지서 raw_dict에서 구성비교표를 결정적으로 추출. LLM 없음."""
    try:
        reasons = oa_raw.raw_dict.get("구체적인거절이유", {})
        rows: list[ExaminerChartRow] = []
        for reason_val in reasons.values():
            if not isinstance(reason_val, dict):
                continue
            claim_reasons = reason_val.get("청구항별거절이유", {})
            for claim_val in claim_reasons.values():
                if not isinstance(claim_val, dict):
                    continue
                chart_rows = claim_val.get("진보성비교", {}).get("구성비교표", [])
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
