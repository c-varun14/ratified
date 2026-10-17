"""Build the frozen v1 graph rows from the pulled record and write them to FalkorDB."""
from __future__ import annotations

import glob
import json
import os
import re
from collections import Counter
from pathlib import Path

from . import schema
from .paths import DATA_DIR

LIST = os.environ.get("RATIFIED_LIST", "tls")
DRAFT_PREFIX = os.environ.get("RATIFIED_DRAFT_PREFIX", "draft-ietf-tls")
BATCH = 500
TEXT_CAP = 8000

STOP_TOKENS = {
    "tls", "tls13", "draft", "ietf", "about", "their", "there", "which", "these",
    "those", "would", "could", "should", "other", "after", "before", "where",
    "while", "still", "version", "issues", "issue", "comments", "comment",
    "questions", "regarding",
}


def load_messages(mail_dir: str, list_name: str = LIST) -> list[dict]:
    messages: dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(mail_dir, f"{list_name}*_messages.json"))):
        for msg in json.loads(Path(path).read_text()):
            current = messages.get(msg["id"])
            if current is None or (not current.get("body") and msg.get("body")):
                messages[msg["id"]] = msg
    return list(messages.values())


def load_threads(mail_dir: str, list_name: str = LIST) -> list[dict]:
    threads: dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(mail_dir, f"{list_name}*_threads.json"))):
        for thread in json.loads(Path(path).read_text()):
            threads.setdefault(str(thread["thread_numeric"]), thread)
    return list(threads.values())


def load_docs(path: str) -> dict:
    return json.loads(Path(path).read_text())


def load_sections(path: str) -> dict:
    return json.loads(Path(path).read_text())


def load_dataset(data_dir: str = DATA_DIR, list_name: str = LIST) -> dict:
    return {
        "messages": load_messages(os.path.join(data_dir, "mail"), list_name),
        "threads": load_threads(os.path.join(data_dir, "mail"), list_name),
        "docs": load_docs(os.path.join(data_dir, "docs", f"{list_name}_docs.json")),
        "sections": load_sections(os.path.join(data_dir, "sections.json")),
    }


def person_key(msg: dict) -> str | None:
    if msg.get("from_email"):
        return msg["from_email"]
    display = (msg.get("from_display") or "").strip()
    return f"name:{display}" if display else None


def person_rows(messages: list[dict]) -> list[dict]:
    people: dict[str, dict] = {}
    for msg in messages:
        key = person_key(msg)
        if not key:
            continue
        people.setdefault(
            key,
            {
                "id": key,
                "name": msg.get("from_name") or msg.get("from_display") or "",
                "email": msg.get("from_email") or "",
            },
        )
    return list(people.values())


def thread_rows(threads: list[dict], list_name: str = LIST) -> list[dict]:
    return [
        {
            "id": f"{list_name}:{t['thread_numeric']}",
            "subject": (t.get("subject") or "")[:300],
            "url": t.get("url"),
            "n_messages": t.get("n_messages"),
            "first_date": t.get("first_date"),
            "last_date": t.get("last_date"),
        }
        for t in threads
    ]


def message_rows(messages: list[dict], list_name: str = LIST) -> list[dict]:
    return [
        {
            "id": m["id"],
            "message_id": m.get("message_id"),
            "subject": (m.get("subject") or "")[:300],
            "date": m.get("date"),
            "from": m.get("from_display") or "",
            "url": m.get("url"),
            "depth": m.get("depth") or 0,
            "has_body": bool(m.get("body")),
            "text": (m.get("body") or "")[:TEXT_CAP],
            "thread": f"{list_name}:{m.get('thread_numeric')}",
        }
        for m in messages
    ]


def person_message_rows(messages: list[dict]) -> list[dict]:
    return [{"src": person_key(m), "tgt": m["id"]} for m in messages if person_key(m)]


def thread_message_rows(messages: list[dict], list_name: str = LIST) -> list[dict]:
    return [{"src": m["id"], "tgt": f"{list_name}:{m.get('thread_numeric')}"} for m in messages]


def body_rows(messages: list[dict]) -> list[dict]:
    return [{"src": m["id"], "tgt": m["id"]} for m in messages]


def role_rows(docs: dict) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    wg = {
        "id": docs["group"]["acronym"],
        "name": docs["group"]["name"],
        "email": docs["group"].get("list_email") or "",
    }
    chairs = [
        {"id": f"chair:{c['email']}", "name": c.get("name") or c["email"].split("@")[0], "email": c["email"]}
        for c in docs.get("chairs", [])
    ]
    ads = [
        {"id": f"ad:{a['email']}", "name": a.get("name") or a["email"].split("@")[0], "email": a["email"]}
        for a in docs.get("ads", [])
    ]
    chair_edges = [{"src": c["id"], "tgt": wg["id"]} for c in chairs]
    ad_edges = [{"src": a["id"], "tgt": wg["id"]} for a in ads]
    return wg, chairs, ads, chair_edges, ad_edges


