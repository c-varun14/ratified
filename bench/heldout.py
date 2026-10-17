"""Held-out routing check: questions the router was not tuned on.

Loads bench/heldout_questions.json, routes each free-text question with the
shipped router, and counts a hit when the tool matches and every key in
expect_args matches the routed argument (numbers as str(), headings
case-insensitively).
"""
from __future__ import annotations

import json
from pathlib import Path

from ratified import routing

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "heldout_questions.json"
RESULTS = HERE / "heldout_results.json"


def _norm(value):
    return str(value).strip().lower()


def _args_match(expected: dict, got: dict) -> bool:
    for key, want in expected.items():
        if key not in got or _norm(got[key]) != _norm(want):
            return False
    return True


def main() -> int:
    questions = json.loads(QUESTIONS.read_text())
    rows = []
    hits = 0
    for entry in questions:
        tool, arguments, tied = routing.route_ex(entry["q"])
        arguments = arguments or {}
        expected_args = entry.get("expect_args") or {}
        hit = tool == entry["expect_tool"] and _args_match(expected_args, arguments)
        hits += 1 if hit else 0
        rows.append(
            {
                "id": entry["id"],
                "q": entry["q"],
                "expect_tool": entry["expect_tool"],
                "expect_args": expected_args,
                "got_tool": tool,
                "got_args": arguments,
                "tied": tied,
                "hit": hit,
            }
        )
        print(
            f'{entry["id"]}: {"hit" if hit else "miss"} | '
            f'expected {entry["expect_tool"]} {expected_args} | got {tool} {arguments}'
        )
    total = len(questions)
    print(f"held-out routing: {hits}/{total}")
    RESULTS.write_text(
        json.dumps(
            {"total": {"hits": hits, "n": total}, "summary": f"held-out routing: {hits}/{total}", "rows": rows},
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
