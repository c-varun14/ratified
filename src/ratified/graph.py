"""Connect to FalkorDB and run Cypher, returning rows as dicts keyed by column name."""
from __future__ import annotations

import os

from falkordb import FalkorDB


def connect(host: str | None = None, port: int | None = None, graph: str | None = None):
    db = FalkorDB(
        host=host or os.environ.get("RATIFIED_FALKOR_HOST", "localhost"),
        port=int(port or os.environ.get("RATIFIED_FALKOR_PORT", "6379")),
    )
    return db.select_graph(graph or os.environ.get("RATIFIED_GRAPH", "ratified"))


def rows(graph, cypher: str, params: dict | None = None) -> list[dict]:
    result = graph.query(cypher, params or {})
    columns = [column[1] for column in result.header]
    return [dict(zip(columns, row)) for row in result.result_set]
