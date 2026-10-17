"""Graph projections and FalkorDB algorithms: which clauses go together, and who knows what.

Two projections are derived from the record by Cypher alone and stored in the graph:
CO_CITED joins two RFC sections cited by the same message, and CO_DISCUSSED joins two people who wrote in the same
thread. Both are written in both directions, because PageRank and label propagation follow edge direction and a pair
has none. FalkorDB's own algorithms then run over them. Label propagation is synchronous, so an isolated pair of
clauses swaps labels and never merges; groups of three or more connected clauses converge.
"""
from __future__ import annotations

from .graph import rows

CLEAR_Q = "MATCH ()-[r:{type}]->() DELETE r"

CO_CITED_Q = """
MATCH (a:Section)<-[:CITES]-(m:Message)-[:CITES]->(b:Section)
WHERE a.id <> b.id
WITH a, b, count(DISTINCT m) AS n
MERGE (a)-[r:CO_CITED]->(b)
SET r.n = n
RETURN count(r) AS edges
"""

CO_DISCUSSED_Q = """
MATCH (p:Person)-[:AUTHORED]->(:Message)-[:IN_THREAD]->(t:Thread)<-[:IN_THREAD]-(:Message)<-[:AUTHORED]-(q:Person)
WHERE p.id <> q.id
WITH p, q, count(DISTINCT t) AS n
MERGE (p)-[r:CO_DISCUSSED]->(q)
SET r.n = n
RETURN count(r) AS edges
"""

RELATED_Q = """
MATCH (:Section {id:$sid})-[r:CO_CITED]->(o:Section)
RETURN o.id AS sid, o.number AS number, o.title AS title, o.url AS url, r.n AS n
ORDER BY n DESC, number
LIMIT $limit
"""

COMMUNITIES_Q = """
CALL algo.labelPropagation({nodeLabels:['Section'], relationshipTypes:['CO_CITED']}) YIELD node, communityId
WITH communityId, node WHERE (node)-[:CO_CITED]->()
RETURN communityId AS community, collect({number: node.number, title: node.title}) AS sections
"""

PAGERANK_Q = """
CALL algo.pageRank('Person', 'CO_DISCUSSED') YIELD node, score
WITH node, score WHERE (node)-[:CO_DISCUSSED]->()
RETURN node.id AS pid, node.name AS name, score
ORDER BY score DESC, name
LIMIT $limit
"""

BETWEENNESS_Q = """
CALL algo.betweenness({nodeLabels:['Person'], relationshipTypes:['CO_DISCUSSED']}) YIELD node, score
RETURN node.id AS pid, score
"""

PERSON_REACH_Q = """
UNWIND $pids AS pid
MATCH (p:Person {id:pid})-[:AUTHORED]->(m:Message)
OPTIONAL MATCH (m)-[:IN_THREAD]->(t:Thread)
OPTIONAL MATCH (m)-[:CITES]->(s:Section)
RETURN p.id AS pid, count(DISTINCT t) AS threads, count(DISTINCT s) AS clauses
"""


def derive_projections(graph) -> dict:
    """(Re)build CO_CITED and CO_DISCUSSED from the record. Idempotent: old projection edges are deleted first."""
    counts = {}
    for edge, cypher in (("CO_CITED", CO_CITED_Q), ("CO_DISCUSSED", CO_DISCUSSED_Q)):
        graph.query(CLEAR_Q.format(type=edge))
        counts[edge] = rows(graph, cypher)[0]["edges"]
    return counts


def related_clauses(graph, sid: str, limit: int = 5) -> list[dict]:
    """Sections cited in the same messages as this one, most shared messages first."""
    return rows(graph, RELATED_Q, {"sid": sid, "limit": int(limit)})


def clause_communities(graph) -> list[dict]:
    """Label-propagation communities over CO_CITED with two or more sections, largest first."""
    out = []
    for row in rows(graph, COMMUNITIES_Q):
        sections = sorted(row["sections"], key=lambda s: [int(p) for p in s["number"].split(".")])
        if len(sections) > 1:
            out.append({"community": row["community"], "sections": sections, "size": len(sections)})
    return sorted(out, key=lambda c: (-c["size"], c["sections"][0]["number"]))


def central_people(graph, limit: int = 10) -> list[dict]:
    """People at the centre of who-wrote-with-whom: PageRank and betweenness over CO_DISCUSSED."""
    ranked = rows(graph, PAGERANK_Q, {"limit": int(limit)})
    pids = [row["pid"] for row in ranked]
    between = {row["pid"]: row["score"] for row in rows(graph, BETWEENNESS_Q)}
    reach = {row["pid"]: row for row in rows(graph, PERSON_REACH_Q, {"pids": pids})}
    return [
        {
            "name": row["name"],
            "pagerank": round(row["score"], 4),
            "betweenness": round(between.get(row["pid"], 0.0), 4),
            "threads": reach.get(row["pid"], {}).get("threads", 0),
            "clauses": reach.get(row["pid"], {}).get("clauses", 0),
        }
        for row in ranked
    ]
