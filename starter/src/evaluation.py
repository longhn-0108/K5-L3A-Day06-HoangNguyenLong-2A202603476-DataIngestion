"""Evaluate retrieved evidence and preserve per-query traces."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any


def _norm_for_match(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", " ", s).strip().lower()


def _hit_matches_gold(question: dict[str, Any], hit: dict[str, Any]) -> bool:
    gold_sources = question.get("gold_source_ids") or [question["gold_source_id"]]
    gold_pages = question.get("gold_pages") or [question["gold_page"]]
    if hit.get("document_id") not in gold_sources:
        return False
    if hit.get("page") not in gold_pages:
        return False
    quotes = question.get("alternative_quotes") or [question["evidence_quote"]]
    hit_text = _norm_for_match(hit.get("text", ""))
    return any(_norm_for_match(q) in hit_text for q in quotes if q)


def _check_filter_compliance(applied_filter: dict[str, Any] | None, hits: list[dict[str, Any]]) -> bool | None:
    if not applied_filter:
        return None
    if not hits:
        return False
    for h in hits:
        meta = h.get("metadata") or {}
        for k, v in applied_filter.items():
            if meta.get(k) != v:
                return False
    return True


def evaluate_query(
    question: dict[str, Any],
    hits: list[dict[str, Any]],
    strategy: str = "",
    applied_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check source/page and enough gold evidence; keep hit@1 and hit@3 trace."""
    matched_ranks = [idx + 1 for idx, h in enumerate(hits) if _hit_matches_gold(question, h)]
    hit_at_1 = 1 in matched_ranks
    evidence_hit_at_3 = any(r <= 3 for r in matched_ranks)
    filter_compliant = _check_filter_compliance(applied_filter, hits)

    return {
        "strategy": strategy,
        "question_id": question["id"],
        "split": question["split"],
        "type": question.get("type", ""),
        "question": question["question"],
        "expected_answer": question["expected_answer"],
        "gold_source_id": question["gold_source_id"],
        "gold_page": question["gold_page"],
        "evidence_quote": question["evidence_quote"],
        "requested_filter": question.get("filter"),
        "applied_filter": applied_filter,
        "hit_at_1": hit_at_1,
        "evidence_hit_at_3": evidence_hit_at_3,
        "matched_ranks": matched_ranks,
        "filter_compliant": filter_compliant,
        "top_k_hits": hits,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1 and Evidence Hit@3 by strategy and dev/test split."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)

    summary: dict[str, Any] = {}
    for (strategy, split), items in sorted(groups.items()):
        total = len(items)
        h1 = sum(1 for x in items if x["hit_at_1"])
        h3 = sum(1 for x in items if x["evidence_hit_at_3"])
        filtered = [x for x in items if x.get("applied_filter")]
        f_ok = sum(1 for x in filtered if x.get("filter_compliant") is True)
        summary[f"{strategy}_{split}"] = {
            "strategy": strategy,
            "split": split,
            "n_questions": total,
            "hit_at_1_count": h1,
            "hit_at_1_rate": round(h1 / total, 4) if total else 0.0,
            "evidence_hit_at_3_count": h3,
            "evidence_hit_at_3_rate": round(h3 / total, 4) if total else 0.0,
            "filtered_questions": len(filtered),
            "filter_compliant_count": f_ok if filtered else None,
        }
    return summary
