# scripts/enrich_claim_conclusion.py
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from patent_agent.core.prompts import render
from patent_agent.llm.base import LLMClient
from patent_agent.models.output import ClaimConclusionResult


def build_conclusion_items(rejection_reasons: list[dict]) -> list[dict]:
    """
    office_action["rejection_reasons"] 에서 (청구항 × 거절유형) 쌍 목록 생성.
    같은 청구항에 신규성·진보성이 동시에 존재하면 신규성 1건으로 합산.
    기재불비는 별도 유지. 결과는 claim_number 오름차순 정렬.
    """
    by_claim: dict[int, dict[str, dict]] = defaultdict(dict)

    for reason in rejection_reasons:
        rtype = reason["rejection_type"]
        for cn in reason["target_claim_numbers"]:
            by_claim[cn][rtype] = reason

    items: list[dict] = []
    for cn in sorted(by_claim.keys()):
        types = by_claim[cn]

        if "신규성" in types and "진보성" in types:
            r = types["신규성"]
            items.append({
                "claim_number": cn,
                "rejection_type": "신규성",
                "merged_from": ["신규성", "진보성"],
                "examiner_reasoning": r["examiner_reasoning"],
                "cited_art_ids": r["cited_art_ids"],
            })
            for rtype in sorted(t for t in types if t not in ("신규성", "진보성")):
                r2 = types[rtype]
                items.append({
                    "claim_number": cn,
                    "rejection_type": rtype,
                    "merged_from": [],
                    "examiner_reasoning": r2["examiner_reasoning"],
                    "cited_art_ids": r2["cited_art_ids"],
                })
        else:
            for rtype in sorted(types.keys()):
                r = types[rtype]
                items.append({
                    "claim_number": cn,
                    "rejection_type": rtype,
                    "merged_from": [],
                    "examiner_reasoning": r["examiner_reasoning"],
                    "cited_art_ids": r["cited_art_ids"],
                })

    return items
