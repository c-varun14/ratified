"""FalkorDB full-text entry points: resolve a clause named in plain words, and search what people wrote.

A free-text question is reduced to a safe full-text query (stop words dropped, long words prefixed, terms OR-ed so
extra words in a casual question do not empty the result) and matched against FalkorDB's own full-text indexes.
No raw user text reaches the index and no LLM is involved.
"""
from __future__ import annotations

import re

from .graph import rows

DEFAULT_DRAFT = "draft-ietf-tls-tls13"

INDEXES = (
    ("Section", "title"),
    ("Message", "subject"),
    ("MessageBody", "text"),
)

STOP_WORDS = {
    "a", "about", "actually", "after", "again", "all", "also", "am", "an", "and", "any", "are", "as", "ask", "asked",
    "at", "backstory", "be", "because", "been", "before", "behind", "being", "but", "by", "can", "clause", "come",
    "comes", "could", "decided", "did", "do", "does", "down", "draft", "ended", "explain", "for", "from", "get", "go",
    "going", "got", "had", "has", "have", "he", "her", "here", "him", "his", "how", "i", "ietf", "if", "in", "into",
    "is", "it", "its", "just", "know", "like", "made", "make", "may", "me", "might", "more", "most", "must", "my",
    "need", "new", "no", "not", "now", "of", "on", "one", "only", "or", "other", "our", "out", "over", "phrased",
    "please", "reason", "read", "reads", "reading", "really", "rfc", "said", "say", "section", "sections", "shall",
    "she", "should", "so", "some", "spec", "story", "talk", "tell", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "those", "tls", "tls13", "to", "too", "under", "up", "us", "very", "want", "was",
    "way", "we", "were", "what", "whats", "when", "where", "which", "while", "who", "whom", "why", "will", "with",
    "work", "works", "worded", "wording", "would", "written", "yes", "you", "your", "8446", "handled", "handle",
    "approach", "behave", "behaves", "exist", "exists", "thing", "things", "pick", "picked", "chose", "choose",
    "people", "person", "says", "think", "thought", "list", "mailing", "anyone", "everyone", "discussion", "discuss",
    "discussed", "mention", "mentioned", "opinion", "opinions", "search", "find",
}

WORD_RE = re.compile(r"[a-z0-9]+")
MAX_TERMS = 6
PREFIX_MIN = 5

SECTION_HITS_Q = """
CALL db.idx.fulltext.queryNodes('Section', $q) YIELD node, score
MATCH (:Draft {id:$draft})-[:HAS_REVISION]->(:DraftRevision)-[:BECAME]->(:RFC)-[:HAS_SECTION]->(node)
RETURN DISTINCT node.id AS sid, node.number AS number, node.title AS title, node.url AS url, score
ORDER BY score DESC, number
LIMIT $limit
"""

BODY_HITS_Q = """
CALL db.idx.fulltext.queryNodes('MessageBody', $q) YIELD node, score
MATCH (m:Message)-[:HAS_BODY]->(node)
RETURN m.id AS mid, score
"""

SUBJECT_HITS_Q = """
CALL db.idx.fulltext.queryNodes('Message', $q) YIELD node, score
RETURN node.id AS mid, score
"""

MESSAGE_DETAIL_Q = """
UNWIND $mids AS mid
MATCH (m:Message {id:mid})
OPTIONAL MATCH (p:Person)-[:AUTHORED]->(m)
OPTIONAL MATCH (m)-[:IN_THREAD]->(t:Thread)
RETURN m.id AS mid, m.url AS url, m.date AS date, m.subject AS subject,
       coalesce(p.name, m.from) AS person, t.id AS tid, t.url AS turl
"""

MESSAGE_TEXT_Q = """
UNWIND $mids AS mid
MATCH (m:Message {id:mid})-[:HAS_BODY]->(b:MessageBody)
RETURN m.id AS mid, b.text AS text
"""

MESSAGE_CITES_Q = """
UNWIND $mids AS mid
MATCH (m:Message {id:mid})-[:CITES]->(s:Section)
RETURN m.id AS mid, s.number AS number, s.title AS title
"""


