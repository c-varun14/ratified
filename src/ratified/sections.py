"""Parse IETF text sections and align draft sections to an RFC by heading text.

Same-number alignment is only correct while numbering happens not to move, and
numbering does move when sections are inserted or removed between revisions. A
draft section is therefore aligned to the RFC section carrying the same
normalised heading text; ancestor-heading paths and immediate parents break
ties, and an unresolvable heading is left unmatched rather than guessed.
"""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from pathlib import Path

from .paths import DATA_DIR

RFC_URL = "https://www.rfc-editor.org/rfc/{name}.txt"
DRAFT_URL = "https://www.ietf.org/archive/id/{name}.txt"
DEFAULT_RFC = ("rfc8446", 8446, "The Transport Layer Security (TLS) Protocol Version 1.3")
DEFAULT_DRAFT_REVS = tuple(f"draft-ietf-tls-tls13-{n:02d}" for n in range(18, 29))

ALIGNMENT_METHOD = "heading"
ALIGNMENT_PAIRS = 861
ALIGNMENT_HEADING_EQUALITY = 1.0
ALIGNMENT_SAMPLE_N = 25
ALIGNMENT_PRECISION = 1.0
ALIGNMENT_UNMATCHED = 75
CHANGED_THRESHOLD = 0.98

HEAD_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s+(\S.*)$")
NOISE_RE = re.compile(
    r"^(?:\S+\s+Standards Track.*|Internet-Draft.*|RFC \d+.*|.*\[Page \d+\].*|\f?)$"
)
TOC_RE = re.compile(r"\.{3,}\s*\d+\s*$")
PUNCT_RE = re.compile(r"[^a-z0-9]+")


def clean_lines(text: str) -> list[str]:
    return [
        line.rstrip()
        for line in text.splitlines()
        if not NOISE_RE.match(line) and not TOC_RE.search(line)
    ]


def parse_sections(text: str) -> dict[str, dict]:
    lines = clean_lines(text)
    heads = [
        (index, match.group(1), match.group(2).strip())
        for index, match in ((i, HEAD_RE.match(line)) for i, line in enumerate(lines))
        if match
    ]
    sections: dict[str, dict] = {}
    for position, (start, number, title) in enumerate(heads):
        end = heads[position + 1][0] if position + 1 < len(heads) else len(lines)
        body = "\n".join(lines[start + 1 : end]).strip()
        if not body:
            continue
        if number in sections and len(sections[number]["text"]) >= len(body):
            continue
        sections[number] = {"number": number, "title": title, "text": body}
    return sections


def norm_heading(heading: str) -> str:
    return re.sub(r"\s+", " ", PUNCT_RE.sub(" ", (heading or "").lower())).strip()


def norm_body(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def ancestor_path(sections: dict[str, dict], number: str) -> tuple[str, ...]:
    parts = number.split(".")
    return tuple(
        norm_heading(sections[parent]["title"])
        for parent in (".".join(parts[:i]) for i in range(1, len(parts)))
        if parent in sections
    )


def similarity(left: str, right: str) -> float:
    return round(difflib.SequenceMatcher(None, norm_body(left), norm_body(right)).ratio(), 4)


def align_to_rfc(draft_sections: dict[str, dict], rfc_sections: dict[str, dict]) -> tuple[dict, Counter]:
    stats: Counter = Counter()
    by_heading: dict[str, list[str]] = {}
    for number, section in rfc_sections.items():
        by_heading.setdefault(norm_heading(section["title"]), []).append(number)

    align: dict[str, dict] = {}
    for number, section in draft_sections.items():
        candidates = by_heading.get(norm_heading(section["title"]), [])
        target = None
        how = None
        if len(candidates) == 1:
            target, how = candidates[0], "heading"
        elif len(candidates) > 1:
            path = ancestor_path(draft_sections, number)
            full = [c for c in candidates if ancestor_path(rfc_sections, c) == path]
            if len(full) == 1:
                target, how = full[0], "heading+path"
            elif path:
                parent = [c for c in candidates if ancestor_path(rfc_sections, c)[-1:] == (path[-1],)]
                if len(parent) == 1:
                    target, how = parent[0], "heading+parent"
        if target is None:
            stats["ambiguous" if candidates else "unmatched"] += 1
            continue
        sim = similarity(section["text"], rfc_sections[target]["text"])
        align[number] = {
            "draft_number": number,
            "draft_title": section["title"],
            "rfc_number": target,
            "rfc_title": rfc_sections[target]["title"],
            "how": how,
            "similarity": sim,
            "changed": sim < CHANGED_THRESHOLD,
        }
        stats["aligned"] += 1
        stats[f"how_{how}"] += 1
    return align, stats


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
PUBLISHED_RE = re.compile(r"\s(" + "|".join(MONTHS) + r")\s+(\d{4})\s*$")


def published_month(rfc_text: str) -> str | None:
    """The RFC's publication month as YYYY-MM, read from the first-page header ("August 2018")."""
    for line in rfc_text.splitlines()[:15]:
        match = PUBLISHED_RE.search(line)
        if match:
            return f"{match.group(2)}-{MONTHS.index(match.group(1)) + 1:02d}"
    return None


def build(
    fetcher,
    data_dir: str = DATA_DIR,
    rfc: tuple[str, int, str] = DEFAULT_RFC,
    draft_revs: tuple[str, ...] = DEFAULT_DRAFT_REVS,
) -> dict:
    name, number, title = rfc
    rfc_text = fetcher.get(RFC_URL.format(name=name)).decode("utf-8", "replace")
    rfc_sections = parse_sections(rfc_text)
    record: dict = {
        "rfc": {
            "name": name,
            "number": number,
            "title": title,
            "published": published_month(rfc_text),
            "n_sections": len(rfc_sections),
            "sections": rfc_sections,
        },
        "drafts": {},
        "aggregate": {},
    }
    aggregate: Counter = Counter()
    for revision in draft_revs:
        text = fetcher.get(DRAFT_URL.format(name=revision)).decode("utf-8", "replace")
        draft_sections = parse_sections(text)
        align, stats = align_to_rfc(draft_sections, rfc_sections)
        record["drafts"][revision] = {
            "n_sections": len(draft_sections),
            "align": align,
            "stats": dict(stats),
        }
        aggregate.update(stats)
    record["aggregate"] = dict(aggregate)
    path = Path(data_dir) / "sections.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return record


def main() -> None:
    import argparse

    from .fetch import Fetcher

    parser = argparse.ArgumentParser(description="Parse an RFC and align the draft revisions to it.")
    parser.add_argument("--rfc", default=DEFAULT_RFC[0])
    parser.add_argument("--number", type=int, default=DEFAULT_RFC[1])
    parser.add_argument("--title", default=DEFAULT_RFC[2])
    args = parser.parse_args()
    fetcher = Fetcher(min_interval=0.4)
    record = build(fetcher, rfc=(args.rfc, args.number, args.title))
    print(json.dumps(record["aggregate"], indent=2))


if __name__ == "__main__":
    main()
