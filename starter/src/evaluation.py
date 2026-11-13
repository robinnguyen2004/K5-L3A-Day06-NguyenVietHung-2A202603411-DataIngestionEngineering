"""Evaluate retrieved evidence per query and aggregate Hit@1 / Evidence Hit@3.

A hit = the chunk is on a gold (source, page) AND contains the FULL evidence quote.
Evidence is compared after NFC normalization with all whitespace removed, because the PDF
text layer splits some words ("lao đ ộng"). Human judgements (grounding, coherence,
equivalent evidence) are NOT inferred here; they are labelled manually.
"""
import re
import unicodedata
from collections import defaultdict
from typing import Any


def _nospace(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text)).lower()


def gold_set(question: dict[str, Any]) -> set[tuple[str, int]]:
    pages = question["gold_page"]
    pages = pages if isinstance(pages, list) else [pages]
    gold = {(question["gold_source_id"], int(p)) for p in pages}
    for alt in question.get("alternative_gold", []):
        gold.add((alt["source_id"], int(alt["page"])))
    return gold


def matches_filter(hit: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    for key, value in (filters or {}).items():
        if key == "chapter":
            if value not in (hit.get("chapters") or []):
                return False
        elif hit.get(key) != value:
            return False
    return True


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Score one query and keep the full top-k trace."""
    gold = gold_set(question)
    evidence = _nospace(question["evidence_quote"])
    half = max(1, len(evidence) // 2)
    question_filter = question.get("filter")
    ranked = []
    for rank, hit in enumerate(hits, start=1):
        text = _nospace(hit["text"])
        on_gold = (hit["document_id"], int(hit["page"])) in gold
        contains = evidence in text
        ranked.append({
            "rank": rank,
            "chunk_id": hit["chunk_id"],
            "score": hit["score"],
            "document_id": hit["document_id"],
            "source": hit["source"],
            "page": hit["page"],
            "law_name": hit.get("law_name"),
            "chapters": hit.get("chapters"),
            "articles": hit.get("articles"),
            "text": hit["text"],
            "on_gold_page": on_gold,
            "contains_full_evidence": contains,
            "contains_partial_evidence": not contains and (evidence[:half] in text or evidence[half:] in text),
            "hit": on_gold and contains,
            "matches_question_filter": matches_filter(hit, question_filter) if question_filter else None,
        })
    top3 = ranked[:3]
    hit3 = any(r["hit"] for r in top3)
    return {
        "id": question["id"],
        "split": question["split"],
        "type": question.get("type"),
        "question": question["question"],
        "expected_answer": question["expected_answer"],
        "gold": sorted(f"{s}:p{p}" for s, p in gold),
        "evidence_quote": question["evidence_quote"],
        "question_filter": question_filter,
        "hit@1": bool(ranked) and ranked[0]["hit"],
        "hit@3": hit3,
        "gold_page_in_top3": any(r["on_gold_page"] for r in top3),
        # Gold page retrieved but evidence only partly inside a chunk -> likely split across chunks.
        "evidence_split_suspect": not hit3 and any(r["on_gold_page"] and r["contains_partial_evidence"]
                                                   for r in top3),
        "filter_compliant_top3": (all(r["matches_question_filter"] for r in top3)
                                  if question_filter else None),
        "hits": ranked,
    }


def _ratio(n: int, total: int) -> dict[str, Any]:
    return {"n": n, "N": total, "text": f"{n}/{total}", "rate": round(n / total, 3) if total else None}


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate by strategy and split. Every metric is reported as n/N."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        groups[(trace["strategy"], trace["split"])].append(trace)
    summary: dict[str, Any] = {}
    for (strategy, split), items in sorted(groups.items()):
        filtered = [t for t in items if t["question_filter"]]
        by_type: dict[str, list] = defaultdict(list)
        for t in items:
            by_type[t.get("type") or "unknown"].append(t)
        summary.setdefault(strategy, {})[split] = {
            "questions": len(items),
            "hit@1": _ratio(sum(t["hit@1"] for t in items), len(items)),
            "evidence_hit@3": _ratio(sum(t["hit@3"] for t in items), len(items)),
            "gold_page_in_top3": _ratio(sum(t["gold_page_in_top3"] for t in items), len(items)),
            "evidence_split_suspect": [t["id"] for t in items if t["evidence_split_suspect"]],
            "filter_compliance_top3": (_ratio(sum(bool(t["filter_compliant_top3"]) for t in filtered),
                                              len(filtered)) if filtered else "N/A"),
            "hit@3_by_type": {k: _ratio(sum(t["hit@3"] for t in v), len(v)) for k, v in sorted(by_type.items())},
            "misses_at_3": [t["id"] for t in items if not t["hit@3"]],
        }
    return summary
