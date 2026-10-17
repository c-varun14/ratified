from __future__ import annotations

import os
import uuid

from fastapi.testclient import TestClient
from falkordb import FalkorDB

from ratified import app as app_module
from ratified import ingest


def test_page_serves_and_answers_end_to_end(monkeypatch, falkor, sample_dataset):
    host = os.environ.get("RATIFIED_FALKOR_HOST", "127.0.0.1")
    port = int(os.environ.get("RATIFIED_FALKOR_PORT", "6379"))
    name = f"ratified_app_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("RATIFIED_FALKOR_HOST", host)
    monkeypatch.setenv("RATIFIED_FALKOR_PORT", str(port))
    monkeypatch.setenv("RATIFIED_GRAPH", name)

    graph = FalkorDB(host=host, port=port).select_graph(name)
    try:
        ingest.ingest(graph, sample_dataset)
        client = TestClient(app_module.app)

        page = client.get("/")
        assert page.status_code == 200
        assert "Ratified" in page.text
        assert "aggregate_unresolved" in page.text

        answered = client.post(
            "/ask",
            data={"question": "which clauses of draft-ietf-tls-tls13 were argued against and never resolved"},
        )
        assert answered.status_code == 200
        assert "outcome-answer" in answered.text
        assert "outcome-answer hero" in answered.text
        assert "This is the graph saying: people discussed these clauses" in answered.text
        assert "§5.4" in answered.text
        assert "mailarchive.ietf.org" in answered.text

        why = client.post("/ask", data={"question": "why does section 5.4 read the way it does, and who do I ask?"})
        assert why.status_code == 200
        assert "via <code>why_clause</code>" in why.text
        assert "Ada Lovelace" in why.text
        assert "not sent" in why.text
        assert "limit=1" in why.text

        unknown = client.post("/ask", data={"question": "what happened to section 99.9"})
        assert unknown.status_code == 200
        assert "the graph does not know" in unknown.text

        receipt = client.get("/receipt", params={"draft": "draft-ietf-tls-tls13", "sid": "rfc8446#5.4"})
        assert receipt.status_code == 200
        assert "tls:1001" in receipt.text
        assert "rfc8446" in receipt.text
        assert "rfc8446.html#section-5.4" in receipt.text
        assert "<svg" in receipt.text and "path-graph" in receipt.text

        assert client.get("/health").json() == {"status": "ok"}
    finally:
        graph.delete()


def test_sync_route_renders_the_deferred_state(monkeypatch, falkor):
    host = os.environ.get("RATIFIED_FALKOR_HOST", "127.0.0.1")
    port = int(os.environ.get("RATIFIED_FALKOR_PORT", "6379"))
    monkeypatch.setenv("RATIFIED_FALKOR_HOST", host)
    monkeypatch.setenv("RATIFIED_FALKOR_PORT", str(port))

    def fake_sync(graph, days=1):
        return {
            "tool": "sync",
            "deferred": True,
            "title": "sync deferred (rate limit), graph unchanged",
            "reason": "rate limit",
            "n_changed": 0,
            "new_people": [],
            "aggregate_changed": False,
            "aggregate": None,
            "notes": ["mailarchive could not be re-fetched (rate limit)"],
        }

    monkeypatch.setattr(app_module.tools, "sync", fake_sync)
    client = TestClient(app_module.app)
    response = client.post("/sync")
    assert response.status_code == 200
    assert "sync deferred (rate limit), graph unchanged" in response.text
    assert "graph unchanged" in response.text


def test_out_of_scope_question_declines_instead_of_answering(monkeypatch, falkor):
    host = os.environ.get("RATIFIED_FALKOR_HOST", "127.0.0.1")
    port = int(os.environ.get("RATIFIED_FALKOR_PORT", "6379"))
    monkeypatch.setenv("RATIFIED_FALKOR_HOST", host)
    monkeypatch.setenv("RATIFIED_FALKOR_PORT", str(port))
    client = TestClient(app_module.app)
    response = client.post(
        "/ask",
        data={"question": "Which IESG DISCUSS positions were filed against draft-ietf-tls-tls13?"},
    )
    assert response.status_code == 200
    assert "the graph does not know" in response.text
    assert "outcome-answer" not in response.text
    assert "outcome-unknown" in response.text
