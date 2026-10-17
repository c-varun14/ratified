from __future__ import annotations

import json
from pathlib import Path

from ratified import routing

QUESTIONS = json.loads((Path(__file__).resolve().parents[1] / "bench" / "questions.json").read_text())

# The deterministic route for every bench question. Every shape now names the
# tool that answers it; the two out-of-scope shapes route to the reserved
# no_answer sentinel, which renders "the graph does not know" instead of bluffing.
ROUTES: dict[str, tuple[str, dict]] = {
    "a1": ("section_by_heading", {"draft": "draft-ietf-tls-tls13", "heading": "Record Padding"}),
    "a2": ("section_by_heading", {"draft": "draft-ietf-tls-tls13", "heading": "Hello Retry Request"}),
    "a3": ("revisions", {"draft": "draft-ietf-tls-tls13", "latest": True}),
    "a4": ("became_rfc", {"draft": "draft-ietf-tls-tls13"}),
    "b1": ("revisions", {"draft": "draft-ietf-tls-tls13", "lo": 18, "hi": 28}),
    "b2": ("chairs", {"wg": "tls"}),
    "b3": ("threads_by_subject", {"pattern": "draft-ietf-tls-tls13-21"}),
    "c1": ("count_became", {"draft": "draft-ietf-tls-"}),
    "c2": ("count_thread_messages", {"thread_or_draft": "tls:1721641"}),
    "c3": ("revisions", {"draft": "draft-ietf-tls-tls13", "count": True}),
    "d1": ("what_happened_to", {"number": "9.4"}),
    "d2": ("no_answer", {"scope": "IESG ballot positions"}),
    "d3": ("no_answer", {"scope": "meeting minutes"}),
}


def test_router_targets_every_bench_question():
    by_id = {question["id"]: question for question in QUESTIONS}
    assert set(by_id) == set(ROUTES)
    for qid, expected in ROUTES.items():
        assert routing.route(by_id[qid]["q"]) == expected, qid


def test_latest_revision_never_routes_to_sync():
    tool, arguments, tied = routing.route_ex(
        "Which is the latest revision of draft-ietf-tls-tls13 in the datatracker?"
    )
    assert tool == "revisions"
    assert arguments == {"draft": "draft-ietf-tls-tls13", "latest": True}
    assert tied is False


def test_only_an_unmatched_shape_is_a_tie_for_the_llm():
    assert routing.route_ex("what is the airspeed velocity of an unladen swallow")[2] is True
    assert routing.route_ex("which is the latest revision of draft-ietf-tls-tls13")[2] is False


def test_shape_rules_are_keyword_explicit():
    assert routing.route("which clauses of draft-ietf-tls-tls13 were argued against and never resolved")[0] == "aggregate_unresolved"
    assert routing.route("who argued about draft-ietf-tls-tls13-21")[0] == "who_argued"
    assert routing.route("what happened to section 5.4") == ("what_happened_to", {"number": "5.4"})
    assert routing.route("is the graph up to date")[0] == "sync"
    assert routing.route("trace the precedent for message abcdefghijklmnop")[0] == "precedent"
    assert routing.route("which section number carries the heading 'Record Padding'")[0] == "section_by_heading"
    assert routing.route("how many revisions of draft-ietf-tls-tls13 are there")[0] == "revisions"