def draft_rows(docs: dict) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    drafts, revisions, in_wg, superseded = [], [], [], []
    for d in docs["drafts"]:
        drafts.append({"id": d["name"], "title": (d.get("title") or "")[:300], "latest_rev": d.get("latest_rev")})
        in_wg.append({"src": d["name"], "tgt": docs["group"]["acronym"]})
        ordered = sorted(d["revisions"], key=lambda r: (len(r["rev"]), r["rev"]))
        for r in ordered:
            revisions.append({"id": r["revision"], "revision": r["revision"], "rev": r["rev"], "date": r.get("date") or ""})
        for a, b in zip(ordered, ordered[1:]):
            superseded.append({"src": a["revision"], "tgt": b["revision"]})
    return drafts, revisions, in_wg, superseded


def has_revision_rows(docs: dict) -> list[dict]:
    return [
        {"src": d["name"], "tgt": r["revision"]}
        for d in docs["drafts"]
        for r in d["revisions"]
    ]


def rfc_rows(docs: dict) -> tuple[list[dict], list[dict]]:
    rfcs = [
        {
            "id": name,
            "number": v.get("rfc_number"),
            "title": (v.get("title") or "")[:300],
            "url": f"https://www.rfc-editor.org/rfc/{name}.html",
        }
        for name, v in docs["rfcs"].items()
    ]
    became = [
        {"src": f"{d['name']}-{d['latest_rev']}", "tgt": d["rfc"]}
        for d in docs["drafts"]
        if d.get("rfc")
    ]
    return rfcs, became


def section_rows(sections: dict) -> list[dict]:
    rfc_name = sections["rfc"]["name"]
    return [
        {
            "id": f"{rfc_name}#{num}",
            "number": num,
            "title": s["title"][:200],
            "url": f"https://www.rfc-editor.org/rfc/{rfc_name}.html#section-{num}",
            "rfc": rfc_name,
        }
        for num, s in sections["rfc"]["sections"].items()
    ]


def align_rows(sections: dict) -> list[dict]:
    rfc_name = sections["rfc"]["name"]
    rows, seen = [], set()
    for draft_name, dv in sections["drafts"].items():
        for info in dv["align"].values():
            key = (draft_name, f"{rfc_name}#{info['rfc_number']}")
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "src": draft_name,
                    "tgt": key[1],
                    "similarity": info["similarity"],
                    "changed": info["changed"],
                    "how": info["how"],
                }
            )
    return rows


def tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(w) >= 5 and w not in STOP_TOKENS
    }


def about_rows(threads: list[dict], sections: dict, list_name: str = LIST) -> list[dict]:
    rfc_name = sections["rfc"]["name"]
    section_tokens = {num: tokens(s["title"]) for num, s in sections["rfc"]["sections"].items()}
    frequency: Counter = Counter()
    for token_set in section_tokens.values():
        frequency.update(token_set)
    rows = []
    for thread in threads:
        thread_tokens = tokens(thread.get("subject"))
        if not thread_tokens:
            continue
        for num, section_tokens_here in section_tokens.items():
            matched = {w for w in (thread_tokens & section_tokens_here) if frequency[w] <= 2}
            if matched:
                rows.append(
                    {
                        "src": f"{list_name}:{thread['thread_numeric']}",
                        "tgt": f"{rfc_name}#{num}",
                        "matched_tokens": ",".join(sorted(matched)),
                    }
                )
    return rows


def discussion_rows(
    messages: list[dict], sections: dict, draft_prefix: str = DRAFT_PREFIX
) -> tuple[list[dict], list[dict], int]:
    rfc_name = sections["rfc"]["name"]
    rev_align = {
        (draft_name, draft_num): info["rfc_number"]
        for draft_name, dv in sections["drafts"].items()
        for draft_num, info in dv["align"].items()
    }
    rev_re = re.compile(rf"({re.escape(draft_prefix)}-[a-z0-9-]+?-)(\d{{2}})(?![a-z0-9-])")
    sec_re = re.compile(r"\b[Ss]ection\s+(\d+(?:\.\d+)*)")
    discussed: set[tuple[str, str]] = set()
    cites: set[tuple[str, str]] = set()
    unresolved = 0
    for msg in messages:
        text = (msg.get("subject") or "") + "\n" + (msg.get("body") or "")
        if not text.strip():
            continue
        revisions = {m.group(1) + m.group(2) for m in rev_re.finditer(text)}
        for revision in revisions:
            discussed.add((msg["id"], revision))
        for match in sec_re.finditer(text):
            num = match.group(1)
            target = next(
                (rev_align[(r, num)] for r in revisions if (r, num) in rev_align), None
            )
            if target is None:
                unresolved += 1
                continue
            cites.add((msg["id"], f"{rfc_name}#{target}"))
    return (
        [{"src": a, "tgt": b} for a, b in sorted(discussed)],
        [{"src": a, "tgt": b} for a, b in sorted(cites)],
        unresolved,
    )


