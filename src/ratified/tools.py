"""The fixed tool catalogue: each tool runs Cypher and returns an answer card.

Every claim carries mechanical permalink chips derived from node properties
(thread id, message id, draft revision, RFC section anchor). Nothing here calls
an LLM, and no LLM output can become a citation.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from . import ingest, mail, viz
from .fetch import Fetcher
from .graph import rows
from .paths import DATA_DIR

DEFAULT_DRAFT = "draft-ietf-tls-tls13"

TOPIC_LINK_PRECISION = "9 of 52 decided links (17.3%; 36 ties)"

BROWSE_BASE = "https://mailarchive.ietf.org/arch/browse"
SYNC_PAGES = 3
SYNC_BODY_CAP = 20
CACHE_LIFETIME = 6 * 3600

OUTCOME_ANSWER = "answer"
OUTCOME_PARTIAL = "partial"
OUTCOME_UNKNOWN = "unknown"
OUTCOME_CONFLICT = "conflict"

OUTCOME_MESSAGE = {
    OUTCOME_ANSWER: "answer",
    OUTCOME_PARTIAL: "partial — some evidence is missing",
    OUTCOME_UNKNOWN: "the graph does not know",
    OUTCOME_CONFLICT: "conflict — the record disagrees with itself",
}

TOOL_CATALOGUE = [
    {"name": "aggregate_unresolved", "args": ["draft"], "description": "clauses of a draft argued against with no resolution trail"},
    {"name": "who_argued", "args": ["draft"], "description": "people who argued about a draft, with their messages"},
    {"name": "what_happened_to", "args": ["number"], "description": "what happened to a clause across revisions and the RFC"},
    {"name": "precedent", "args": ["message_id"], "description": "trace a message to a revision and the RFC section it became"},
    {"name": "sync", "args": ["days"], "description": "how current the graph is, by record date"},
    {"name": "section_by_heading", "args": ["draft", "heading"], "description": "the section number a heading names, from the draft's RFC"},
    {"name": "revisions", "args": ["draft", "lo", "hi", "latest", "count"], "description": "a draft's revisions: list them, bound them to a range, count them, or name the latest"},
    {"name": "count_unresolved", "args": ["draft"], "description": "how many clauses of a draft are argued against with no resolution trail"},
]

CATALOGUE_BY_NAME = {tool["name"]: tool for tool in TOOL_CATALOGUE}


def thread_chip(thread_id, url):
    return {"kind": "thread", "label": thread_id, "url": url}


def message_chip(message_id, url):
    return {"kind": "message", "label": message_id, "url": url}


def revision_chip(revision):
    name, _, rev = revision.rpartition("-")
    path = f"{name}/{rev}" if name and rev.isdigit() else revision
    return {"kind": "revision", "label": revision, "url": f"https://datatracker.ietf.org/doc/{path}/"}


def section_chip(number, title, url):
    return {"kind": "section", "label": f"§{number} {title}", "url": url}


def rfc_chip(rfc_id, url=None):
    return {"kind": "rfc", "label": rfc_id, "url": url or f"https://www.rfc-editor.org/rfc/{rfc_id}.html"}


def card(tool, title, claims, rows_out=None, missing=None, conflicts=None, notes=None):
    chips, seen = [], set()
    for claim in claims:
        for chip in claim.get("chips", []):
            if chip["url"] not in seen:
                seen.add(chip["url"])
                chips.append(chip)
    conflicts = conflicts or []
    missing = missing or []
    if conflicts:
        outcome = OUTCOME_CONFLICT
    elif not claims:
        outcome = OUTCOME_UNKNOWN
    elif missing:
        outcome = OUTCOME_PARTIAL
    else:
        outcome = OUTCOME_ANSWER
    return {
        "tool": tool,
        "title": title,
        "outcome": outcome,
        "outcome_message": OUTCOME_MESSAGE[outcome],
        "claims": claims,
        "chips": chips,
        "rows": rows_out or [],
        "missing": missing,
        "conflicts": conflicts,
        "notes": notes or [],
    }


def _topic_link_note(count: int) -> str:
    return (
        f"{count} clause(s) below are leads, not objections: they carry no message citation and are matched only "
        f"by subject-token overlap, where hand-checking the links measured {TOPIC_LINK_PRECISION} correct"
    )


def aggregate_unresolved(graph, draft: str = DEFAULT_DRAFT):
    cited = rows(
        graph,
        """
        MATCH (d:Draft {id:$draft})-[:HAS_REVISION]->(dr:DraftRevision)-[al:ALIGNS_SECTION]->(s:Section)
        WHERE al.changed = true
        MATCH (m:Message)-[:DISCUSSED]->(dr)
        MATCH (m)-[:CITES]->(s)
        OPTIONAL MATCH (p:Person)-[:AUTHORED]->(m)
        OPTIONAL MATCH (m)-[:IN_THREAD]->(t:Thread)
        RETURN s.id AS sid, s.number AS number, s.title AS title, s.url AS url,
               collect(DISTINCT dr.id) AS revisions,
               collect(DISTINCT m.id) AS messages, collect(DISTINCT m.url) AS message_urls,
               collect(DISTINCT m.date) AS dates, collect(DISTINCT p.name) AS people,
               collect(DISTINCT t.id) AS threads, collect(DISTINCT t.url) AS thread_urls
        """,
        {"draft": draft},
    )
    about = rows(
        graph,
        """
        MATCH (d:Draft {id:$draft})-[:HAS_REVISION]->(dr:DraftRevision)-[al:ALIGNS_SECTION]->(s:Section)
        WHERE al.changed = true
        MATCH (t:Thread)-[:ABOUT_SECTION]->(s)
        RETURN s.id AS sid, s.number AS number, s.title AS title, s.url AS url,
               collect(DISTINCT dr.id) AS revisions,
               collect(DISTINCT t.id) AS threads, collect(DISTINCT t.url) AS thread_urls
        """,
        {"draft": draft},
    )

    clauses: dict[str, dict] = {}
    for row in cited:
        clause = clauses.setdefault(row["sid"], {**row, "buckets": set()})
        clause["buckets"].add("cited")
        for key in ("messages", "message_urls", "dates", "people", "threads", "thread_urls"):
            clause[key] = sorted(set(clause.get(key) or []) | set(row.get(key) or []))
    for row in about:
        clause = clauses.setdefault(
            row["sid"],
            {**row, "messages": [], "message_urls": [], "dates": [], "people": [], "buckets": set()},
        )
        clause["buckets"].add("topic")
        for key in ("revisions", "threads", "thread_urls"):
            clause[key] = sorted(set(clause.get(key) or []) | set(row.get(key) or []))

    if not clauses:
        return card(
            "aggregate_unresolved",
            f"Unresolved objections in {draft}",
            [],
            notes=[f"no clause of {draft} is linked to an objection in the graph"],
        )

    claims = []
    for clause in clauses.values():
        cited_bucket = "cited" in clause["buckets"]
        last_argued = max(clause.get("dates") or [""])
        later = rows(
            graph,
            "MATCH (m:Message)-[:CITES]->(s:Section {id:$sid}) WHERE m.date > $after RETURN count(m) AS n",
            {"sid": clause["sid"], "after": last_argued},
        )
        trail = later[0]["n"] if later else 0
        chips = [section_chip(clause["number"], clause["title"], clause["url"])]
        chips += [revision_chip(r) for r in sorted(clause.get("revisions") or [])]
        chips += [thread_chip(t, u) for t, u in zip(clause.get("threads") or [], clause.get("thread_urls") or [])]
        chips += [message_chip(m, u) for m, u in zip(clause.get("messages") or [], clause.get("message_urls") or [])]
        people = ", ".join(sorted(set(clause.get("people") or [])))
        label = f"§{clause['number']} {clause['title']}"
        if trail:
            text = f"{label} — a later citation trail exists ({trail} message(s) after {last_argued})"
        elif cited_bucket and people:
            text = f"{label} — argued against by {people}; no resolution trail found"
        elif cited_bucket:
            text = f"{label} — cited by {len(set(clause.get('messages') or []))} message(s); no resolution trail found"
        else:
            threads = len(set(clause.get("threads") or []))
            text = f"{label} — {threads} thread(s) matched this clause by subject tokens; no resolution trail found"
        claims.append(
            {
                "text": text,
                "unresolved": not trail,
                "attributed": cited_bucket and bool(people),
                "bucket": "cited" if cited_bucket else "topic",
                "sid": clause["sid"],
                "draft": draft,
                "chips": chips,
            }
        )

    claims.sort(key=lambda c: (c["bucket"] != "cited", not c["unresolved"], not c["attributed"], c["text"]))
    attributed = sum(1 for c in claims if c["unresolved"] and c["attributed"])
    leads = sum(1 for c in claims if c["bucket"] == "topic")
    title = f"{attributed} clauses of {draft} argued against, no resolution trail"
    notes = [_topic_link_note(leads)] if leads else []
    result = card(
        "aggregate_unresolved",
        title,
        claims,
        rows_out=[{"section": c["text"], "unresolved": c["unresolved"], "bucket": c["bucket"]} for c in claims],
        notes=notes,
    )
    result["explanation"] = (
        "This is the graph saying: people objected, and no later document trail says it was settled."
    )
    return result


CITED_PATH_Q = """
MATCH (s:Section {id:$sid})
MATCH (m:Message)-[:CITES]->(s)
MATCH (m)-[:DISCUSSED]->(dr:DraftRevision)
MATCH (dr)-[al:ALIGNS_SECTION]->(s)
MATCH (m)-[:IN_THREAD]->(t:Thread)
MATCH p=(dr)-[:SUPERSEDED*0..]->(last:DraftRevision)
MATCH (last)-[:BECAME]->(rfc:RFC)-[:HAS_SECTION]->(s)
WHERE al.changed = true
RETURN DISTINCT m.id AS mid, m.url AS murl, m.date AS date, m.subject AS subject,
       t.id AS tid, t.url AS turl,
       [n IN nodes(p) | n.id] AS chain, rfc.id AS rfc,
       s.number AS number, s.title AS title, s.url AS surl,
       al.similarity AS similarity, al.changed AS changed
