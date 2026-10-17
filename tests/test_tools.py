from __future__ import annotations

import copy

from ratified import ingest, routing, tools


def test_aggregate_unresolved_reports_the_hero_clause(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.aggregate_unresolved(graph, "draft-ietf-tls-tls13")
    assert result["outcome"] == "answer"
    assert any("§5.4" in claim["text"] for claim in result["claims"])
    assert any(claim["unresolved"] for claim in result["claims"])
    assert any(chip["kind"] == "section" for chip in result["chips"])
    assert all(chip["url"].startswith("http") for chip in result["chips"])


def test_who_argued_lists_people(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.who_argued(graph, "draft-ietf-tls-tls13")
    assert result["outcome"] == "answer"
    assert {claim["text"].split(" — ")[0] for claim in result["claims"]} == {"Ada Lovelace", "Grace Hopper"}


def test_precedent_traces_message_to_rfc_section(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.precedent(graph, "aaa111")
    assert result["outcome"] == "answer"
    assert any("rfc8446" in claim["text"] for claim in result["claims"])
    assert any(chip["kind"] == "section" for chip in result["chips"])
    assert any(chip["kind"] == "revision" for chip in result["chips"])


def test_precedent_unknown_when_no_path(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.precedent(graph, "no-such-message")
    assert result["outcome"] == "unknown"
    assert result["outcome_message"] == "the graph does not know"


def test_precedent_conflict_when_citation_is_ambiguous(graph, sample_dataset):
    data = copy.deepcopy(sample_dataset)
    data["messages"].append(
        {
            "id": "ccc333",
            "thread_numeric": 1001,
            "message_id": "<c@example.org>",
            "subject": "draft-ietf-tls-tls13-21 padding and protection",
            "date": "2017-08-13",
            "from_display": "Ada Lovelace",
            "from_name": "Ada Lovelace",
            "from_email": "ada@example.org",
            "depth": 2,
            "url": "https://mailarchive.ietf.org/arch/msg/tls/ccc333/",
            "body": "See Section 5.4 and Section 5.5 of draft-ietf-tls-tls13-21.",
        }
    )
    data["sections"]["drafts"]["draft-ietf-tls-tls13-21"]["align"]["5.5"] = {
        "draft_number": "5.5",
        "draft_title": "Record Payload Protection",
        "rfc_number": "5.5",
        "rfc_title": "Record Payload Protection",
        "how": "heading",
        "similarity": 0.9,
        "changed": True,
    }
    ingest.ingest(graph, data)
    result = tools.precedent(graph, "ccc333")
    assert result["outcome"] == "conflict"
    assert result["conflicts"]


def test_what_happened_to_reports_alignment_and_unknown(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    known = tools.what_happened_to(graph, "5.4")
    assert known["outcome"] == "answer"
    assert any("changed" in claim["text"] for claim in known["claims"])
    assert any(chip["kind"] == "rfc" for chip in known["chips"])

    unknown = tools.what_happened_to(graph, "99.9")
    assert unknown["outcome"] == "unknown"


def test_routing_maps_questions_to_the_catalogue():
    assert routing.route("which clauses were argued against and never resolved")[0] == "aggregate_unresolved"
    assert routing.route("who argued about draft-ietf-tls-tls13-21")[0] == "who_argued"
    assert routing.route("what happened to section 5.4") == ("what_happened_to", {"number": "5.4"})
    assert routing.route("is the graph up to date")[0] == "sync"
    assert routing.route("trace the precedent for message abcdefghijklmnop")[0] == "precedent"
    assert routing.route("anything at all")[0] == "aggregate_unresolved"
    assert routing.route("who argued about draft-ietf-tls-tls13-28")[1] == {"draft": "draft-ietf-tls-tls13"}