def ingest(graph, data: dict, *, list_name: str = LIST, draft_prefix: str = DRAFT_PREFIX, batch: int = BATCH) -> dict:
    nodes = lambda label, rows: _write(graph, schema.merge_nodes(label), rows, batch)
    edges = lambda type_, rows: _write(graph, schema.merge_edges(type_), rows, batch)

    wg, chairs, ads, chair_edges, ad_edges = role_rows(data["docs"])
    nodes("Wg", [wg])
    nodes("Person", person_rows(data["messages"]))
    nodes("Chair", chairs)
    nodes("AreaDirector", ads)
    edges("CHAIRS", chair_edges)
    edges("AD_FOR", ad_edges)

    nodes("Thread", thread_rows(data["threads"], list_name))
    nodes("Message", message_rows(data["messages"], list_name))
    nodes("MessageBody", message_rows(data["messages"], list_name))
    edges("IN_THREAD", thread_message_rows(data["messages"], list_name))
    edges("HAS_BODY", body_rows(data["messages"]))
    edges("AUTHORED", person_message_rows(data["messages"]))

    drafts, revisions, in_wg, superseded = draft_rows(data["docs"])
    rfcs, became = rfc_rows(data["docs"])
    nodes("Draft", drafts)
    nodes("DraftRevision", revisions)
    nodes("RFC", rfcs)
    edges("IN_WG", in_wg)
    edges("HAS_REVISION", has_revision_rows(data["docs"]))
    edges("SUPERSEDED", superseded)
    edges("BECAME", became)

    sections = section_rows(data["sections"])
    nodes("Section", sections)
    edges("HAS_SECTION", [{"src": s["rfc"], "tgt": s["id"]} for s in sections])
    edges("ALIGNS_SECTION", align_rows(data["sections"]))
    edges("ABOUT_SECTION", about_rows(data["threads"], data["sections"], list_name))

    discussed, cites, unresolved = discussion_rows(data["messages"], data["sections"], draft_prefix)
    edges("DISCUSSED", discussed)
    edges("CITES", cites)

    return {
        "nodes": {
            label: _count(graph, f"MATCH (n:{label}) RETURN count(n)")
            for label in schema.NODES
        },
        "edges": {
            type_: _count(graph, f"MATCH ()-[e:{type_}]->() RETURN count(e)")
            for type_ in schema.EDGES
        },
        "cites_unresolved": unresolved,
    }


def append_messages(graph, messages: list[dict], threads: list[dict], sections: dict,
                    *, list_name: str = LIST, draft_prefix: str = DRAFT_PREFIX, batch: int = BATCH) -> dict:
    """Add newly fetched messages (and any new threads) without touching existing nodes."""
    _write(graph, schema.merge_nodes("Person"), person_rows(messages), batch)
    _write(graph, schema.merge_nodes("Thread"), thread_rows(threads, list_name), batch)
    _write(graph, schema.merge_nodes("Message"), message_rows(messages, list_name), batch)
    _write(graph, schema.merge_nodes("MessageBody"), message_rows(messages, list_name), batch)
    _write(graph, schema.merge_edges("IN_THREAD"), thread_message_rows(messages, list_name), batch)
    _write(graph, schema.merge_edges("AUTHORED"), person_message_rows(messages), batch)
    _write(graph, schema.merge_edges("HAS_BODY"), body_rows(messages), batch)
    discussed, cites, unresolved = discussion_rows(messages, sections, draft_prefix)
    _write(graph, schema.merge_edges("DISCUSSED"), discussed, batch)
    _write(graph, schema.merge_edges("CITES"), cites, batch)
    return {"messages": len(messages), "threads": len(threads), "discussed": len(discussed), "cites": len(cites)}


def _write(graph, cypher: str, rows: list[dict], batch: int) -> None:
    for start in range(0, max(1, len(rows)), batch):
        graph.query(cypher, {"rows": rows[start : start + batch]})


def _count(graph, cypher: str) -> int:
    result = graph.query(cypher).result_set
    return result[0][0] if result else 0
