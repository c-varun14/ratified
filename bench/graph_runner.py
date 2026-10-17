"""Answer the bench questions with the graph — the system under test.

Each question carries a `graph` plan: either a catalogue tool call or a read-only
Cypher query. This module only executes the plan and shapes the rows; it does not
decide the answer's correctness (see `grade.py`) and it never reads `keys.json`.
"""
from __future__ import annotations

from ratified import tools
from ratified.graph import connect, rows


def _values(result_rows: list[dict]) -> list:
    out = []
    for row in result_rows:
        out.extend(v for v in row.values() if v is not None)
    return out


def _shape(kind: str, values: list) -> dict:
    if kind == "number":
        if not values:
            return {"answer": None, "abstain": True, "text": ""}
        return {"answer": int(values[0]), "abstain": False, "text": " ".join(str(v) for v in values)}
    if kind == "list":
        if not values:
            return {"answer": [], "abstain": True, "text": ""}
        return {"answer": [str(v) for v in values], "abstain": False, "text": " ".join(str(v) for v in values)}
    if not values:
        return {"answer": None, "abstain": True, "text": ""}
    return {"answer": str(values[0]), "abstain": False, "text": " ".join(str(v) for v in values)}


def answer_one(graph, question: dict, kind: str) -> dict:
    plan = question["graph"]
    if plan["kind"] == "tool":
        card = tools.run(graph, plan["tool"], **plan.get("args") or {})
        abstain = card["outcome"] == tools.OUTCOME_UNKNOWN
        text = " ".join(
            [card["title"], *[claim["text"] for claim in card["claims"]]]
        ).strip()
        return {
            "answer": None if abstain else card.get("answer", card["title"]),
            "abstain": abstain,
            "outcome": card["outcome"],
            "rows": len(card["rows"]),
            "text": text,
            "plan": {"tool": plan["tool"], "args": plan.get("args") or {}},
        }
    result = rows(graph, plan["query"])
    shaped = _shape(kind, _values(result))
    shaped["outcome"] = None
    shaped["rows"] = len(result)
    shaped["text"] = "".join([shaped["text"], " ", plan["query"]])
    shaped["plan"] = {"cypher": plan["query"]}
    return shaped


def answer_all(questions: list[dict], keys: dict) -> dict[str, dict]:
    graph = connect()
    out: dict[str, dict] = {}
    for question in questions:
        kind = keys[question["id"]]["answer_kind"]
        out[question["id"]] = answer_one(graph, question, kind)
    return out
