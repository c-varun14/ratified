from __future__ import annotations

from ratified import ingest, schema

FROZEN_NODES = {
    "Wg": ("name", "email"),
    "Person": ("name", "email"),
    "Chair": ("name", "email"),
    "AreaDirector": ("name", "email"),
    "Thread": ("subject", "url", "n_messages", "first_date", "last_date"),
    "Message": ("message_id", "subject", "date", "from", "url", "depth", "has_body"),
    "MessageBody": ("text",),
    "Draft": ("title", "latest_rev"),
    "DraftRevision": ("revision", "rev", "date"),
    "RFC": ("number", "title", "url"),
    "Section": ("number", "title", "url"),
}

FROZEN_EDGES = {
    "AUTHORED": ("Person", "Message", ()),
    "IN_THREAD": ("Message", "Thread", ()),
    "HAS_BODY": ("Message", "MessageBody", ()),
    "CHAIRS": ("Chair", "Wg", ()),
    "AD_FOR": ("AreaDirector", "Wg", ()),
    "IN_WG": ("Draft", "Wg", ()),
    "HAS_REVISION": ("Draft", "DraftRevision", ()),
    "SUPERSEDED": ("DraftRevision", "DraftRevision", ()),
    "BECAME": ("DraftRevision", "RFC", ()),
    "DISCUSSED": ("Message", "DraftRevision", ()),
    "CITES": ("Message", "Section", ()),
    "ABOUT_SECTION": ("Thread", "Section", ("matched_tokens",)),
    "HAS_SECTION": ("RFC", "Section", ()),
    "ALIGNS_SECTION": ("DraftRevision", "Section", ("similarity", "changed", "how")),
}


def test_frozen_vocabulary():
    assert schema.SCHEMA_VERSION == 1
    assert {label: node.props for label, node in schema.NODES.items()} == FROZEN_NODES
    assert {
        type_: (edge.source, edge.target, edge.props) for type_, edge in schema.EDGES.items()
    } == FROZEN_EDGES


def test_merge_statements_reference_key_and_props():
    assert schema.merge_nodes("Message") == (
        "UNWIND $rows AS r MERGE (n:Message {id:r.id}) SET n.message_id=r.message_id, "
        "n.subject=r.subject, n.date=r.date, n.from=r.from, n.url=r.url, n.depth=r.depth, "
        "n.has_body=r.has_body"
    )
    assert schema.merge_edges("ALIGNS_SECTION") == (
        "UNWIND $rows AS r MATCH (a:DraftRevision {id:r.src}), (b:Section {id:r.tgt}) "
        "MERGE (a)-[x:ALIGNS_SECTION]->(b) SET x.similarity=r.similarity, "
        "x.changed=r.changed, x.how=r.how"
    )


def test_round_trip(graph, sample_dataset):
    counts = ingest.ingest(graph, sample_dataset)

    assert counts["nodes"] == {
        "Wg": 1,
        "Person": 2,
        "Chair": 1,
        "AreaDirector": 1,
        "Thread": 1,
        "Message": 2,
        "MessageBody": 2,
        "Draft": 1,
        "DraftRevision": 2,
        "RFC": 1,
        "Section": 2,
    }
    assert counts["edges"] == {
        "AUTHORED": 2,
        "IN_THREAD": 2,
        "HAS_BODY": 2,
        "CHAIRS": 1,
        "AD_FOR": 1,
        "IN_WG": 1,
        "HAS_REVISION": 2,
        "SUPERSEDED": 1,
        "BECAME": 1,
        "DISCUSSED": 2,
        "CITES": 1,
        "ABOUT_SECTION": 2,
        "HAS_SECTION": 2,
        "ALIGNS_SECTION": 1,
    }
    assert counts["cites_unresolved"] == 0

    section = graph.query(
        "MATCH (s:Section {id:'rfc8446#5.4'}) RETURN s.title, s.url"
    ).result_set[0]
    assert section == ["Record Padding", "https://www.rfc-editor.org/rfc/rfc8446.html#section-5.4"]

    align = graph.query(
        "MATCH (:DraftRevision {id:'draft-ietf-tls-tls13-21'})-[e:ALIGNS_SECTION]->"
        "(:Section {id:'rfc8446#5.4'}) RETURN e.changed, e.how"
    ).result_set[0]
    assert align == [True, "heading"]

    path = graph.query(
        "MATCH (m:Message)-[:DISCUSSED]->(:DraftRevision {id:'draft-ietf-tls-tls13-21'}) "
        "MATCH (m)-[:CITES]->(:Section {id:'rfc8446#5.4'}) RETURN count(DISTINCT m)"
    ).result_set[0][0]
    assert path == 1
