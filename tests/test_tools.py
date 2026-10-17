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


def test_aggregate_claims_carry_a_clause_id_for_the_receipt(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    result = tools.aggregate_unresolved(graph, "draft-ietf-tls-tls13")
    assert result["claims"]
    assert all(claim["sid"].startswith("rfc8446#") for claim in result["claims"])
    assert all(claim["draft"] == "draft-ietf-tls-tls13" for claim in result["claims"])


def test_aggregate_labels_topic_links_as_leads(graph, sample_dataset):
    data = copy.deepcopy(sample_dataset)
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
    result = tools.aggregate_unresolved(graph, "draft-ietf-tls-tls13")
    buckets: dict[str, list] = {}
    for claim in result["claims"]:
        buckets.setdefault(claim["bucket"], []).append(claim)
    assert any("§5.4" in claim["text"] for claim in buckets["cited"])
    assert any("§5.5" in claim["text"] for claim in buckets["topic"])
    assert result["notes"] and "measured" in result["notes"][0]


def test_clause_receipt_traces_object_thread_revisions_to_section(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    receipt = tools.clause_receipt(graph, "draft-ietf-tls-tls13", "rfc8446#5.4")
    assert receipt["paths"]
    steps = receipt["paths"][0]["steps"]
    kinds = [step["kind"] for step in steps]
    assert kinds[0] == "message"
    assert kinds[1] == "thread"
    assert "revision" in kinds
    assert kinds[-2] == "rfc" and kinds[-1] == "section"
    assert all(step["url"].startswith("http") for step in steps)
    assert receipt["paths"][0]["svg"].startswith("<svg")
    assert 'class="node on-path"' in receipt["paths"][0]["svg"]


def test_clause_receipt_empty_for_unknown_clause(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    assert tools.clause_receipt(graph, "draft-ietf-tls-tls13", "rfc8446#99.9")["paths"] == []
