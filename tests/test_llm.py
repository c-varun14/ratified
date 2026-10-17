from __future__ import annotations

import pytest

from ratified import llm, routing


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm, "_GRAPH_HASH", None)
    return tmp_path


def test_disabled_without_a_key_or_litellm(monkeypatch, graph):
    monkeypatch.delenv("RATIFIED_LLM", raising=False)
    for key in llm.API_KEY_ENVS:
        monkeypatch.delenv(key, raising=False)
    assert llm.enabled() is False
    assert llm.complete("anything", graph=graph) is None
    assert llm.phrase(graph, "q", {"outcome": "answer", "title": "t", "claims": []}) is None
    assert llm.choose_tool(graph, "who argued about draft-ietf-tls-tls13-21") == routing.route(
        "who argued about draft-ietf-tls-tls13-21"
    )


def test_off_switch_disables_even_with_key(monkeypatch, graph):
    monkeypatch.setenv("RATIFIED_LLM", "off")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert llm.enabled() is False


def test_complete_caches_by_model_prompt_and_graph_hash(monkeypatch, graph, cache):
    monkeypatch.setattr(llm, "enabled", lambda: True)
    calls = []
    monkeypatch.setattr(llm, "_call", lambda model, prompt: calls.append((model, prompt)) or "phrasing")

    assert llm.complete("hello", graph=graph) == "phrasing"
    assert llm.complete("hello", graph=graph) == "phrasing"
    assert len(calls) == 1

    assert llm.complete("different", graph=graph) == "phrasing"
    assert len(calls) == 2

    monkeypatch.setattr(llm, "_GRAPH_HASH", "deadbeef")
    assert llm.complete("hello", graph=graph) == "phrasing"
    assert len(calls) == 3
    assert len(list(cache.glob("*.json"))) == 3


def test_choose_tool_validates_against_catalogue(monkeypatch, graph, cache):
    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(
        llm, "_call", lambda model, prompt: '{"tool": "what_happened_to", "arguments": {"number": "5.4", "junk": 1}}'
    )
    assert llm.choose_tool(graph, "?") == ("what_happened_to", {"number": "5.4"})


def test_choose_tool_falls_back_when_reply_is_not_a_known_tool(monkeypatch, graph, cache):
    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(llm, "_call", lambda model, prompt: '{"tool": "not_a_tool", "arguments": {}}')
    question = "who argued about draft-ietf-tls-tls13-21"
    assert llm.choose_tool(graph, question) == routing.route(question)
