"""The fixed tool catalogue: each tool runs Cypher and returns an answer card.

Every claim carries mechanical permalink chips derived from node properties
(thread id, message id, draft revision, RFC section anchor). Nothing here calls
an LLM, and no LLM output can become a citation.
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta

from . import ingest, insights, mail, search, viz
from .fetch import Fetcher
from .graph import rows
from .paths import DATA_DIR

DEFAULT_DRAFT = "draft-ietf-tls-tls13"
LIST_LABEL = "the TLS list's messages"

TOPIC_LINK_PRECISION = "9 of 52 decided links (17.3%; 36 ties)"

SUBJECT_PREFIX_RE = re.compile(r"^(?:\s*(?:re|fwd?):\s*|\s*\[[^\]]+\]\s*)+", re.I)

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
    {"name": "why_clause", "args": ["number", "heading", "topic", "draft"], "description": "where a shipped clause was discussed while still changing, clauses discussed with it, who to ask now, and a drafted (never sent) question; a plain-words topic is resolved by FalkorDB's full-text index"},
    {"name": "search_discussion", "args": ["text"], "description": "what people wrote about a topic: FalkorDB full-text over message text, expanded to threads, authors and the clauses each message cites"},
    {"name": "who_knows", "args": [], "description": "the most central people in the list's discussions: algo.pageRank and algo.betweenness over who wrote in the same threads"},
    {"name": "aggregate_unresolved", "args": ["draft"], "description": "clauses of a draft discussed while still changing, with no later resolution trail"},
    {"name": "who_argued", "args": ["draft"], "description": "people who discussed a draft on the list, with their messages"},
    {"name": "what_happened_to", "args": ["number"], "description": "what happened to a clause across revisions and the RFC"},
    {"name": "precedent", "args": ["message_id"], "description": "trace a message to a revision and the RFC section it became"},
    {"name": "sync", "args": ["days"], "description": "how current the graph is, by record date"},
    {"name": "section_by_heading", "args": ["draft", "heading"], "description": "the section number a heading names, from the draft's RFC"},
    {"name": "revisions", "args": ["draft", "lo", "hi", "latest", "count"], "description": "a draft's revisions: list them, bound them to a range, count them, or name the latest"},
    {"name": "count_unresolved", "args": ["draft"], "description": "how many clauses of a draft were discussed while still changing, with no later resolution trail"},
    {"name": "chairs", "args": ["wg"], "description": "the chairs of the working group, and its area directors, from CHAIRS/AD_FOR"},
    {"name": "became_rfc", "args": ["draft"], "description": "the RFC a draft became, from the BECAME edge"},
    {"name": "threads_by_subject", "args": ["pattern"], "description": "thread ids whose subject names a distinctive pattern, from Thread/Message subjects"},
    {"name": "count_became", "args": ["draft"], "description": "how many drafts in a family the record shows became an RFC"},
    {"name": "count_thread_messages", "args": ["thread_or_draft"], "description": "how many messages a thread (or a draft's discussion) carries"},
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
        OPTIONAL MATCH (dr)-[:SUPERSEDED]->(next:DraftRevision)
        OPTIONAL MATCH (shipped:RFC)-[:HAS_SECTION]->(s)
        WITH s, m, dr, coalesce(next.date, shipped.published + '-31') AS until
        WHERE until IS NULL OR m.date <= until
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
            f"Unresolved discussions in {draft}",
            [],
            notes=[f"no clause of {draft} is linked to a discussion in the graph"],
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
            text = f"{label} — discussed by {people} while still changing; no resolution trail found"
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
    title = f"{attributed} clauses of {draft} discussed while still changing, no resolution trail"
    notes = [_topic_link_note(leads)] if leads else []
    result = card(
        "aggregate_unresolved",
        title,
        claims,
        rows_out=[{"section": c["text"], "unresolved": c["unresolved"], "bucket": c["bucket"]} for c in claims],
        notes=notes,
    )
    result["explanation"] = (
        "This is the graph saying: people discussed these clauses while their text was still changing, "
        "and no later message in the record returns to them. A gap in the record, not proof of an open objection."
    )
    return result


CITED_PATH_Q = """
MATCH (s:Section {id:$sid})
MATCH (m:Message)-[:CITES]->(s)
MATCH (m)-[:DISCUSSED]->(dr:DraftRevision)
MATCH (dr)-[al:ALIGNS_SECTION]->(s)
WHERE al.changed = true
OPTIONAL MATCH (dr)-[:SUPERSEDED]->(next:DraftRevision)
OPTIONAL MATCH (shipped:RFC)-[:HAS_SECTION]->(s)
WITH s, m, dr, al, coalesce(next.date, shipped.published + '-31') AS until
WHERE until IS NULL OR m.date <= until
MATCH (m)-[:IN_THREAD]->(t:Thread)
MATCH p=(dr)-[:SUPERSEDED*0..]->(last:DraftRevision)
MATCH (last)-[:BECAME]->(rfc:RFC)-[:HAS_SECTION]->(s)
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


