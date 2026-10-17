"""Map a free-text question to one catalogue tool and its argument, with no LLM.

This is the tool-mode router: deterministic, so the page works with the LLM
disabled. The LLM, when enabled, only has to pick the same tool and phrase it.
"""
from __future__ import annotations

import re

from .tools import DEFAULT_DRAFT

DRAFT_RE = re.compile(r"(draft-[a-z0-9-]+)")
NUMBER_RE = re.compile(r"(?:section|§)\s*(\d+(?:\.\d+)*)", re.I)
MESSAGE_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9_-]{13,})")


def extract_draft(question: str) -> str:
    match = DRAFT_RE.search(question)
    if not match:
        return DEFAULT_DRAFT
    return re.sub(r"-\d{2}$", "", match.group(1))


def extract_number(question: str) -> str | None:
    match = NUMBER_RE.search(question)
    if match:
        return match.group(1)
    match = re.search(r"\b(\d+(?:\.\d+)+)\b", question)
    return match.group(1) if match else None


def extract_message(question: str) -> str | None:
    match = MESSAGE_RE.search(question)
    return match.group(1) if match else None


def route(question: str) -> tuple[str, dict]:
    text = (question or "").lower()
    if any(word in text for word in ("unresolved", "never resolved", "argued against", "aggregate", "objection", "settle")):
        return "aggregate_unresolved", {"draft": extract_draft(question)}
    if "argu" in text and ("who" in text or "people" in text):
        return "who_argued", {"draft": extract_draft(question)}
    if any(word in text for word in ("precedent", "trace", "why")):
        message = extract_message(question)
        if message:
            return "precedent", {"message_id": message}
        return "aggregate_unresolved", {"draft": extract_draft(question)}
    if any(word in text for word in ("sync", "current", "latest", "fresh", "up to date")):
        return "sync", {"days": 1}
    number = extract_number(question)
    if number and any(word in text for word in ("what happened", "clause", "section", "changed", "§")):
        return "what_happened_to", {"number": number}
    return "aggregate_unresolved", {"draft": extract_draft(question)}