ORDER BY m.date
"""

TOPIC_PATH_Q = """
MATCH (s:Section {id:$sid})
MATCH (t:Thread)-[ab:ABOUT_SECTION]->(s)
MATCH (m:Message)-[:IN_THREAD]->(t)
MATCH (m)-[:DISCUSSED]->(dr:DraftRevision)
MATCH (dr)-[al:ALIGNS_SECTION]->(s)
MATCH p=(dr)-[:SUPERSEDED*0..]->(last:DraftRevision)
MATCH (last)-[:BECAME]->(rfc:RFC)-[:HAS_SECTION]->(s)
WHERE al.changed = true
RETURN DISTINCT t.id AS tid, t.url AS turl, ab.matched_tokens AS tokens,
       m.id AS mid, m.url AS murl, m.date AS date,
       [n IN nodes(p) | n.id] AS chain, rfc.id AS rfc,
       s.number AS number, s.title AS title, s.url AS surl, al.similarity AS similarity
ORDER BY m.date
"""


def _path_steps(row: dict) -> list[dict]:
    steps = [
        message_chip(row["mid"], row["murl"]),
        thread_chip(row["tid"], row["turl"]),
    ]
    steps += [revision_chip(revision) for revision in (row.get("chain") or [])]
    steps.append(rfc_chip(row["rfc"]))
    steps.append(section_chip(row["number"], row["title"], row["surl"]))
    return steps


def clause_receipt(graph, draft: str, sid: str):
    """The full traced path for one clause as ordered lists of mechanical permalinks.

    object -> thread -> draft revision -> SUPERSEDED hops -> RFC section. Citation
    objects come first; subject-token threads follow, labelled as such.
    """
    cited = rows(graph, CITED_PATH_Q, {"sid": sid})
    topic = rows(graph, TOPIC_PATH_Q, {"sid": sid})
    all_revisions = [
        row["id"]
        for row in rows(
            graph,
            "MATCH (d:Draft {id:$draft})-[:HAS_REVISION]->(r:DraftRevision) "
            "RETURN r.id AS id, r.date AS date ORDER BY r.date",
            {"draft": draft},
        )
    ]
    all_threads = [
        row["id"]
        for row in rows(
            graph,
            "MATCH (t:Thread)-[:ABOUT_SECTION]->(s:Section {id:$sid}) RETURN t.id AS id",
            {"sid": sid},
        )
    ]
    entries = [("cited in message", row) for row in cited]
    seen: set[str] = set()
    for row in topic:
        if row["tid"] in seen:
            continue
        seen.add(row["tid"])
        entries.append((f"thread matched by subject tokens ({row['tokens']})", row))

    paths = []
    for via, row in entries:
        steps = _path_steps(row)
        chain = [revision for revision in (row.get("chain") or [])]
        paths.append(
            {
                "via": via,
                "similarity": row["similarity"],
                "steps": steps,
                "svg": viz.path_svg(
                    steps,
                    [revision for revision in all_revisions if revision not in chain],
                    [thread for thread in all_threads if thread != row["tid"]],
                ),
            }
        )
    return {"draft": draft, "sid": sid, "paths": paths}


def who_argued(graph, draft: str = DEFAULT_DRAFT):
    people = rows(
        graph,
        """
        MATCH (d:Draft {id:$draft})-[:HAS_REVISION]->(dr:DraftRevision)
        MATCH (m:Message)-[:DISCUSSED]->(dr)
        OPTIONAL MATCH (p:Person)-[:AUTHORED]->(m)
        OPTIONAL MATCH (m)-[:IN_THREAD]->(t:Thread)
        RETURN coalesce(p.name, m.from) AS person,
               count(DISTINCT m) AS n,
               collect(DISTINCT m.id) AS messages, collect(DISTINCT m.url) AS message_urls,
               collect(DISTINCT t.id) AS threads, collect(DISTINCT t.url) AS thread_urls
        ORDER BY n DESC, person
        """,
        {"draft": draft},
    )
    if not people:
        return card("who_argued", f"Who argued about {draft}", [], notes=[f"no message in the graph discusses {draft}"])
    claims = []
    for person in people:
        chips = [message_chip(m, u) for m, u in zip(person["messages"], person["message_urls"])]
        chips += [thread_chip(t, u) for t, u in zip(person["threads"], person["thread_urls"])]
        claims.append({"text": f"{person['person']} — {person['n']} messages", "chips": chips})
    return card("who_argued", f"Who argued about {draft}", claims, rows_out=people)


def what_happened_to(graph, number: str):
    alignments = rows(
        graph,
        """
        MATCH (dr:DraftRevision)-[al:ALIGNS_SECTION]->(s:Section {number:$number})
        OPTIONAL MATCH (dr)-[:SUPERSEDED*0..]->(last:DraftRevision)-[:BECAME]->(rfc:RFC)-[:HAS_SECTION]->(s)
        RETURN DISTINCT dr.id AS revision, al.similarity AS similarity, al.changed AS changed, al.how AS how,
               s.title AS title, s.url AS url, s.number AS number, rfc.id AS rfc
        ORDER BY dr.id
        """,
        {"number": number},
    )
    if not alignments:
        return card(
            "what_happened_to",
            f"What happened to §{number}",
            [],
            notes=[f"§{number} is not aligned to any draft revision in the graph"],
        )
    claims = []
    for row in alignments:
        chips = [revision_chip(row["revision"]), section_chip(row["number"], row["title"], row["url"])]
        if row.get("rfc"):
            chips.append(rfc_chip(row["rfc"]))
        verdict = "changed" if row["changed"] else "unchanged"
        claims.append(
            {
                "text": f"{row['revision']} → §{row['number']} {row['title']} ({verdict}, similarity {row['similarity']}, {row['how']})",
                "chips": chips,
            }
        )
    return card("what_happened_to", f"What happened to §{number}", claims, rows_out=alignments)


def precedent(graph, message_id: str):
    paths = rows(
        graph,
        """
        MATCH (m:Message)-[:DISCUSSED]->(dr:DraftRevision)
        MATCH (m)-[:CITES]->(s:Section)
        MATCH (dr)-[al:ALIGNS_SECTION]->(s)
        MATCH p=(dr)-[:SUPERSEDED*0..]->(last:DraftRevision)-[:BECAME]->(rfc:RFC)-[:HAS_SECTION]->(s)
        WHERE al.changed = true AND (m.id = $mid OR m.url = $mid OR m.message_id = $mid)
        RETURN DISTINCT m.id AS message, m.date AS date, m.url AS message_url, m.subject AS subject,
               dr.id AS revision, length(p) AS hops, rfc.id AS rfc,
               s.id AS sid, s.number AS number, s.title AS section_title, s.url AS section_url,
               al.similarity AS similarity
        ORDER BY m.date
        """,
        {"mid": message_id},
    )
    if not paths:
        return card(
            "precedent",
            f"Precedent for {message_id}",
            [],
            notes=[f"no message {message_id} cites a section whose clause changed on the way to an RFC"],
        )
    missing = []
    if any(not p.get("date") for p in paths):
        missing.append("some contributing messages have no date in the record")
    conflicts = []
    sections = sorted({p["sid"] for p in paths})
    if len(sections) > 1:
        conflicts.append(f"the citation resolves to more than one changed clause: {', '.join(sections)}")
    claims = []
    for path in paths:
        chips = [
            message_chip(path["message"], path["message_url"]),
            revision_chip(path["revision"]),
            rfc_chip(path["rfc"]),
            section_chip(path["number"], path["section_title"], path["section_url"]),
        ]
        claims.append(
            {
                "text": (
                    f"{path['message']} ({path['date']}) → {path['revision']} → "
                    f"{path['rfc']} §{path['number']} {path['section_title']} "
                    f"({path['hops']} revision hops, similarity {path['similarity']})"
                ),
                "chips": chips,
            }
        )
    return card("precedent", f"Precedent for {message_id}", claims, rows_out=paths, missing=missing, conflicts=conflicts)


def section_by_heading(graph, draft: str = DEFAULT_DRAFT, heading: str = ""):
    """The section number a heading names. Scoped to the RFC the draft became."""
    heading = (heading or "").strip()
    hits = rows(
        graph,
        """
        MATCH (d:Draft {id:$draft})-[:HAS_REVISION]->(:DraftRevision)-[:BECAME]->(rfc:RFC)
              -[:HAS_SECTION]->(s:Section)
        WHERE toLower(s.title) = toLower($heading)
        RETURN s.number AS number, s.title AS title, s.url AS url ORDER BY s.number
        """,
        {"draft": draft, "heading": heading},
    )
    scoped = bool(hits)
    if not hits:
        hits = rows(
            graph,
            "MATCH (s:Section) WHERE toLower(s.title) = toLower($heading) "
            "RETURN s.number AS number, s.title AS title, s.url AS url ORDER BY s.number",
            {"heading": heading},
        )
    if not hits:
        result = card(
            "section_by_heading",
            f'Section for heading "{heading}"',
            [],
            notes=[f'no section in the graph carries the heading "{heading}"'],
        )
        result["answer"] = None
        return result
    claims = [
        {"text": f'§{hit["number"]} {hit["title"]}', "chips": [section_chip(hit["number"], hit["title"], hit["url"])]}
        for hit in hits
    ]
    title = f'§{hits[0]["number"]} — {hits[0]["title"]}' if len(hits) == 1 else f'{len(hits)} sections carry the heading "{heading}"'
    result = card("section_by_heading", title, claims, rows_out=hits)
    result["answer"] = hits[0]["number"] if len(hits) == 1 else [hit["number"] for hit in hits]
    if not scoped:
        result["notes"].append(f"matched the RFC sections directly; {draft} has no RFC link in the graph")
    return result


def _revision_number(rev) -> int | None:
    try:
        return int(rev)
    except (TypeError, ValueError):
        return None


def revisions(graph, draft: str = DEFAULT_DRAFT, lo=None, hi=None, latest: bool = False, count: bool = False):
    """A draft's revisions: the list, a range of it, its count, or the latest one."""
    all_revs = rows(
        graph,
        "MATCH (d:Draft {id:$draft})-[:HAS_REVISION]->(r:DraftRevision) "
        "RETURN r.id AS id, r.rev AS rev, r.date AS date ORDER BY toInteger(r.rev), r.id",
        {"draft": draft},
    )
    low = _revision_number(lo)
    high = _revision_number(hi)
    selected = [
        row for row in all_revs
        if (low is None or (_revision_number(row["rev"]) is not None and _revision_number(row["rev"]) >= low))
        and (high is None or (_revision_number(row["rev"]) is not None and _revision_number(row["rev"]) <= high))
    ]
    if not selected:
        result = card("revisions", f"Revisions of {draft}", [], notes=[f"no revision of {draft} matches the request"])
        result["answer"] = None
        return result
    ids = [row["id"] for row in selected]
    claims = [
        {"text": row["id"] + (f' ({row["date"]})' if row.get("date") else ""), "chips": [revision_chip(row["id"])]}
        for row in selected
    ]
    if count:
        answer, title = len(ids), f"{len(ids)} revisions of {draft}"
    elif latest:
        answer, title = ids[-1], f"Latest revision of {draft} — {ids[-1]}"
    else:
        answer, title = ids, f"Revisions of {draft} ({len(ids)})"
    result = card(
        "revisions",
        title,
        claims,
        rows_out=[{"id": row["id"], "rev": row["rev"], "date": row["date"]} for row in selected],
    )
    result["answer"] = answer
    result["count"] = len(ids)
    result["latest"] = ids[-1]
    return result


