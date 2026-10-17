from __future__ import annotations

import json
from pathlib import Path

from ratified import routing, tools

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


def test_each_new_shape_routes_to_its_tool():
    assert routing.route_ex("Who are the chairs of the TLS working group?") == ("chairs", {"wg": "tls"}, False)
    assert routing.route_ex("Which RFC did draft-ietf-tls-tls13 become?") == (
        "became_rfc", {"draft": "draft-ietf-tls-tls13"}, False
    )
    assert routing.route_ex("Which threads name draft-ietf-tls-tls13-21 in the subject?") == (
        "threads_by_subject", {"pattern": "draft-ietf-tls-tls13-21"}, False
    )
    assert routing.route_ex("How many draft-ietf-tls-* drafts became an RFC?") == (
        "count_became", {"draft": "draft-ietf-tls-"}, False
    )
    assert routing.route_ex("How many messages does the archive show in thread tls:1721641?") == (
        "count_thread_messages", {"thread_or_draft": "tls:1721641"}, False
    )


def test_out_of_scope_shapes_route_to_the_no_answer_sentinel():
    assert routing.route_ex("Which IESG DISCUSS positions were filed against draft-ietf-tls-tls13?") == (
        "no_answer", {"scope": "IESG ballot positions"}, False
    )
    assert routing.route_ex("Which TLS working-group meeting minutes record the decision to adopt draft-ietf-tls-tls13?") == (
        "no_answer", {"scope": "meeting minutes"}, False
    )
    # the sentinel is reserved, never offered as a tool the LLM or a reader can pick
    assert tools.NO_ANSWER not in {tool["name"] for tool in tools.TOOL_CATALOGUE}
    assert tools.NO_ANSWER not in tools.TOOLS


def test_the_abstention_card_declines_with_the_unknown_outcome():
    result = tools.run(None, tools.NO_ANSWER, scope="IESG ballot positions")
    assert result["outcome"] == "unknown"
    assert result["answer"] is None
    assert result["outcome_message"] == "the graph does not know"
    assert "IESG ballot positions" in result["title"]


# The questions the post-fix bench scored exact, before this follow-up. Their
# routes must not drift (the full thirteen are pinned by ROUTES above).
PRE_FOLLOW_UP_PASSING = ["a1", "a2", "a3", "b1", "c3", "d1"]


def test_pre_follow_up_passing_routes_are_unchanged():
    by_id = {question["id"]: question for question in QUESTIONS}
    for qid in PRE_FOLLOW_UP_PASSING:
        assert routing.route(by_id[qid]["q"]) == ROUTES[qid], qid


def test_why_questions_route_to_why_clause():
    assert routing.route("I'm new here: why does RFC 8446 section 4.2.1 read the way it does, and who do I ask?") == (
        "why_clause",
        {"number": "4.2.1", "draft": "draft-ietf-tls-tls13"},
    )
    assert routing.route("who do I ask about §4.2.11?")[0] == "why_clause"
    assert routing.route("why is 'Supported Versions' like this?") == (
        "why_clause",
        {"heading": "Supported Versions", "draft": "draft-ietf-tls-tls13"},
    )


def test_a_contraction_is_not_read_as_a_quoted_heading():
    assert routing.route("what's the story behind 'Key Share' reading the way it does?") == (
        "why_clause",
        {"heading": "Key Share", "draft": "draft-ietf-tls-tls13"},
    )


def test_casual_phrasings_reach_their_shapes():
    assert routing.route("how come RFC 8446 section 4.2.11 ended up worded the way it is?")[0] == "why_clause"
    assert routing.route("who's leading the tls working group right now?")[0] == "chairs"
    assert routing.route("how many times was draft-ietf-tls-tls13 revised in total?")[1] == {
        "draft": "draft-ietf-tls-tls13",
        "count": True,
    }
    assert routing.route("which draft-ietf-tls-tls13 revisions sit between -20 and -25?")[1] == {
        "draft": "draft-ietf-tls-tls13",
        "lo": 20,
        "hi": 25,
    }
    assert routing.route("which RFC did draft-ietf-tls-tls13 turn into?")[0] == "became_rfc"
    assert routing.route("who took part in the discussion of draft-ietf-tls-tls13?")[0] == "who_argued"


def test_why_without_a_clause_keeps_the_old_routes():
    assert routing.route("Which RFC 8446 section numbered 9.4 covers protocol invariants?")[0] == "what_happened_to"
    assert routing.route("why 4BwmDeAqZ1ccHKkEk1R9tqdXTW8")[0] == "precedent"
