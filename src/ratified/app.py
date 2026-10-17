"""The one product page: question box -> catalogue tool -> Cypher -> answer card."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import insights, llm, tools
from .graph import connect, rows, start_trace, stop_trace

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app = FastAPI(title="Ratified")

SCENARIO = "I'm new here: why does RFC 8446 section 4.2.1 read the way it does, and who do I ask?"

EXAMPLES = [
    "Why does early data work like this in TLS 1.3?",
    "What did people say about middleboxes?",
    "Who knows the most about TLS 1.3?",
    "Which clauses of draft-ietf-tls-tls13 were discussed while still changing and never resolved?",
    "Which IESG DISCUSS positions were filed against draft-ietf-tls-tls13?",
]

STATS_Q = """
MATCH (m:Message)
WITH count(m) AS messages, sum(CASE WHEN m.has_body THEN 1 ELSE 0 END) AS with_text,
     min(m.date) AS first, max(m.date) AS last
MATCH (n) WITH messages, with_text, first, last, count(n) AS nodes
MATCH ()-[e]->() RETURN messages, with_text, first, last, nodes, count(e) AS edges
"""


def corpus_stats() -> dict | None:
    try:
        found = rows(connect(), STATS_Q)
    except Exception:  # noqa: BLE001
        return None
    return found[0] if found and found[0]["nodes"] else None


def clause_index() -> list[dict]:
    try:
        return tools.discussed_clauses(connect())
    except Exception:  # noqa: BLE001
        return []


def people_index() -> list[dict]:
    try:
        return insights.central_people(connect(), 6)
    except Exception:  # noqa: BLE001
        return []


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "catalogue": tools.TOOL_CATALOGUE,
            "card": None,
            "question": "",
            "scenario": SCENARIO,
            "examples": EXAMPLES,
            "stats": corpus_stats(),
            "clauses": clause_index(),
            "people": people_index(),
        },
    )


@app.post("/ask", response_class=HTMLResponse)
def ask(request: Request, question: str = Form("")):
    graph = connect()
    start_trace()
    try:
        tool, arguments = llm.choose_tool(graph, question)
        result = tools.run(graph, tool, **arguments)
        result["phrasing"] = llm.phrase(graph, question, result)
    finally:
        trace = stop_trace()
    return TEMPLATES.TemplateResponse(
        request,
        "_card.html",
        {"card": result, "tool": tool, "arguments": arguments, "question": question, "trace": trace},
    )


@app.get("/receipt", response_class=HTMLResponse)
def receipt(request: Request, draft: str = "", sid: str = "", limit: int | None = None):
    graph = connect()
    start_trace()
    try:
        found = tools.clause_receipt(graph, draft, sid, limit=limit)
    finally:
        trace = stop_trace()
    return TEMPLATES.TemplateResponse(request, "_receipt.html", {"receipt": found, "trace": trace})


@app.post("/sync", response_class=HTMLResponse)
def run_sync(request: Request, days: int = Form(1)):
    graph = connect()
    return TEMPLATES.TemplateResponse(request, "_sync.html", {"status": tools.sync(graph, days=days)})


@app.get("/health")
def health():
    return {"status": "ok"}