def count_unresolved(graph, draft: str = DEFAULT_DRAFT):
    """How many clauses of a draft are argued against with no resolution trail."""
    aggregate = aggregate_unresolved(graph, draft)
    cited = [claim for claim in aggregate["claims"] if claim.get("bucket") == "cited" and claim.get("unresolved")]
    leads = [claim for claim in aggregate["claims"] if claim.get("bucket") == "topic"]
    count = len(cited)
    claims = [{"text": claim["text"], "chips": claim["chips"]} for claim in cited]
    notes = list(aggregate.get("notes") or [])
    if leads:
        notes.append(f"{len(leads)} further clause(s) are subject-token leads, counted separately from the {count} cited here")
    result = card(
        "count_unresolved",
        f"{count} clauses of {draft} argued against, no resolution trail",
        claims,
        rows_out=[{"section": claim["text"]} for claim in cited],
        notes=notes,
    )
    result["answer"] = count
    result["count"] = count
    return result


class SyncDeferred(RuntimeError):
    """Raised when mailarchive cannot be re-fetched and the cache cannot stand in."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _fetch_window(fetcher, list_name: str, since: str) -> tuple[list[dict], bool]:
    window: list[dict] = []
    seen: set[str] = set()
    from_cache = False
    for page in range(1, SYNC_PAGES + 1):
        url = f"{BROWSE_BASE}/{list_name}/?page={page}"
        try:
            body = fetcher.get(url, use_cache=False)
        except Exception:
            if fetcher.offline:
                raise SyncDeferred("offline")
            age = fetcher.cache_age(url)
            if age is None or age > CACHE_LIFETIME:
                raise SyncDeferred("rate limit")
            body = fetcher.get(url)
            from_cache = True
        page_rows = mail.parse_rows(body.decode("utf-8", "replace"), list_name)
        if not page_rows:
            break
        recent = [row for row in page_rows if (row.get("date") or "") >= since]
        window.extend(row for row in recent if row["id"] not in seen)
        seen.update(row["id"] for row in recent)
        if len(recent) < len(page_rows):
            break
    return window, from_cache


def _attach_bodies(fetcher, new_rows: list[dict]) -> int:
    targets = [row for row in new_rows if mail.DRAFT_SUBJ_RE.search(row.get("subject") or "")][:SYNC_BODY_CAP]
    fetched = 0
    for row in targets:
        try:
            parsed = mail.parse_body(fetcher.get(row["url"] + "download/"))
        except Exception:
            continue
        fetched += 1
        for key in ("message_id", "in_reply_to", "references", "from_name", "from_email", "body", "draft_refs"):
            row[key] = parsed.get(key)
    return fetched


def _threads_for(new_rows: list[dict], existing: set[str], list_name: str) -> list[dict]:
    grouped: dict[int, list[dict]] = {}
    for row in new_rows:
        grouped.setdefault(row["thread_numeric"], []).append(row)
    threads = []
    for number, group in grouped.items():
        if f"{list_name}:{number}" in existing:
            continue
        ordered = sorted(group, key=lambda r: r.get("date") or "")
        threads.append(
            {
                "thread_numeric": number,
                "url": ordered[0]["url"],
                "subject": ordered[0]["subject"],
                "n_messages": len(group),
                "first_date": ordered[0].get("date"),
                "last_date": ordered[-1].get("date"),
            }
        )
    return threads


def _aggregate_summary(graph, draft: str = DEFAULT_DRAFT):
    result = aggregate_unresolved(graph, draft)
    return (result["title"], tuple(sorted(c["sid"] for c in result["claims"] if c["unresolved"])))


def sync(graph, days: int = 1, fetcher=None, sections: dict | None = None):
    list_name = ingest.LIST
    since = (date.today() - timedelta(days=int(days))).isoformat()
    fetcher = fetcher or Fetcher(min_interval=2.0)
    before = _aggregate_summary(graph)
    try:
        window, from_cache = _fetch_window(fetcher, list_name, since)
    except SyncDeferred as deferred:
        return {
            "tool": "sync",
            "deferred": True,
            "title": f"sync deferred ({deferred.reason}), graph unchanged",
            "reason": deferred.reason,
            "n_changed": 0,
            "new_people": [],
            "aggregate_changed": False,
            "aggregate": None,
            "notes": [
                f"mailarchive could not be re-fetched ({deferred.reason}); the graph and the aggregate card are unchanged"
            ],
        }

    known = {row["id"] for row in rows(graph, "MATCH (m:Message) RETURN m.id AS id")}
    known_people = {row["name"] for row in rows(graph, "MATCH (p:Person) RETURN p.name AS name")}
    new_rows = [row for row in window if row["id"] not in known]
    new_people = sorted(
        {
            row["from_display"]
            for row in new_rows
            if row.get("from_display") and row["from_display"] not in known_people
        }
    )

    fetched_bodies = 0
    if new_rows:
        fetched_bodies = _attach_bodies(fetcher, new_rows)
        if sections is None:
            sections = ingest.load_sections(os.path.join(DATA_DIR, "sections.json"))
        existing = {row["id"] for row in rows(graph, "MATCH (t:Thread) RETURN t.id AS id")}
        ingest.append_messages(
            graph, new_rows, _threads_for(new_rows, existing, list_name), sections, list_name=list_name
        )

    after_card = aggregate_unresolved(graph)
    after = (after_card["title"], tuple(sorted(c["sid"] for c in after_card["claims"] if c["unresolved"])))
    changed = before != after

    chips = [message_chip(row["id"], row["url"]) for row in new_rows[:8]]
    if new_rows:
        claims = [{"text": f"{len(new_rows)} new message(s) in the last {days} day(s); {fetched_bodies} body fetch(es)", "chips": chips}]
    elif window:
        claims = [{"text": f"no new messages in the last {days} day(s); {len(window)} already in the graph", "chips": []}]
    else:
        claims = [{"text": f"no messages dated on or after {since}", "chips": []}]
    if new_people:
        claims.append({"text": "new people: " + ", ".join(new_people), "chips": []})

    result = card("sync", f"sync — {len(new_rows)} changed / {len(new_people)} new people", claims)
    result["deferred"] = False
    result["n_changed"] = len(new_rows)
    result["new_people"] = new_people
    result["aggregate_changed"] = changed
    result["aggregate"] = after_card if changed else None
    result["notes"].append(f"aggregate card {'changed' if changed else 'unchanged'}")
    if from_cache:
        result["notes"].append("the fresh fetch did not answer; the window was compared against the cached browse page(s)")
    return result


TOOLS = {
    "aggregate_unresolved": aggregate_unresolved,
    "who_argued": who_argued,
    "what_happened_to": what_happened_to,
    "precedent": precedent,
    "sync": sync,
    "section_by_heading": section_by_heading,
    "revisions": revisions,
    "count_unresolved": count_unresolved,
}


def run(graph, tool: str, **kwargs):
    return TOOLS[tool](graph, **kwargs)
