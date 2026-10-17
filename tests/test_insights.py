from __future__ import annotations

import copy

import pytest

from ratified import ingest, insights
from ratified.graph import rows


@pytest.fixture
def linked(sample_dataset):
    data = copy.deepcopy(sample_dataset)
    data["messages"].append(
        {
            "id": "ccc333",
            "thread_numeric": 1001,
            "message_id": "<c@example.org>",
            "subject": "Re: draft-ietf-tls-tls13-21: TLS 1.3 Record Padding removal",
            "date": "2017-08-13",
            "from_display": "Alan Turing",
            "from_name": "Alan Turing",
            "from_email": "alan@example.org",
            "depth": 1,
            "url": "https://mailarchive.ietf.org/arch/msg/tls/ccc333/",
            "body": "Section 5.3, Section 5.4 and Section 5.5 of draft-ietf-tls-tls13-21 have to change together.",
        }
    )
    data["sections"]["rfc"]["sections"]["5.3"] = {"number": "5.3", "title": "Per-Record Nonce", "text": "nonce"}
    for number, title in (("5.3", "Per-Record Nonce"), ("5.5", "Record Payload Protection")):
        data["sections"]["drafts"]["draft-ietf-tls-tls13-21"]["align"][number] = {
            "draft_number": number,
            "draft_title": title,
            "rfc_number": number,
            "rfc_title": title,
            "how": "heading",
            "similarity": 0.8,
            "changed": True,
        }
    return data


def test_derive_projections_is_symmetric_and_idempotent(graph, linked):
    ingest.ingest(graph, linked)
    first = insights.derive_projections(graph)
    assert first == {"CO_CITED": 6, "CO_DISCUSSED": 6}
    assert insights.derive_projections(graph) == first
    assert rows(graph, "MATCH ()-[r:CO_CITED]->() RETURN count(r) AS n")[0]["n"] == 6


def test_related_clauses_reads_either_side(graph, linked):
    ingest.ingest(graph, linked)
    insights.derive_projections(graph)
    assert [(r["number"], r["n"]) for r in insights.related_clauses(graph, "rfc8446#5.4")] == [("5.3", 1), ("5.5", 1)]
    assert [(r["number"], r["n"]) for r in insights.related_clauses(graph, "rfc8446#5.5")] == [("5.3", 1), ("5.4", 1)]


def test_clause_communities_group_co_cited_sections(graph, linked):
    ingest.ingest(graph, linked)
    insights.derive_projections(graph)
    communities = insights.clause_communities(graph)
    assert [[s["number"] for s in c["sections"]] for c in communities] == [["5.3", "5.4", "5.5"]]


def test_central_people_rank_everyone_in_the_shared_thread(graph, linked):
    ingest.ingest(graph, linked)
    insights.derive_projections(graph)
    people = insights.central_people(graph)
    assert {p["name"] for p in people} == {"Ada Lovelace", "Grace Hopper", "Alan Turing"}
    assert all(p["pagerank"] > 0 for p in people)
    by_name = {p["name"]: p for p in people}
    assert by_name["Alan Turing"]["clauses"] == 3
    assert by_name["Ada Lovelace"]["clauses"] == 1
    assert by_name["Grace Hopper"]["threads"] == 1