def clause_receipt(graph, draft: str, sid: str, limit: int | None = None):
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
    for via, row in entries[:limit]:
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


WHY_SECTION_Q = """
MATCH (d:Draft {id:$draft})-[:HAS_REVISION]->(:DraftRevision)-[:BECAME]->(rfc:RFC)-[:HAS_SECTION]->(s:Section)
WHERE s.number = $number OR toLower(s.title) = $heading
RETURN DISTINCT s.id AS sid, s.number AS number, s.title AS title, s.url AS url, rfc.id AS rfc
ORDER BY s.number
"""

WHY_DISCUSSION_Q = """
MATCH (s:Section {id:$sid})
MATCH (m:Message)-[:CITES]->(s)
MATCH (m)-[:DISCUSSED]->(dr:DraftRevision)-[al:ALIGNS_SECTION]->(s)
WHERE al.changed = true
OPTIONAL MATCH (dr)-[:SUPERSEDED]->(next:DraftRevision)
OPTIONAL MATCH (shipped:RFC)-[:HAS_SECTION]->(s)
WITH s, m, dr, coalesce(next.date, shipped.published + '-31') AS until
WHERE until IS NULL OR m.date <= until
MATCH (m)-[:IN_THREAD]->(t:Thread)
OPTIONAL MATCH (p:Person)-[:AUTHORED]->(m)
RETURN m.id AS mid, m.url AS murl, m.date AS date, m.subject AS subject,
       coalesce(p.name, m.from) AS person, t.id AS tid, t.url AS turl, t.subject AS tsubject,
       collect(DISTINCT dr.id) AS revisions
ORDER BY date, mid
"""

WHY_ROLES_Q = """
MATCH (c:Chair)-[:CHAIRS]->(w:Wg {id:$wg}) RETURN c.name AS name, 'chair' AS role
UNION
MATCH (a:AreaDirector)-[:AD_FOR]->(w:Wg {id:$wg}) RETURN a.name AS name, 'area director' AS role
"""


DISCUSSED_CLAUSES_Q = """
MATCH (d:Draft {id:$draft})-[:HAS_REVISION]->(:DraftRevision)-[:BECAME]->(:RFC)-[:HAS_SECTION]->(s:Section)
MATCH (m:Message)-[:CITES]->(s)
MATCH (m)-[:DISCUSSED]->(dr:DraftRevision)-[al:ALIGNS_SECTION]->(s)
WHERE al.changed = true
OPTIONAL MATCH (dr)-[:SUPERSEDED]->(next:DraftRevision)
OPTIONAL MATCH (shipped:RFC)-[:HAS_SECTION]->(s)
WITH s, m, dr, coalesce(next.date, shipped.published + '-31') AS until
WHERE until IS NULL OR m.date <= until
OPTIONAL MATCH (p:Person)-[:AUTHORED]->(m)
RETURN s.number AS number, s.title AS title,
       count(DISTINCT m) AS messages, count(DISTINCT coalesce(p.name, m.from)) AS people
ORDER BY messages DESC, number
"""


def discussed_clauses(graph, draft: str = DEFAULT_DRAFT) -> list[dict]:
    """Every shipped clause that why_clause can trace to a discussion, busiest first."""
    return rows(graph, DISCUSSED_CLAUSES_Q, {"draft": draft})


def _short_rev(revision: str) -> str:
    return "-" + revision.rpartition("-")[2]


def _rfc_label(rfc_id: str) -> str:
    return f"RFC {rfc_id[3:]}" if rfc_id.startswith("rfc") else rfc_id


def _bare_subject(subject: str) -> str:
    return SUBJECT_PREFIX_RE.sub("", subject or "").strip()


