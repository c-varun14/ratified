"""Deterministic scoring for the bench. No LLM judges anything here.

Every count comes from string comparison after a fixed normalisation, so the table
is reproducible byte for byte. Per category (and overall) the grader reports, for
both systems, how many questions were answered exactly, how many only by substring,
how many ties (substring but not exact) and how many negatives (neither).
"""
from __future__ import annotations

import re

NORM_RE = re.compile(r"[^a-z0-9]+")


def norm(text) -> str:
    return NORM_RE.sub(" ", str(text).lower()).strip()


def _atoms(key: dict) -> list[str]:
    return [norm(atom) for atom in key.get("atoms") or []]


def _exact_graph(key: dict, answer: dict) -> bool:
    kind = key["answer_kind"]
    if answer.get("abstain"):
        return False
    if kind == "number":
        try:
            return int(answer["answer"]) == int(key["key"])
        except (TypeError, ValueError):
            return False
    if kind == "list":
        got = {norm(x) for x in answer.get("answer") or []}
        return got == {norm(x) for x in key["key"] or []}
    return norm(answer.get("answer")) == norm(key["key"])


def _contains_all(haystack: str, needles: list[str]) -> bool:
    return all(needle in haystack for needle in needles)


def score_graph(key: dict, answer: dict) -> dict:
    if key["answer_kind"] == "abstain":
        return {"scoreable": True, "exact": bool(answer.get("abstain")),
                "substring": bool(answer.get("abstain")), "abstained": bool(answer.get("abstain"))}
    exact = _exact_graph(key, answer)
    substring = exact or _contains_all(norm(answer.get("text")), _atoms(key))
    return {"scoreable": True, "exact": exact, "substring": substring,
            "abstained": bool(answer.get("abstain"))}


def score_rag(key: dict, retrieval: dict) -> dict:
    """A retriever is scored on what its retrieved context contains; it never abstains.

    Count questions are not scoreable by retrieval: a rank-1 chunk merely containing
    the digits of the answer is not an answer, and counting them is exactly the step a
    retriever cannot take. They are marked not-scoreable rather than counted as either
    a pass or a fail, and the count of them is reported.
    """
    top1 = norm(retrieval["texts"][0]) if retrieval["texts"] else ""
    topk = norm(" ".join(retrieval["texts"]))
    base = {"abstained": False, "top1": retrieval["ids"][0] if retrieval["ids"] else None}
    if key["answer_kind"] == "number":
        return {**base, "scoreable": False, "exact": False, "substring": False, "evidence_hit": False,
                "not_scoreable_reason": "retrieval cannot emit a count"}
    atoms = _atoms(key)
    if key["answer_kind"] == "abstain" or not atoms:
        # A retriever has no way to refuse: it always returns chunks, so it never abstains.
        return {**base, "scoreable": True, "exact": False, "substring": False, "evidence_hit": False}
    return {
        **base,
        "scoreable": True,
        "exact": _contains_all(top1, atoms),
        "substring": _contains_all(topk, atoms),
        "evidence_hit": any(atom in topk for atom in atoms),
    }


def _blank() -> dict:
    return {"exact": 0, "substring": 0, "ties": 0, "negatives": 0, "total": 0, "not_scoreable": 0}


def _accumulate(bucket: dict, score: dict) -> None:
    if score.get("scoreable") is False:
        bucket["not_scoreable"] += 1
        return
    bucket["total"] += 1
    bucket["exact"] += int(score["exact"])
    bucket["substring"] += int(score["substring"])
    if score["substring"] and not score["exact"]:
        bucket["ties"] += 1
    if not score["substring"]:
        bucket["negatives"] += 1


def score_system(keys: dict, questions: list[dict], answers: dict) -> dict:
    """Grade one system's answers across the whole set, by category and overall."""
    table: dict[str, dict] = {}
    for question in questions:
        key = keys[question["id"]]
        bucket = table.setdefault(key["category"], _blank())
        _accumulate(bucket, score_graph(key, answers[question["id"]]))
    fields = ("exact", "substring", "ties", "negatives", "total", "not_scoreable")
    return {
        "table": table,
        "totals": {field: sum(table[c][field] for c in table) for field in fields},
    }


def grade(keys: dict, questions: list[dict], graph_answers: dict, rag_retrievals: dict) -> dict:
    table: dict[str, dict] = {}
    per_question: list[dict] = []
    abstain = {"unanswerable": 0, "graph_correct": 0, "graph_false_abstain": 0,
               "rag_correct": 0, "rag_substance_free": 0, "examples": []}

    for question in questions:
        qid = question["id"]
        key = keys[qid]
        category = key["category"]
        graph_score = score_graph(key, graph_answers[qid])
        rag_score = score_rag(key, rag_retrievals[qid])
        entry = table.setdefault(category, {"graph": _blank(), "rag": _blank()})
        _accumulate(entry["graph"], graph_score)
        _accumulate(entry["rag"], rag_score)

        if key["answer_kind"] == "abstain":
            abstain["unanswerable"] += 1
            abstain["graph_correct"] += int(graph_score["abstained"])
            rag_confident = bool(rag_retrievals[qid]["ids"])
            abstain["rag_substance_free"] += int(rag_confident)
            abstain["examples"].append(
                {
                    "id": qid,
                    "graph_abstained": graph_score["abstained"],
                    "rag_returned": rag_retrievals[qid]["ids"][:3],
                    "rag_top1_excerpt": rag_retrievals[qid]["texts"][0][:240] if rag_confident else "",
                    "gated": bool(graph_score["abstained"] and rag_confident),
                }
            )
        elif graph_score["abstained"]:
            abstain["graph_false_abstain"] += 1

        per_question.append(
            {
                "id": qid,
                "category": category,
                "question": question["q"],
                "answer_kind": key["answer_kind"],
                "key": key["key"],
                "authoritative_source": key["authoritative_source"],
                "graph": {
                    **graph_answers[qid],
                    "exact": graph_score["exact"],
                    "substring": graph_score["substring"],
                },
                "rag": {
                    "top_k": rag_retrievals[qid]["ids"],
                    "scoreable": rag_score.get("scoreable", True),
                    "exact": rag_score["exact"],
                    "substring": rag_score["substring"],
                    "evidence_hit": rag_score["evidence_hit"],
                    **({"note": rag_score["not_scoreable_reason"]} if not rag_score.get("scoreable", True) else {}),
                },
            }
        )

    totals = {
        system: {
            field: sum(table[category][system][field] for category in table)
            for field in ("exact", "substring", "ties", "negatives", "total", "not_scoreable")
        }
        for system in ("graph", "rag")
    }
    totals["n"] = len(questions)
    return {"table": table, "totals": totals, "abstain": abstain, "questions": per_question}


def subset_summary(per_question: list[dict], keys: dict, answerable_only: bool = True) -> dict:
    """The text-supported subset: questions a retriever could in principle answer."""
    selected = [q for q in per_question if keys[q["id"]].get("rag_answerable")]
    if not selected:
        return {"n": 0}
    return {
        "n": len(selected),
        "ids": [q["id"] for q in selected],
        "graph": {k: sum(int(q["graph"][k]) for q in selected) for k in ("exact", "substring")},
        "rag": {k: sum(int(q["rag"][k]) for q in selected) for k in ("exact", "substring")},
        "note": (
            "questions whose answer's evidence lies in text the RAG corpus indexes "
            "(message subjects/bodies and RFC 8446 section text)"
        ),
    }
