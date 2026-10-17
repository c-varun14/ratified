from __future__ import annotations

from bench import grade


def test_graph_scores_exact_and_substring_separately():
    key = {"answer_kind": "text", "key": "5.4", "atoms": ["5.4"]}
    assert grade.score_graph(key, {"abstain": False, "answer": "5.4", "text": "§5.4 Record Padding"}) == {
        "scoreable": True, "exact": True, "substring": True, "abstained": False
    }
    partial = grade.score_graph(key, {"abstain": False, "answer": "section five", "text": "the 5.4 padding clause"})
    assert partial["substring"] and not partial["exact"]


def test_graph_abstention_is_the_pass_condition_for_an_abstain_key():
    key = {"answer_kind": "abstain", "key": None, "atoms": []}
    assert grade.score_graph(key, {"abstain": True})["exact"]
    assert not grade.score_graph(key, {"abstain": False, "answer": "something", "text": "something"})["exact"]


def test_a_retriever_cannot_be_credited_for_a_count():
    key = {"answer_kind": "number", "key": 24, "atoms": ["24"]}
    retrieval = {"ids": ["msg:x"], "texts": ["we sent 24 messages that week"]}
    score = grade.score_rag(key, retrieval)
    assert score["scoreable"] is False
    assert not score["exact"] and not score["substring"]


def test_a_retriever_never_abstains_on_an_unanswerable_question():
    key = {"answer_kind": "abstain", "key": None, "atoms": []}
    retrieval = {"ids": ["sec:rfc8446#9.3"], "texts": ["§9.3 Protocol Invariants and the section body"]}
    score = grade.score_rag(key, retrieval)
    assert score["scoreable"] and not score["exact"] and not score["abstained"]


def test_ties_and_negatives_are_counted_per_category():
    questions = [
        {"id": "q1", "q": "?", "category": "collect"},
        {"id": "q2", "q": "?", "category": "collect"},
    ]
    keys = {
        "q1": {"category": "collect", "answer_kind": "text", "key": "a", "atoms": ["a"]},
        "q2": {"category": "collect", "answer_kind": "text", "key": "b", "atoms": ["b"]},
    }
    answers = {
        "q1": {"abstain": False, "answer": "x a", "text": "x a"},
        "q2": {"abstain": False, "answer": "nothing", "text": "nothing"},
    }
    scored = grade.score_system(keys, questions, answers)
    assert scored["table"]["collect"]["exact"] == 0
    assert scored["table"]["collect"]["substring"] == 1
    assert scored["table"]["collect"]["ties"] == 1
    assert scored["table"]["collect"]["negatives"] == 1
