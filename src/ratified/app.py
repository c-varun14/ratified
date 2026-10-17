"""The one product page: question box -> catalogue tool -> Cypher -> answer card."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import routing, tools
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
    tool, arguments = routing.route(question)
    result = tools.run(connect(), tool, **arguments)
    return TEMPLATES.TemplateResponse(
        request,
        "_card.html",
        {"card": result, "tool": tool, "arguments": arguments},
    )


@app.get("/health")
def health():
    return {"status": "ok"}