def _draft_message(section: dict, discussed: list[dict], people: list[str], roles: list[dict]) -> dict:
    label = f"{_rfc_label(section['rfc'])} §{section['number']} {section['title']}"
    chairs = [r["name"] for r in roles if r["role"] == "chair"]
    lines = [
        "Hi all,",
        "",
        f"I'm new to TLS 1.3 and trying to understand why {label} reads the way it does.",
        "",
    ]
    threads: dict[str, dict] = {}
    for row in discussed:
        threads.setdefault(row["tid"], row | {"dates": [], "revs": set()})
        threads[row["tid"]]["dates"].append(row["date"])
        threads[row["tid"]]["revs"].update(row["revisions"])
    for thread in threads.values():
        revs = ", ".join(_short_rev(r) for r in sorted(thread["revs"]))
        span = min(thread["dates"]) if min(thread["dates"]) == max(thread["dates"]) else (
            f"{min(thread['dates'])} to {max(thread['dates'])}"
        )
        lines.append(
            f"The list archive shows you discussed it in \"{_bare_subject(thread['tsubject'] or thread['subject'])}\" ({span}), "
            f"while the draft was at {revs} and the clause's text still differed from what shipped."
        )
    lines += [
        "",
        "Could you point me to the reasoning, or to whatever settled it?",
        "",
        "Sources:",
    ]
    lines += [f"- {thread['turl']}" for thread in threads.values()]
    lines.append(f"- {section['url']}")
    return {
        "to": people,
        "cc": [f"{name} (TLS chair)" for name in chairs],
        "subject": f"Question on {label}",
        "body": "\n".join(lines),
    }


def why_clause(graph, number: str = "", heading: str = "", draft: str = DEFAULT_DRAFT, topic: str = ""):
    """Where a shipped clause was discussed while it was still changing, and who to ask now.

    A clause is named by number, by exact heading, or by a plain-words topic that FalkorDB's full-text index on
    Section.title resolves (the best match is answered; the runners-up are listed).
    """
    number = (number or "").strip().lstrip("§")
    heading = (heading or "").strip().lower()
    resolved = []
    if not number and not heading and topic:
        resolved = search.find_sections(graph, topic, draft)
        if not resolved:
            result = card(
                "why_clause",
                "No clause matches that question",
                [],
                notes=[f"FalkorDB's full-text index on RFC section headings found nothing for: {search.query_terms(topic) or topic!r}"]
                + [f"you can ask: {item}" for item in ANSWERABLE],
            )
            result["answer"] = None
            return result
        number = resolved[0]["number"]
    sections = rows(graph, WHY_SECTION_Q, {"draft": draft, "number": number, "heading": heading})
    asked = f"§{number}" if number else f"the section titled '{heading}'"
    if not sections:
        result = card(
            "why_clause",
            f"Why {asked} reads the way it does",
            [],
            notes=[f"the RFC that {draft} became has no {asked} in the graph"],
        )
        result["answer"] = None
        return result
    section = sections[0]
    label = f"§{section['number']} {section['title']}"
    discussed = rows(graph, WHY_DISCUSSION_Q, {"sid": section["sid"]})
    roles = rows(graph, WHY_ROLES_Q, {"wg": ingest.LIST})

    counts: dict[str, int] = {}
    for row in discussed:
        counts[row["person"]] = counts.get(row["person"], 0) + 1
    people = sorted(counts, key=lambda name: (-counts[name], name))

    claims = []
    for row in discussed:
        revs = ", ".join(_short_rev(r) for r in sorted(row["revisions"]))
        chips = [message_chip(row["mid"], row["murl"]), thread_chip(row["tid"], row["turl"])]
        chips += [revision_chip(r) for r in sorted(row["revisions"])]
        claims.append(
            {
                "text": f"{row['date']} · {row['person']} cited {label} in \"{_bare_subject(row['subject'])}\" (draft at {revs})",
                "chips": chips,
            }
        )
    missing = []
    if not claims:
        claims = [{"text": f"{label} shipped in {_rfc_label(section['rfc'])}", "chips": [section_chip(section["number"], section["title"], section["url"])]}]
        missing = [f"no message in the graph cites {label} while its text was still changing"]

    title = (
        f"{label}: discussed by {len(people)} people while still changing, then shipped in {_rfc_label(section['rfc'])}"
        if people
        else f"{label}: shipped in {_rfc_label(section['rfc'])}, no discussion found"
    )
    result = card("why_clause", title, claims, rows_out=discussed, missing=missing)
    result["hero"] = True
    result["explanation"] = (
        "Connected, not caused: these messages cited the clause while its text still differed from what shipped. "
        "The graph does not show that they caused the change."
    )
    result["section"] = section
    result["sid"] = section["sid"]
    result["draft"] = draft
    result["who_to_ask"] = [
        {"name": name, "why": f"cited this clause in {counts[name]} message(s)"} for name in people
    ] + [{"name": r["name"], "why": f"current TLS {r['role']}"} for r in sorted(roles, key=lambda r: (r["role"], r["name"]))]
    result["draft_message"] = _draft_message(section, discussed, people, roles)
    result["related"] = insights.related_clauses(graph, section["sid"])
    if resolved:
        result["resolved"] = {
            "topic": topic,
            "query": search.query_terms(topic),
            "matches": [{"number": r["number"], "title": r["title"], "score": r["score"]} for r in resolved],
        }
    result["answer"] = people
    return result


