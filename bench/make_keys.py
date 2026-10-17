"""Derive the bench answer keys from the raw primary records.

Run standalone (`python bench/make_keys.py`) or through `python -m ratified.bench`.
The script reads `bench/questions.json`, applies the named rule to the cached raw
bytes of the authoritative source, and writes `bench/keys.json` with the key and
its derivation (source URL, record, rule, evidence).

It must never import `ratified` and never connect to FalkorDB: the point of the
bench is that the keys are established without the system under test. The guard at
the bottom of `main` fails loudly if that ever stops being true.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:  # python -m bench.make_keys / import bench.make_keys
    from . import sources
except ImportError:  # python bench/make_keys.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sources  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = Path(__file__).resolve().parent / "questions.json"
KEYS = Path(__file__).resolve().parent / "keys.json"


class RuleError(RuntimeError):
    pass


def _section_number_for_heading(params: dict) -> tuple[object, dict]:
    heading = params["heading"].strip().lower()
    rfc = sources.rfc_sections()
    hits = sorted((n for n, s in rfc.items() if s["title"].strip().lower() == heading), key=len)
    if not hits:
        raise RuleError(f"no RFC 8446 heading matches {heading!r}")
    if len(hits) > 1:
        raise RuleError(f"{heading!r} is ambiguous in RFC 8446: {hits}")
    number = hits[0]
    return number, {
        "record": f"{sources.RFC_TXT_URL} numbered headings",
        "rule": "exact case-insensitive heading match -> section number",
        "evidence": {"heading": rfc[number]["title"], "number": number,
                     "rfc_heading_count": len(rfc)},
    }


def _latest_revision(params: dict) -> tuple[object, dict]:
    name = params["name"]
    revs = sources.revisions(name)
    if not revs:
        raise RuleError(f"no dochistory revisions cached for {name}")
    latest = revs[-1]
    return f"{name}-{latest}", {
        "record": f"{sources.BASE}/api/v1/doc/dochistory/ (objects with name={name})",
        "rule": "maximum revision label by (length, lexical) order",
        "evidence": {"n_revisions": len(revs), "revs": revs},
    }


def _became_rfc_of(params: dict) -> tuple[object, dict]:
    name = params["name"]
    mapping = sources.became_rfc()
    target = mapping.get(name)
    if not target:
        raise RuleError(f"{name} has no became_rfc target in the datatracker record")
    return target, {
        "record": f"{sources.BASE}/api/v1/doc/relateddocument/?relationship__slug=became_rfc",
        "rule": "source -> target for the requested draft",
        "evidence": {"target": target, "n_pairs": len(mapping)},
    }


def _revision_ids_between(params: dict) -> tuple[object, dict]:
    name, lo, hi = params["name"], int(params["lo"]), int(params["hi"])
    ids = [f"{name}-{rev}" for rev in sources.revisions(name) if lo <= int(rev) <= hi]
    if not ids:
        raise RuleError(f"no revisions of {name} between {lo} and {hi}")
    return ids, {
        "record": f"{sources.BASE}/api/v1/doc/dochistory/ (objects with name={name})",
        "rule": f"revision labels with {lo} <= int(rev) <= {hi}, ascending",
        "evidence": {"n_ids": len(ids), "ids": ids},
    }


def _chairs(params: dict) -> tuple[object, dict]:
    role = params["role"]
    people = sources.roles(role)
    if not people:
        raise RuleError(f"no datatracker roles cached for role={role}")
    names = sorted(p["name"] for p in people)
    return names, {
        "record": f"{sources.BASE}/api/v1/group/role/?group=1326&name={role}",
        "rule": "local part of each role holder's registered email",
        "evidence": {"people": people},
    }


def _threads_naming(params: dict) -> tuple[object, dict]:
    needle = params["needle"]
    rows = sources.browse_rows()
    threads = sorted({row["thread"] for row in rows if needle in row["subject"]})
    if not threads:
        raise RuleError(f"no archive subject mentions {needle}")
    return threads, {
        "record": f"{sources.ARCHIVE}/arch/browse/{sources.LIST}/ (row subject + thread columns)",
        "rule": "distinct thread ids whose subject contains the needle",
        "evidence": {"n_threads": len(threads), "threads": threads,
                     "n_rows": len(rows)},
    }


def _count_became_rfc(params: dict) -> tuple[object, dict]:
    mapping = sources.became_rfc()
    return len(mapping), {
        "record": f"{sources.BASE}/api/v1/doc/relateddocument/?relationship__slug=became_rfc",
        "rule": "count of distinct draft-ietf-tls-* sources with a became_rfc target",
        "evidence": {"sources": sorted(mapping)},
    }


def _count_thread_messages(params: dict) -> tuple[object, dict]:
    thread = params["thread"]
    rows = sources.browse_rows()
    n = sum(1 for row in rows if row["thread"] == thread)
    if not n:
        raise RuleError(f"thread {thread} has no rows in the cached browse pages")
    return n, {
        "record": f"{sources.ARCHIVE}/arch/browse/{sources.LIST}/ (row thread column)",
        "rule": "count of browse rows carrying the requested thread id",
        "evidence": {"thread": thread, "n_rows_total": len(rows)},
    }


def _count_revisions(params: dict) -> tuple[object, dict]:
    name = params["name"]
    revs = sources.revisions(name)
    return len(revs), {
        "record": f"{sources.BASE}/api/v1/doc/dochistory/ (objects with name={name})",
        "rule": "count of distinct revision labels",
        "evidence": {"revs": revs},
    }


def _abstain(params: dict) -> tuple[object, dict]:
    """A negative key: prove from the primary source that the answer does not exist."""
    reason = params["reason"]
    rfc = sources.rfc_sections()
    evidence: dict = {"reason": reason}
    if "9.4" in reason:
        titles = {s["title"].lower(): n for n, s in rfc.items()}
        if "9.4" in rfc:
            raise RuleError("RFC 8446 does contain a section 9.4; the question is answerable")
        evidence["rfc_has_section_9_4"] = False
        evidence["protocol_invariants_at"] = titles.get("protocol invariants")
    evidence["rfc_heading_count"] = len(rfc)
    return None, {
        "record": f"{sources.RFC_TXT_URL} + the ingested record's own scope",
        "rule": "absence in the primary source: the key is that no answer exists",
        "evidence": evidence,
    }


RULES = {
    "section_number_for_heading": _section_number_for_heading,
    "latest_revision": _latest_revision,
    "became_rfc_of": _became_rfc_of,
    "revision_ids_between": _revision_ids_between,
    "chairs": _chairs,
    "threads_naming": _threads_naming,
    "count_became_rfc": _count_became_rfc,
    "count_thread_messages": _count_thread_messages,
    "count_revisions": _count_revisions,
    "abstain": _abstain,
}


def atoms_for(answer_kind: str, value) -> list[str]:
    if answer_kind == "abstain":
        return []
    if answer_kind == "list":
        return [str(item) for item in value]
    return [str(value)]


def build(questions_path: Path = QUESTIONS) -> dict:
    questions = json.loads(questions_path.read_text())
    keys: dict[str, dict] = {}
    for question in questions:
        rule = RULES.get(question["rule"])
        if rule is None:
            raise RuleError(f"unknown rule {question['rule']!r} for question {question['id']}")
        value, derivation = rule(question.get("params") or {})
        keys[question["id"]] = {
            "id": question["id"],
            "category": question["category"],
            "question": question["q"],
            "answer_kind": question["answer_kind"],
            "key": value,
            "atoms": atoms_for(question["answer_kind"], value),
            "authoritative_source": question["source"],
            "derivation": derivation,
            "rag_answerable": bool(question.get("rag_answerable")),
        }
    return {
        "meta": {
            "derived_from": "cache/http — the raw responses served by the authoritative sources",
            "cache_dir": str(sources.CACHE_DIR),
            "rfc": sources.RFC,
            "draft": sources.DRAFT,
            "list": sources.LIST,
            "n_questions": len(keys),
            "categories": _categories(keys),
            "record_counts": {
                "browse_rows": len(sources.browse_rows()),
                "threads": len({r["thread"] for r in sources.browse_rows()}),
                "message_downloads": len(sources.message_downloads()),
                "rfc_sections": len(sources.rfc_sections()),
                "draft_revisions": len(sources.revisions()),
                "became_rfc": len(sources.became_rfc()),
            },
        },
        "keys": keys,
    }


def _categories(keys: dict[str, dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in keys.values():
        counts[key["category"]] = counts.get(key["category"], 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive the bench answer keys from raw sources.")
    parser.add_argument("--out", default=str(KEYS))
    parser.add_argument("--print", action="store_true", dest="show")
    args = parser.parse_args(argv)

    if "ratified" in sys.modules:
        raise SystemExit(
            "bench/make_keys.py imported the product (ratified) — keys must be independent of "
            "the system under test"
        )
    record = build()
    Path(args.out).write_text(json.dumps(record, indent=2) + "\n")
    print(f"wrote {args.out} — {record['meta']['n_questions']} keys, {record['meta']['categories']}")
    if args.show:
        print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
