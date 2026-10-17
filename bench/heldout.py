"""Held-out routing check: questions the router was not tuned on.

Loads bench/heldout_questions.json, routes each free-text question with the
shipped router, and counts a hit when the tool matches and every key in
expect_args matches the routed argument (numbers as str(), headings
case-insensitively).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ratified import routing

HERE = Path(__file__).resolve().parent
ABSTAIN = {"no_answer", "not_understood"}


def _norm(value):
    return str(value).strip().lower()


def _args_match(expected: dict, got: dict) -> bool:
    for key, want in expected.items():
        if key not in got or _norm(got[key]) != _norm(want):
            return False
    return True


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "heldout"
    questions = json.loads((HERE / f"{name}_questions.json").read_text())
    results_path = HERE / f"{name}_results.json"
    rows = []
    hits = 0
    abstain_hits = 0
    for entry in questions:
        tool, arguments, tied = routing.route_ex(entry["q"])
        arguments = arguments or {}
        expected_args = entry.get("expect_args") or {}
        hit = tool == entry["expect_tool"] and _args_match(expected_args, arguments)
        hits += 1 if hit else 0
        abstain_hits += 1 if hit or (tool in ABSTAIN and entry["expect_tool"] in ABSTAIN) else 0
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
    summary = (
        f"held-out routing: {hits}/{total} strict; {abstain_hits}/{total} counting either abstention "
        f"({', '.join(sorted(ABSTAIN))}) as a correct decline"
    )
    print(summary)
    results_path.write_text(
        json.dumps(
            {"total": {"hits": hits, "abstain_equivalent": abstain_hits, "n": total}, "summary": summary, "rows": rows},
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