def search_discussion(graph, text: str = "", limit: int = 10):
    """What people wrote about a topic: FalkorDB full-text over message bodies and subjects, then the graph
    expands each hit to its thread, its author and the RFC clauses it cites."""
    hits = search.search_messages(graph, text, limit)
    query = search.query_terms(text)
    if not hits:
        result = card(
            "search_discussion",
            "No message in the record matches that",
            [],
            notes=[f"FalkorDB's full-text index over {LIST_LABEL} found nothing for: {query or text!r}"],
        )
        result["answer"] = []
        return result
    claims = []
    for hit in hits:
        chips = [message_chip(hit["mid"], hit["url"])]
        if hit.get("tid"):
            chips.append(thread_chip(hit["tid"], hit["turl"]))
        cited = ", ".join(f"§{s['number']} {s['title']}" for s in hit["sections"])
        text_out = f"{hit['date']} · {hit['person']}: \"{_bare_subject(hit['subject'])}\""
        claims.append({"text": text_out + (f" (cites {cited})" if cited else ""), "quote": hit["excerpt"], "chips": chips})
    clauses = sorted({(s["number"], s["title"]) for hit in hits for s in hit["sections"]}, key=lambda s: s[0])
    notes = [f"full-text query run in FalkorDB: {query}"]
    if clauses:
        notes.append("clauses these messages cite: " + ", ".join(f"§{n} {t}" for n, t in clauses))
    result = card("search_discussion", f"{len(hits)} messages on the list match", claims, notes=notes)
    result["answer"] = [hit["mid"] for hit in hits]
    return result


def who_knows(graph, limit: int = 10):
    """The people at the centre of the list's discussions: PageRank and betweenness over CO_DISCUSSED."""
    people = insights.central_people(graph, limit)
    if not people:
        result = card("who_knows", "No discussion network in the graph", [], notes=["CO_DISCUSSED has no edges"])
        result["answer"] = []
        return result
    claims = [
        {
            "text": (
                f"{p['name']} — PageRank {p['pagerank']}, betweenness {round(p['betweenness'])}; "
                f"wrote in {p['threads']} threads, cited {p['clauses']} RFC 8446 clauses"
            ),
            "chips": [],
        }
        for p in people
    ]
    result = card(
        "who_knows",
        f"The {len(people)} most central people in the TLS list discussions",
        claims,
        rows_out=people,
        notes=[
            "PageRank and betweenness are FalkorDB's algo.pageRank and algo.betweenness over CO_DISCUSSED, "
            "an edge between two people who wrote in the same thread (derived from the record by Cypher)",
            "central in the discussion network is not the same as being right, or being the decider",
        ],
    )
    result["explanation"] = (
        "PageRank ranks people by how connected their conversation partners are; betweenness ranks the people "
        "who link otherwise separate discussions."
    )
    result["answer"] = [p["name"] for p in people]
    return result


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
        return card("who_argued", f"Who discussed {draft}", [], notes=[f"no message in the graph discusses {draft}"])
    claims = []
    for person in people:
        chips = [message_chip(m, u) for m, u in zip(person["messages"], person["message_urls"])]
        chips += [thread_chip(t, u) for t, u in zip(person["threads"], person["thread_urls"])]
        claims.append({"text": f"{person['person']} — {person['n']} messages", "chips": chips})
    return card("who_argued", f"Who discussed {draft}", claims, rows_out=people)


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
    """How many clauses of a draft were discussed while still changing, with no resolution trail."""
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
        f"{count} clauses of {draft} discussed while still changing, no resolution trail",
        claims,
        rows_out=[{"section": claim["text"]} for claim in cited],
        notes=notes,
    )
    result["answer"] = count
    result["count"] = count
    return result


