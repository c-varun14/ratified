"""Parse IETF text sections and align draft sections to an RFC by heading text.

Same-number alignment is only correct while numbering happens not to move, and
numbering does move when sections are inserted or removed between revisions. A
draft section is therefore aligned to the RFC section carrying the same
normalised heading text; ancestor-heading paths and immediate parents break
ties, and an unresolvable heading is left unmatched rather than guessed.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter

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
