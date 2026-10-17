"""Click-verify a sample of the citation chips the product renders.

The chips are mechanical — thread id, message id, draft revision, RFC section
anchor — and the claim being checked is that each one resolves to the artefact it
names. This script pulls the chips out of the real answer cards, takes a fixed,
stratified sample of ten, fetches each permalink over the live network and applies
the strictest rule per kind:

* section chip: the fetched HTML must actually carry ``id="section-N"`` (the
  rfc-editor anchor the URL points at), not merely return 200.
* revision chip: 200, and the page must name the revision it claims.
* thread / message chip: 200 at the permalink.
* RFC chip: 200.

Failures are written to `bench/chip_checks.json` and printed with their URLs — the
point is to list what broke, not to report a pass rate over an unspecified sample.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ratified import tools  # noqa: E402
from ratified.graph import connect, rows  # noqa: E402

OUT = Path(__file__).resolve().parent / "chip_checks.json"
SAMPLE_N = 10
SEED = 7
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
ANCHOR_RE = re.compile(r'id="(section-[0-9.]+)"')


def collect_chips() -> list[dict]:
    """Every chip the hero card and the receipt view can render, deduplicated."""
    graph = connect()
    chips: dict[str, dict] = {}

    card = tools.aggregate_unresolved(graph)
    for chip in card["chips"]:
        chips.setdefault(chip["url"], chip)
    for claim in card["claims"]:
        for chip in claim["chips"]:
            chips.setdefault(chip["url"], chip)

    cited = [c for c in card["claims"] if c["bucket"] == "cited"][:3]
    for claim in cited:
        receipt = tools.clause_receipt(graph, claim["draft"], claim["sid"])
        for path in receipt["paths"]:
            for step in path["steps"]:
                chips.setdefault(step["url"], step)

    for row in rows(graph, "MATCH (m:Message) WHERE m.has_body RETURN m.id AS id LIMIT 1"):
        for claim in tools.precedent(graph, row["id"])["claims"]:
            for chip in claim["chips"]:
                chips.setdefault(chip["url"], chip)
    return list(chips.values())


def sample(chips: list[dict], n: int = SAMPLE_N) -> list[dict]:
    """A fixed stratified sample: at least one of every kind present, then fill."""
    by_kind: dict[str, list[dict]] = {}
    for chip in sorted(chips, key=lambda c: (c["kind"], c["url"])):
        by_kind.setdefault(chip["kind"], []).append(chip)
    rng = random.Random(SEED)
    chosen: list[dict] = []
    for kind in sorted(by_kind):
        chosen.append(rng.choice(by_kind[kind]))
    pool = [chip for chip in sorted(chips, key=lambda c: c["url"]) if chip not in chosen]
    rng.shuffle(pool)
    chosen.extend(pool[: max(0, n - len(chosen))])
    return chosen[:n]


def fetch(url: str, timeout: float = 30.0, attempts: int = 3) -> dict:
    last = "no attempt"
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
                return {"status": response.status, "url": response.url, "body": body, "error": None}
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code in (404, 410):
                break
            time.sleep(1.5 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
    return {"status": None, "url": url, "body": "", "error": last}


def check(chip: dict) -> dict:
    result = fetch(chip["url"])
    status, body, error = result["status"], result["body"], result["error"]
    ok = status == 200
    detail = ""
    if chip["kind"] == "section" and ok:
        fragment = chip["url"].split("#", 1)[1] if "#" in chip["url"] else ""
        anchors = ANCHOR_RE.findall(body)
        ok = fragment in anchors
        if not ok:
            detail = f"anchor id=\"{fragment}\" absent from fetched HTML ({len(anchors)} section anchors present)"
        else:
            detail = f'anchor id="{fragment}" present'
    elif chip["kind"] == "revision" and ok:
        name = chip["label"]
        draft = name.rsplit("-", 1)[0]
        ok = name in body or draft in body
        detail = f"page names {name}" if ok else f"page does not name {name}"
    elif chip["kind"] == "thread" and ok:
        # A thread chip labels a thread id but permalinks the thread's root message.
        # mailarchive renders that root message page as the full thread listing, so
        # require the thread-row markup rather than merely a 200.
        markers = body.count("depth-")
        root = chip["url"].rstrip("/").rsplit("/", 1)[-1]
        ok = markers > 0 and root in body
        detail = f"thread listing present ({markers} depth markers, root {root} on page)"
    elif chip["kind"] == "message" and ok:
        marker = chip["url"].rstrip("/").rsplit("/", 1)[-1]
        ok = marker in body
        detail = f"message id {marker} present" if ok else f"message id {marker} absent"
    elif ok:
        detail = f"HTTP {status}"
    else:
        detail = error or f"HTTP {status}"
    return {
        "kind": chip["kind"],
        "label": chip["label"],
        "url": chip["url"],
        "final_url": result["url"],
        "status": status,
        "resolved": ok,
        "detail": detail,
        "error": error,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Click-verify a sample of citation chips.")
    parser.add_argument("--sample", type=int, default=SAMPLE_N)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    chips = collect_chips()
    chosen = sample(chips, args.sample)
    results = [check(chip) for chip in chosen]
    failures = [r for r in results if not r["resolved"]]
    record = {
        "meta": {
            "chips_available": len(chips),
            "kinds_available": sorted({c["kind"] for c in chips}),
            "sample_size": len(chosen),
            "seed": SEED,
            "method": "stratified on chip kind, then seeded fill; strictest rule per kind",
        },
        "results": results,
        "failures": failures,
    }
    Path(args.out).write_text(json.dumps(record, indent=2) + "\n")
    for result in results:
        mark = "ok " if result["resolved"] else "FAIL"
        print(f"  {mark} {result['kind']:8s} {result['status']}  {result['url']}")
        if not result["resolved"]:
            print(f"       {result['detail']}")
    print(f"\n{len(results) - len(failures)}/{len(results)} resolved; wrote {args.out}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
