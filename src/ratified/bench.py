"""`python -m ratified.bench` — run the evaluation bench and write bench/results.json.

The bench lives in the top-level `bench/` directory so the question set, the
derived keys and the results are plain artefacts a reader can open. This module is
only the package entry point: it puts the repository root on the path and hands
over to `bench.run`, which derives the keys from the raw sources, answers each
question with the graph, retrieves with the BM25 + dense baseline and grades both.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from bench import run

    return run.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