def chairs(graph, wg: str = ""):
    """The working group's chairs (and, separately, its area directors)."""
    wg = wg or ingest.LIST
    people = rows(
        graph,
        "MATCH (c:Chair)-[:CHAIRS]->(w:Wg {id:$wg}) RETURN c.name AS name ORDER BY c.name",
        {"wg": wg},
    )
    if not people:
        result = card("chairs", f"Chairs of {wg}", [], notes=[f"no chair of {wg} is recorded in the graph"])
        result["answer"] = None
        return result
    ads = rows(
        graph,
        "MATCH (a:AreaDirector)-[:AD_FOR]->(w:Wg {id:$wg}) RETURN a.name AS name ORDER BY a.name",
        {"wg": wg},
    )
    claims = [{"text": f"chair: {person['name']}", "chips": []} for person in people]
    claims += [{"text": f"area director: {person['name']}", "chips": []} for person in ads]
    result = card("chairs", f"Chairs of {wg}", claims, rows_out=people)
    result["answer"] = [person["name"] for person in people]
    result["area_directors"] = [person["name"] for person in ads]
    return result


def became_rfc(graph, draft: str = DEFAULT_DRAFT):
    """The RFC a draft became, read straight off the BECAME edge."""
    hits = rows(
        graph,
        "MATCH (d:Draft {id:$draft})-[:HAS_REVISION]->(:DraftRevision)-[:BECAME]->(rfc:RFC) "
        "RETURN DISTINCT rfc.id AS id, rfc.number AS number, rfc.title AS title, rfc.url AS url ORDER BY rfc.id",
        {"draft": draft},
    )
    if not hits:
        result = card("became_rfc", f"What {draft} became", [], notes=[f"the graph records no RFC that {draft} became"])
        result["answer"] = None
        return result
    claims = [
        {"text": f"{hit['id']} — {hit['title']}", "chips": [rfc_chip(hit["id"], hit["url"])]}
        for hit in hits
    ]
    title = f"{draft} became {hits[0]['id']}" if len(hits) == 1 else f"{draft} became {len(hits)} RFCs"
    result = card("became_rfc", title, claims, rows_out=hits)
    result["answer"] = hits[0]["id"] if len(hits) == 1 else [hit["id"] for hit in hits]
    return result


def threads_by_subject(graph, pattern: str = ""):
    """Thread ids whose subject (or any message's subject) carries a distinctive pattern."""
    pattern = (pattern or "").strip()
    hits = rows(
        graph,
        """
        MATCH (t:Thread)
        OPTIONAL MATCH (t)<-[:IN_THREAD]-(m:Message)
        WITH t, collect(toLower(m.subject)) AS subjects
        WHERE toLower(t.subject) CONTAINS toLower($pattern)
           OR any(subject IN subjects WHERE subject CONTAINS toLower($pattern))
        RETURN DISTINCT t.id AS id, t.subject AS subject, t.url AS url ORDER BY t.id
        """,
        {"pattern": pattern},
    )
    if not hits:
        result = card(
            "threads_by_subject",
            f'Threads naming "{pattern}"',
            [],
            notes=[f'no thread subject in the graph contains "{pattern}"'],
        )
        result["answer"] = None
        return result
    claims = [
        {"text": f"{hit['id']} — {hit['subject']}", "chips": [thread_chip(hit["id"], hit["url"])]}
        for hit in hits
    ]
    result = card("threads_by_subject", f'{len(hits)} thread(s) naming "{pattern}"', claims, rows_out=hits)
    result["answer"] = [hit["id"] for hit in hits]
    return result


def count_became(graph, draft: str = DEFAULT_DRAFT):
    """How many drafts in a family the record shows became an RFC (BECAME count)."""
    if draft.endswith("-") or "*" in draft:
        cypher = (
            "MATCH (d:Draft)-[:HAS_REVISION]->(:DraftRevision)-[:BECAME]->(:RFC) "
            "WHERE d.id STARTS WITH $draft RETURN count(DISTINCT d) AS n"
        )
    else:
        cypher = (
            "MATCH (d:Draft {id:$draft})-[:HAS_REVISION]->(:DraftRevision)-[:BECAME]->(:RFC) "
            "RETURN count(DISTINCT d) AS n"
        )
    count = rows(graph, cypher, {"draft": draft})[0]["n"]
    if not count:
        result = card(
            "count_became",
            f"No draft matching {draft} is recorded as having become an RFC",
            [],
            notes=[f"the graph has no BECAME edge from a draft matching {draft}"],
        )
        result["answer"] = None
        return result
    claims = [{"text": f"{count} draft(s) matching {draft} hold a BECAME edge to an RFC", "chips": []}]
    result = card("count_became", f"{count} drafts matching {draft} became an RFC", claims, rows_out=[{"count": count}])
    result["answer"] = count
    result["count"] = count
    return result


