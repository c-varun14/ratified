"""Frozen v1 graph schema for the Ratified FalkorDB store.

Phase 0 proposed this schema and Phase 1 freezes it: node labels, their identity
property, the properties each node carries, and the edge vocabulary with endpoint
labels. Ingest and every query tool build statements from these declarations, so
the writer and the readers cannot drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 2
GRAPH_NAME = "ratified"
KEY = "id"


@dataclass(frozen=True)
class NodeDef:
    label: str
    props: tuple[str, ...]


@dataclass(frozen=True)
class EdgeDef:
    type: str
    source: str
    target: str
    props: tuple[str, ...] = ()


NODES: dict[str, NodeDef] = {
    "Wg": NodeDef("Wg", ("name", "email")),
    "Person": NodeDef("Person", ("name", "email")),
    "Chair": NodeDef("Chair", ("name", "email")),
    "AreaDirector": NodeDef("AreaDirector", ("name", "email")),
    "Thread": NodeDef("Thread", ("subject", "url", "n_messages", "first_date", "last_date")),
    "Message": NodeDef("Message", ("message_id", "subject", "date", "from", "url", "depth", "has_body")),
    "MessageBody": NodeDef("MessageBody", ("text",)),
    "Draft": NodeDef("Draft", ("title", "latest_rev")),
    "DraftRevision": NodeDef("DraftRevision", ("revision", "rev", "date")),
    "RFC": NodeDef("RFC", ("number", "title", "url")),
    "Section": NodeDef("Section", ("number", "title", "url")),
}

EDGES: dict[str, EdgeDef] = {
    "AUTHORED": EdgeDef("AUTHORED", "Person", "Message"),
    "IN_THREAD": EdgeDef("IN_THREAD", "Message", "Thread"),
    "HAS_BODY": EdgeDef("HAS_BODY", "Message", "MessageBody"),
    "CHAIRS": EdgeDef("CHAIRS", "Chair", "Wg"),
    "AD_FOR": EdgeDef("AD_FOR", "AreaDirector", "Wg"),
    "IN_WG": EdgeDef("IN_WG", "Draft", "Wg"),
    "HAS_REVISION": EdgeDef("HAS_REVISION", "Draft", "DraftRevision"),
    "SUPERSEDED": EdgeDef("SUPERSEDED", "DraftRevision", "DraftRevision"),
    "BECAME": EdgeDef("BECAME", "DraftRevision", "RFC"),
    "DISCUSSED": EdgeDef("DISCUSSED", "Message", "DraftRevision"),
    "CITES": EdgeDef("CITES", "Message", "Section"),
    "ABOUT_SECTION": EdgeDef("ABOUT_SECTION", "Thread", "Section", ("matched_tokens",)),
    "HAS_SECTION": EdgeDef("HAS_SECTION", "RFC", "Section"),
    "ALIGNS_SECTION": EdgeDef(
        "ALIGNS_SECTION", "DraftRevision", "Section", ("similarity", "changed", "how")
    ),
    "CO_CITED": EdgeDef("CO_CITED", "Section", "Section", ("n",)),
    "CO_DISCUSSED": EdgeDef("CO_DISCUSSED", "Person", "Person", ("n",)),
}

DERIVED_EDGES = ("CO_CITED", "CO_DISCUSSED")


def merge_nodes(label: str) -> str:
    node = NODES[label]
    sets = ", ".join(f"n.{p}=r.{p}" for p in node.props)
    return f"UNWIND $rows AS r MERGE (n:{label} {{{KEY}:r.id}}) SET {sets}"


def merge_edges(type_: str) -> str:
    edge = EDGES[type_]
    stmt = (
        f"UNWIND $rows AS r MATCH (a:{edge.source} {{{KEY}:r.src}}), "
        f"(b:{edge.target} {{{KEY}:r.tgt}}) MERGE (a)-[x:{type_}]->(b)"
    )
    if edge.props:
        stmt += " SET " + ", ".join(f"x.{p}=r.{p}" for p in edge.props)
    return stmt
