"""The fixed tool catalogue: each tool runs Cypher and returns an answer card.

Every claim carries mechanical permalink chips derived from node properties
(thread id, message id, draft revision, RFC section anchor). Nothing here calls
an LLM, and no LLM output can become a citation.
"""
from __future__ import annotations

from datetime import date, timedelta

from .graph import rows

DEFAULT_DRAFT = "draft-ietf-tls-tls13"

TOPIC_LINK_PRECISION = "9 of 52 decided links (17.3%; 36 ties)"

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
]

CATALOGUE_BY_NAME = {tool["name"]: tool for tool in TOOL_CATALOGUE}


def thread_chip(thread_id, url):
    return {"kind": "thread", "label": thread_id, "url": url}


def message_chip(message_id, url):
    return {"kind": "message", "label": message_id, "url": url}


def revision_chip(revision):
    return {"kind": "revision", "label": revision, "url": f"https://datatracker.ietf.org/doc/{revision}/"}


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
    return card(
        "aggregate_unresolved",
        title,
        claims,
        rows_out=[{"section": c["text"], "unresolved": c["unresolved"], "bucket": c["bucket"]} for c in claims],
        notes=notes,
    )


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


def sync(graph, days: int = 1):
    since = (date.today() - timedelta(days=int(days))).isoformat()
    window = rows(
        graph,
        "MATCH (m:Message) WHERE m.date >= $since RETURN count(m) AS messages, max(m.date) AS latest",
        {"since": since},
    )
    threads = rows(graph, "MATCH (t:Thread) RETURN count(t) AS n, max(t.last_date) AS latest")
    total = rows(graph, "MATCH (m:Message) RETURN count(m) AS n")[0]["n"]
    recent = window[0]["messages"] if window else 0
    latest = (threads[0]["latest"] if threads else None) or "unknown"
    newest = rows(
        graph,
        "MATCH (t:Thread) WHERE t.last_date = $latest RETURN t.id AS id, t.url AS url LIMIT 1",
        {"latest": latest},
    )
    chips = [thread_chip(n["id"], n["url"]) for n in newest]
    summary = (
        f"{total} messages in the graph; {recent} dated on or after {since}; "
        f"most recent thread dated {latest}"
    )
    claims = [{"text": summary, "chips": chips}]
    return card("sync", f"Graph freshness (last {days} day(s))", claims, rows_out=window + threads)


TOOLS = {
    "aggregate_unresolved": aggregate_unresolved,
    "who_argued": who_argued,
    "what_happened_to": what_happened_to,
    "precedent": precedent,
    "sync": sync,
}


def run(graph, tool: str, **kwargs):
    return TOOLS[tool](graph, **kwargs)