def count_thread_messages(graph, thread_or_draft: str = ""):
    """How many messages a thread carries (or a draft's discussion does)."""
    ref = (thread_or_draft or "").strip()
    if ":" in ref:
        hits = rows(
            graph,
            "MATCH (t:Thread {id:$ref})<-[:IN_THREAD]-(m:Message) "
            "RETURN t.id AS id, t.subject AS subject, t.url AS url, count(m) AS n",
            {"ref": ref},
        )
    else:
        hits = rows(
            graph,
            "MATCH (d:Draft {id:$ref})-[:HAS_REVISION]->(:DraftRevision)<-[:DISCUSSED]-(m:Message) "
            "RETURN d.id AS id, d.title AS subject, d.id AS url, count(DISTINCT m) AS n",
            {"ref": ref},
        )
    if not hits or not hits[0]["id"]:
        result = card("count_thread_messages", f"Messages in {ref}", [], notes=[f"the graph does not know {ref}"])
        result["answer"] = None
        return result
    hit = hits[0]
    chips = [thread_chip(hit["id"], hit["url"])] if ":" in ref else []
    claims = [{"text": f"{hit['id']} — {hit['n']} message(s)", "chips": chips}]
    result = card("count_thread_messages", f"{hit['n']} message(s) in {hit['id']}", claims, rows_out=hits)
    result["answer"] = hit["n"]
    result["count"] = hit["n"]
    return result


NO_ANSWER = "no_answer"
NOT_UNDERSTOOD = "not_understood"

ANSWERABLE = [
    "why a section of RFC 8446 reads the way it does, and who to ask (e.g. \"why does early data work like this?\")",
    "what the list said about a topic (e.g. \"what did people say about middleboxes?\")",
    "who the most central people in the discussions are",
    "which clauses of draft-ietf-tls-tls13 were discussed while still changing and never resolved",
    "who chairs the TLS working group",
    "the latest revision of draft-ietf-tls-tls13, how many revisions it had, or the revisions between two numbers",
    "which RFC a draft became, or the section number of a quoted heading",
]


def no_answer(scope: str = "that record"):
    """The router's honest abstention for a shape no catalogue tool can answer.

    Reserved: it is not in TOOL_CATALOGUE, so the LLM can never pick it and it is
    not offered as a tool. It only renders the same "the graph does not know" card
    the empty traversals already use.
    """
    result = card(
        NO_ANSWER,
        f"{scope} is not in the ingested record",
        [],
        notes=[f"the graph holds one WG's drafts, RFCs and mailing-list threads — no {scope} artefact is loaded"],
    )
    result["explanation"] = "This is the graph saying: the question names a record it was not built to hold."
    result["answer"] = None
    return result


def not_understood():
    """The router matched no question shape, so nothing is guessed: say what can be asked instead."""
    result = card(
        NOT_UNDERSTOOD,
        "That question doesn't map to anything in the graph",
        [],
        notes=[f"you can ask: {item}" for item in ANSWERABLE],
    )
    result["explanation"] = "No question shape matched, so no query ran and nothing was guessed."
    result["answer"] = None
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
    "why_clause": why_clause,
    "search_discussion": search_discussion,
    "who_knows": who_knows,
    "aggregate_unresolved": aggregate_unresolved,
    "who_argued": who_argued,
    "what_happened_to": what_happened_to,
    "precedent": precedent,
    "sync": sync,
    "section_by_heading": section_by_heading,
    "revisions": revisions,
    "count_unresolved": count_unresolved,
    "chairs": chairs,
    "became_rfc": became_rfc,
    "threads_by_subject": threads_by_subject,
    "count_became": count_became,
    "count_thread_messages": count_thread_messages,
}


def run(graph, tool: str, **kwargs):
    if tool == NO_ANSWER:
        return no_answer(**kwargs)
    if tool == NOT_UNDERSTOOD:
        return not_understood()
    return TOOLS[tool](graph, **kwargs)
