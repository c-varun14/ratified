"""Optional LLM polish: pick a tool from the catalogue and phrase the result.

Every response is cached to disk keyed by (model, prompt, graph-hash). The LLM
never produces a citation — the mechanical chips come from tools.py — and its
phrasing is returned in a separate field. When litellm is missing, no provider
key is set, or RATIFIED_LLM=off, every call returns None and the page runs in
deterministic tool mode.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import routing, schema, tools
from .graph import rows
from .paths import ROOT

MODEL = os.environ.get("RATIFIED_MODEL", "gpt-4o-mini")
OFF_ENV = "RATIFIED_LLM"
API_KEY_ENVS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY", "OPENROUTER_API_KEY")
CACHE_DIR = Path(os.environ.get("RATIFIED_LLM_CACHE", str(ROOT / "cache" / "llm")))

_GRAPH_HASH: str | None = None


def enabled() -> bool:
    if os.environ.get(OFF_ENV, "").lower() in ("0", "off", "false", "no"):
        return False
    if not any(os.environ.get(key) for key in API_KEY_ENVS):
        return False
    try:
        import litellm  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def graph_hash(graph) -> str:
    global _GRAPH_HASH
    if _GRAPH_HASH is None:
        node_count = rows(graph, "MATCH (n) RETURN count(n) AS n")[0]["n"]
        edge_count = rows(graph, "MATCH ()-[e]->() RETURN count(e) AS n")[0]["n"]
        payload = json.dumps({"nodes": node_count, "edges": edge_count, "schema": schema.SCHEMA_VERSION})
        _GRAPH_HASH = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return _GRAPH_HASH


def complete(prompt: str, *, graph, model: str = MODEL) -> str | None:
    if not enabled():
        return None
    key = hashlib.sha256(f"{model}\x00{prompt}\x00{graph_hash(graph)}".encode("utf-8")).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())["text"]
    text = _call(model, prompt)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"model": model, "prompt": prompt, "graph_hash": graph_hash(graph), "text": text})
    )
    return text


def choose_tool(graph, question: str) -> tuple[str, dict]:
    fallback = routing.route(question)
    if not enabled():
        return fallback
    catalogue = json.dumps([{"name": t["name"], "args": t["args"]} for t in tools.TOOL_CATALOGUE])
    prompt = (
        "Choose one tool and its arguments for the question. Reply with a single JSON object "
        '{"tool": <name>, "arguments": {<arg>: <value>}} and nothing else.\n'
        f"Tools: {catalogue}\nQuestion: {question}"
    )
    text = complete(prompt, graph=graph)
    if not text:
        return fallback
    try:
        choice = json.loads(_first_json(text))
        name = choice["tool"]
        if name not in tools.TOOLS:
            return fallback
        allowed = tools.CATALOGUE_BY_NAME[name]["args"]
        arguments = {k: v for k, v in (choice.get("arguments") or {}).items() if k in allowed}
        return name, arguments
    except (ValueError, KeyError, TypeError):
        return fallback


def phrase(graph, question: str, answer: dict) -> str | None:
    if not enabled():
        return None
    prompt = (
        "Rewrite the graph result as one plain sentence. Do not add facts, numbers or links; "
        "only restate what is given.\n"
        f"Question: {question}\nOutcome: {answer['outcome']}\nTitle: {answer['title']}\nClaims:\n"
        + "\n".join(f"- {claim['text']}" for claim in answer["claims"][:20])
    )
    return complete(prompt, graph=graph)


def _call(model: str, prompt: str) -> str:
    import litellm

    response = litellm.completion(
        model=model, messages=[{"role": "user", "content": prompt}], temperature=0.2
    )
    return response["choices"][0]["message"]["content"]


def _first_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in LLM reply")
    return text[start : end + 1]
