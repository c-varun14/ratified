"""Rebuild the Ratified graph for one Working Group from the local record.

The graph is dropped and rebuilt from the record in data/ on every run, so the
result is deterministic: the same cache in, the same counts out.
"""
from __future__ import annotations

import argparse
import json
import os

from falkordb import FalkorDB

from . import datatracker, ingest, sections
from .fetch import Fetcher
from .paths import DATA_DIR


def rebuild(graph, data: dict, group: str) -> dict:
    try:
        graph.delete()
    except Exception:  # noqa: BLE001
        pass
    return ingest.ingest(graph, data, list_name=group)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ratified", description="Rebuild the Ratified graph.")
    parser.add_argument("--group", default=os.environ.get("RATIFIED_LIST", "tls"))
    parser.add_argument("--graph", default=os.environ.get("RATIFIED_GRAPH", "ratified"))
    parser.add_argument("--host", default=os.environ.get("RATIFIED_FALKOR_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("RATIFIED_FALKOR_PORT", "6379")))
    parser.add_argument("--data-dir", default=DATA_DIR)
    parser.add_argument("--refresh", action="store_true", help="re-fetch docs and sections first")
    args = parser.parse_args(argv)

    if args.refresh:
        fetcher = Fetcher()
        datatracker.pull(fetcher, args.group, data_dir=args.data_dir)
        sections.build(fetcher, args.data_dir)

    data = ingest.load_dataset(args.data_dir, args.group)
    graph = FalkorDB(host=args.host, port=args.port).select_graph(args.graph)
    print(json.dumps(rebuild(graph, data, args.group), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
