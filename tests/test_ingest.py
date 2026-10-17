from __future__ import annotations

import os

import pytest

from ratified import ingest

PHASE0_NODES = {
    "Wg": 1,
    "Person": 339,
    "Chair": 3,
    "AreaDirector": 2,
    "Thread": 291,
    "Message": 2011,
    "Draft": 113,
    "DraftRevision": 839,
    "RFC": 66,
    "Section": 84,
}
PHASE0_EDGES = {
    "AUTHORED": 2011,
    "IN_THREAD": 2011,
    "DISCUSSED": 940,
    "SUPERSEDED": 726,
    "BECAME": 66,
    "CHAIRS": 3,
    "AD_FOR": 2,
    "HAS_REVISION": 839,
    "HAS_SECTION": 84,
    "ALIGNS_SECTION": 861,
    "CITES": 36,
    "ABOUT_SECTION": 111,
}


def test_ingest_is_idempotent(graph, sample_dataset):
    first = ingest.ingest(graph, sample_dataset)
    second = ingest.ingest(graph, sample_dataset)
    assert first == second


def test_rebuild_reproduces_frozen_counts(graph):
    if not os.path.exists(os.path.join(ingest.DATA_DIR, "docs", "tls_docs.json")):
        pytest.skip("phase-0 record not present")
    data = ingest.load_dataset()
    first = ingest.ingest(graph, data)
    second = ingest.ingest(graph, data)
    assert first == second
    for label, count in PHASE0_NODES.items():
        assert first["nodes"][label] == count
    for type_, count in PHASE0_EDGES.items():
        assert first["edges"][type_] == count