def create_indexes(graph) -> list[str]:
    """Create the full-text indexes the entry points rely on. Idempotent: an existing index is left alone."""
    existing = {row["label"] for row in rows(graph, "CALL db.indexes() YIELD label, types RETURN label, types")
                if any("FULLTEXT" in kinds for kinds in (row["types"] or {}).values())}
    for label, prop in INDEXES:
        if label not in existing:
            graph.query(f"CREATE FULLTEXT INDEX FOR (n:{label}) ON (n.{prop})")
    return [label for label, _ in INDEXES]


def _stem(word: str) -> str:
    """Drop a plural ending so the prefix also matches the singular: middleboxes* misses middlebox."""
    if word.endswith("es") and len(word) > 6:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def query_terms(text: str) -> str:
    """Reduce free text to a safe OR-ed full-text query, or "" when nothing is left."""
    seen: set[str] = set()
    terms: list[str] = []
    for word in WORD_RE.findall((text or "").lower()):
        if word in STOP_WORDS or word in seen or word.isdigit():
            continue
        seen.add(word)
        terms.append(_stem(word) + "*" if len(word) >= PREFIX_MIN else word)
        if len(terms) >= MAX_TERMS:
            break
    return "|".join(terms)


def find_sections(graph, text: str, draft: str = DEFAULT_DRAFT, limit: int = 3) -> list[dict]:
    """Sections of the RFC a draft became whose heading matches the question, best first."""
    q = query_terms(text)
    if not q:
        return []
    return rows(graph, SECTION_HITS_Q, {"q": q, "draft": draft, "limit": int(limit)})


def _best_scores(graph, q: str) -> list[tuple[str, float]]:
    merged: dict[str, float] = {}
    for cypher in (BODY_HITS_Q, SUBJECT_HITS_Q):
        for row in rows(graph, cypher, {"q": q}):
            merged[row["mid"]] = max(merged.get(row["mid"], 0.0), float(row["score"] or 0.0))
    return sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))


def search_messages(graph, text: str, limit: int = 10) -> list[dict]:
    """Messages whose body or subject matches the question, best first, each with the clauses it cites."""
    q = query_terms(text)
    if not q:
        return []
    hits = _best_scores(graph, q)[: int(limit)]
    if not hits:
        return []
    mids = [mid for mid, _ in hits]
    details = {row["mid"]: row for row in rows(graph, MESSAGE_DETAIL_Q, {"mids": mids})}
    texts = {row["mid"]: row["text"] or "" for row in rows(graph, MESSAGE_TEXT_Q, {"mids": mids})}
    stems = [term.rstrip("*") for term in q.split("|")]
    cited: dict[str, list[dict]] = {}
    for row in rows(graph, MESSAGE_CITES_Q, {"mids": mids}):
        cited.setdefault(row["mid"], []).append({"number": row["number"], "title": row["title"]})
    return [
        {
            **{key: details.get(mid, {}).get(key) for key in ("url", "date", "subject", "person", "tid", "turl")},
            "mid": mid,
            "score": score,
            "excerpt": excerpt(texts.get(mid, ""), stems),
            "sections": sorted(cited.get(mid, []), key=lambda s: s["number"]),
        }
        for mid, score in hits
    ]


QUOTED_LINE_RE = re.compile(r"^\s*>.*$", re.M)
EMAIL_RE = re.compile(r"<?[\w.+=-]+@[\w.-]+\.\w+>?")


def excerpt(text: str, stems: list[str], width: int = 220) -> str:
    """The sentence-sized stretch of the writer's own words (quoted replies removed) around the first matched term."""
    own = " ".join(EMAIL_RE.sub("[address]", QUOTED_LINE_RE.sub("", text or "")).split())
    lower = own.lower()
    hits = [lower.find(stem) for stem in stems if stem and lower.find(stem) >= 0]
    if not hits:
        return ""
    at = min(hits)
    start = max(0, at - width // 3)
    end = min(len(own), start + width)
    return ("…" if start else "") + own[start:end].strip() + ("…" if end < len(own) else "")
