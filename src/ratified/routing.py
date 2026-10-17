"""Map a free-text question to one catalogue tool and its argument, with no LLM.

The router is deterministic and shaped: a question is classified into one of the
known shapes — single-lookup, collect, aggregate or unanswerable — by explicit
keyword rules, and each shape names exactly one catalogue tool with its argument.
A shape the ingested graph cannot answer (the IESG-ballot / meeting-minutes
questions) routes to the reserved ``no_answer`` sentinel, which renders the same
"the graph does not know" card the app already uses rather than bluffing.

The LLM is never required to pick a tool; when it is enabled it is used only to
phrase the result, and it is consulted as a tie-breaker solely when no shape rule
matches (`route_ex` then returns `tied=True`). That tie-break call is cached by
(model, prompt, graph-hash) like every other LLM call.
"""
from __future__ import annotations

import re

from .ingest import LIST as DEFAULT_WG
from .tools import DEFAULT_DRAFT, NO_ANSWER, NOT_UNDERSTOOD

DRAFT_RE = re.compile(r"(draft-[a-z0-9-]+)")
NUMBER_RE = re.compile(r"(?:section|§)\s*(\d+(?:\.\d+)*)", re.I)
MESSAGE_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9_-]{13,})")
HEADING_RE = re.compile(r"(?<![A-Za-z])['\"“”‘’]([^'\"“”‘’]{2,})['\"“”‘’](?![A-Za-z])")
THREAD_RE = re.compile(r"\b([a-z][a-z0-9-]*:\d+)\b", re.I)
REV_RANGE_RE = re.compile(
    r"(?:revision[s]?\s*)?(?<![A-Za-z0-9])#?-?(\d{1,4})\s*(?:to|through|and|–|—|-)\s*#?-?(\d{1,4})\b", re.I
)

HERO_WORDS = (
    "unresolved", "never resolved", "argued against", "aggregate", "objection", "settle",
    "left open", "never closed", "never formally closed",
)
SYNC_WORDS = ("sync", "up to date", "fresh", "how current")
PRECEDENT_WORDS = ("precedent", "trace", "why")
WHY_WORDS = (
    "why", "how come", "reason", "story behind", "backstory", "where did", "wording", "worded",
    "phrased", "written", "reads", "read the way", "who do i ask", "who should i ask", "who to ask",
    "who should i talk", "who should i ping", "reasoning",
)
REVISION_WORDS = ("revision", "revised")
BECAME_WORDS = ("become", "became", "turn into", "turned into", "ended up as")
CHAIR_WORDS = ("chair", "who runs", "who leads", "leading the", "steering", "in charge of")
WHO_DISCUSSED_WORDS = ("took part", "participated", "whose messages", "who posted", "who discussed", "who talked")
WHO_KNOWS_WORDS = ("who knows", "key people", "most influential", "central", "expert", "most active", "who matters")
SEARCH_WORDS = (
    "say about", "said about", "says about", "talk about", "talked about", "discussion of", "discussions of",
    "discussions about", "opinions on", "mentioned", "anyone mention", "search",
)
SECTION_WORDS = ("what happened", "clause", "section", "changed", "§")
LATEST_WORDS = ("latest", "newest", "most recent")
COUNT_WORDS = ("how many", "count", "number of")
OUT_OF_SCOPE_WORDS = ("iesg", "ballot", "minutes")


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


def extract_heading(question: str) -> str | None:
    match = HEADING_RE.search(question or "")
    return match.group(1).strip() if match else None


def extract_thread(question: str) -> str | None:
    match = THREAD_RE.search(question or "")
    return match.group(1) if match else None


def extract_needle(question: str) -> str | None:
    """The distinctive pattern a subject question names: a full draft id or a quoted phrase."""
    match = DRAFT_RE.search(question or "")
    if match:
        return match.group(1)
    return extract_heading(question)


def extract_revision_range(question: str) -> tuple[int | None, int | None]:
    match = REV_RANGE_RE.search(question or "")
    if not match:
        return None, None
    lo, hi = int(match.group(1)), int(match.group(2))
    return (lo, hi) if lo <= hi else (hi, lo)


def _out_of_scope(text: str) -> str:
    if "iesg" in text or "ballot" in text:
        return "IESG ballot positions"
    return "meeting minutes"


def route_ex(question: str) -> tuple[str, dict, bool]:
    """The deterministic route, plus whether no shape rule matched (a tie)."""
    text = (question or "").lower()
    draft = extract_draft(question)

    heading = extract_heading(question)
    if heading and ("heading" in text or "titled" in text):
        return "section_by_heading", {"draft": draft, "heading": heading}, False

    if any(word in text for word in REVISION_WORDS):
        lo, hi = extract_revision_range(question)
        count_intent = any(word in text for word in COUNT_WORDS) or "total" in text
        if count_intent:
            return "revisions", {"draft": draft, "count": True}, False
        if lo is not None and hi is not None:
            return "revisions", {"draft": draft, "lo": lo, "hi": hi}, False
        if any(word in text for word in LATEST_WORDS):
            return "revisions", {"draft": draft, "latest": True}, False
        return "revisions", {"draft": draft}, False

    if any(word in text for word in OUT_OF_SCOPE_WORDS):
        return NO_ANSWER, {"scope": _out_of_scope(text)}, False

    if any(word in text for word in BECAME_WORDS):
        if any(word in text for word in COUNT_WORDS):
            return "count_became", {"draft": draft}, False
        return "became_rfc", {"draft": draft}, False

    if any(word in text for word in CHAIR_WORDS):
        return "chairs", {"wg": DEFAULT_WG}, False

    thread = extract_thread(question)
    if "thread" in text and ("subject" in text or "mention" in text):
        needle = extract_needle(question)
        if needle:
            return "threads_by_subject", {"pattern": needle}, False

    if thread and "thread" in text and any(word in text for word in COUNT_WORDS):
        return "count_thread_messages", {"thread_or_draft": thread}, False

    number = extract_number(question)
    if any(word in text for word in WHY_WORDS) and (number or heading):
        if number:
            return "why_clause", {"number": number, "draft": draft}, False
        return "why_clause", {"heading": heading, "draft": draft}, False
    if number and any(word in text for word in SECTION_WORDS):
        return "what_happened_to", {"number": number}, False
    if any(word in text for word in HERO_WORDS):
        return "aggregate_unresolved", {"draft": draft}, False
    if ("argu" in text and ("who" in text or "people" in text)) or any(word in text for word in WHO_DISCUSSED_WORDS):
        return "who_argued", {"draft": draft}, False
    if any(word in text for word in WHO_KNOWS_WORDS):
        return "who_knows", {}, False
    if any(word in text for word in SEARCH_WORDS):
        return "search_discussion", {"text": question}, False
    if any(word in text for word in PRECEDENT_WORDS):
        message = extract_message(question)
        if message:
            return "precedent", {"message_id": message}, False
    if any(word in text for word in WHY_WORDS):
        return "why_clause", {"topic": question, "draft": draft}, False
    if any(word in text for word in SYNC_WORDS):
        return "sync", {"days": 1}, False
    return NOT_UNDERSTOOD, {}, True


def route(question: str) -> tuple[str, dict]:
    tool, arguments, _ = route_ex(question)
    return tool, arguments
