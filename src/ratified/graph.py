"""Connect to FalkorDB and run Cypher, returning rows as dicts keyed by column name.

While a trace is active (one per web request), every query is recorded with FalkorDB's own internal execution
time, so each answer card can show the Cypher that produced it.
"""
from __future__ import annotations

import os
import re
from contextvars import ContextVar

from falkordb import FalkorDB

_TRACE: ContextVar[list[dict] | None] = ContextVar("ratified_trace", default=None)


def connect(host: str | None = None, port: int | None = None, graph: str | None = None):
    db = FalkorDB(
        host=host or os.environ.get("RATIFIED_FALKOR_HOST", "localhost"),
        port=int(port or os.environ.get("RATIFIED_FALKOR_PORT", "6379")),
    )
    return db.select_graph(graph or os.environ.get("RATIFIED_GRAPH", "ratified"))


def start_trace() -> None:
    _TRACE.set([])


def stop_trace() -> list[dict]:
    trace = _TRACE.get() or []
    _TRACE.set(None)
    return trace


def rows(graph, cypher: str, params: dict | None = None) -> list[dict]:
    result = graph.query(cypher, params or {})
    columns = [column[1] for column in result.header]
    out = [dict(zip(columns, row)) for row in result.result_set]
    trace = _TRACE.get()
    if trace is not None:
        trace.append(
            {
                "cypher": re.sub(r"\s+", " ", cypher).strip(),
                "params": {k: v for k, v in (params or {}).items() if k != "rows"},
                "rows": len(out),
                "ms": round(float(result.run_time_ms or 0.0), 3),
            }
        )
    return out
