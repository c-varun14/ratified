from __future__ import annotations

import os

import pytest

from ratified import ingest

RECORD_NODES = {
    "Wg": 1,
    "Person": 403,
    "Chair": 3,
    "AreaDirector": 2,
    "Thread": 633,
    "Message": 3078,
    "Draft": 113,
    "DraftRevision": 839,
    "RFC": 66,
    "Section": 84,
}
RECORD_EDGES = {
    "AUTHORED": 3078,
    "IN_THREAD": 3078,
    "DISCUSSED": 1755,
    "SUPERSEDED": 726,
    "BECAME": 66,
    "CHAIRS": 3,
    "AD_FOR": 2,
    "HAS_REVISION": 839,
    "HAS_SECTION": 84,
    "ALIGNS_SECTION": 861,
    "CITES": 333,
    "ABOUT_SECTION": 229,
    "CO_CITED": 968,
    "CO_DISCUSSED": 40390,
}


def test_ingest_is_idempotent(graph, sample_dataset):
    first = ingest.ingest(graph, sample_dataset)
    second = ingest.ingest(graph, sample_dataset)
    assert first == second


def test_rebuild_reproduces_frozen_counts(graph):
    if not os.path.exists(os.path.join(ingest.DATA_DIR, "docs", "tls_docs.json")):
        pytest.skip("the committed record is not present")
    data = ingest.load_dataset()
    first = ingest.ingest(graph, data)
    second = ingest.ingest(graph, data)
    assert first == second
    for label, count in RECORD_NODES.items():
        assert first["nodes"][label] == count
    for type_, count in RECORD_EDGES.items():
        assert first["edges"][type_] == count
