from __future__ import annotations

from ratified import graph as graph_module


def test_a_trace_records_each_query_with_falkordb_time(graph):
    graph_module.start_trace()
    graph_module.rows(graph, "UNWIND range(1, 3) AS x\n   RETURN x", {})
    graph_module.rows(graph, "RETURN $v AS v", {"v": 7})
    trace = graph_module.stop_trace()
    assert [entry["cypher"] for entry in trace] == ["UNWIND range(1, 3) AS x RETURN x", "RETURN $v AS v"]
    assert [entry["rows"] for entry in trace] == [3, 1]
    assert trace[1]["params"] == {"v": 7}
    assert all(entry["ms"] >= 0 for entry in trace)


def test_rows_outside_a_trace_records_nothing(graph):
    assert graph_module.rows(graph, "RETURN 1 AS one") == [{"one": 1}]
    assert graph_module.stop_trace() == []
