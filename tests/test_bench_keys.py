from __future__ import annotations

import json
import sys
from pathlib import Path

from bench import make_keys

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {"single_lookup", "collect", "aggregate", "unanswerable"}


def read_questions() -> list[dict]:
    return json.loads((ROOT / "bench" / "questions.json").read_text())


def test_question_set_is_two_tiers_worth_of_questions_across_four_categories():
    questions = read_questions()
    assert 10 <= len(questions) <= 15
    assert {q["category"] for q in questions} == CATEGORIES
    assert len({q["id"] for q in questions}) == len(questions)


def test_keys_are_derived_without_importing_the_product():
    sys.modules.pop("ratified", None)
    record = make_keys.build()
    assert "ratified" not in sys.modules
    assert record["meta"]["n_questions"] == len(read_questions())


def test_every_key_carries_its_source_and_derivation():
    record = make_keys.build()
    for key in record["keys"].values():
        assert key["authoritative_source"]
        assert key["derivation"]["record"]
        assert key["derivation"]["rule"]
        if key["answer_kind"] == "abstain":
            assert key["key"] is None and key["atoms"] == []
        else:
            assert key["key"] not in (None, [], "")
            assert key["atoms"]


def test_keys_match_the_question_set():
    record = make_keys.build()
    assert set(record["keys"]) == {q["id"] for q in read_questions()}


def test_the_unanswerable_keys_are_checked_against_the_primary_source():
    record = make_keys.build()
    d1 = record["keys"]["d1"]
    assert d1["answer_kind"] == "abstain"
    assert d1["derivation"]["evidence"]["rfc_has_section_9_4"] is False
    assert d1["derivation"]["evidence"]["protocol_invariants_at"] == "9.3"


def test_the_committed_keys_match_a_fresh_derivation():
    committed = json.loads((ROOT / "bench" / "keys.json").read_text())
    assert committed["keys"] == make_keys.build()["keys"]
