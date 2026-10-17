"""The one product page: question box -> catalogue tool -> Cypher -> answer card."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import llm, tools
from .graph import connect

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app = FastAPI(title="Ratified")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {"catalogue": tools.TOOL_CATALOGUE, "card": None, "question": ""},
    )


@app.post("/ask", response_class=HTMLResponse)
def ask(request: Request, question: str = Form("")):
    graph = connect()
    tool, arguments = llm.choose_tool(graph, question)
    result = tools.run(graph, tool, **arguments)
    result["phrasing"] = llm.phrase(graph, question, result)
    return TEMPLATES.TemplateResponse(
        request,
        "_card.html",
        {"card": result, "tool": tool, "arguments": arguments},
    )


@app.get("/receipt", response_class=HTMLResponse)
def receipt(request: Request, draft: str = "", sid: str = ""):
    graph = connect()
    return TEMPLATES.TemplateResponse(
        request,
        "_receipt.html",
        {"receipt": tools.clause_receipt(graph, draft, sid)},
    )


@app.get("/health")
def health():
    return {"status": "ok"}
