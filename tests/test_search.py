from __future__ import annotations

from ratified import ingest, search


def test_create_indexes_is_idempotent(graph):
    first = search.create_indexes(graph)
    second = search.create_indexes(graph)
    assert first == second == ["Section", "Message", "MessageBody"]


def test_query_terms_drops_stop_words_and_ors_prefixed_terms():
    assert search.query_terms("why does the record padding read this way") == "record*|padding*"


def test_query_terms_of_a_stop_word_only_question_is_empty():
    assert search.query_terms("why is it like this?") == ""


def test_query_terms_keeps_no_punctuation():
    q = search.query_terms('what about "Record Padding" (RFC 8446)?')
    assert q == "record*|padding*"


def test_find_sections_ranks_the_padding_clause_first(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    search.create_indexes(graph)
    hits = search.find_sections(graph, "why is record padding like this, in practice?")
    assert hits[0]["sid"] == "rfc8446#5.4"
    assert hits[0]["title"] == "Record Padding"


def test_find_sections_returns_nothing_for_an_unrelated_topic(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    search.create_indexes(graph)
    assert search.find_sections(graph, "quantum teleportation") == []


def test_search_messages_finds_the_body_and_its_citations(graph, sample_dataset):
    ingest.ingest(graph, sample_dataset)
    search.create_indexes(graph)
    hits = search.search_messages(graph, "padding leaks")
    assert hits[0]["mid"] == "aaa111"
    assert hits[0]["person"] == "Ada Lovelace"
    assert hits[0]["tid"] == "tls:1001"
    assert hits[0]["sections"] == [{"number": "5.4", "title": "Record Padding"}]
