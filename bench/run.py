"""Run the whole bench and write bench/results.json — the authoritative artefact.

Sequence: derive the keys from raw sources, answer every question with the graph,
retrieve for every question with the RAG baseline, grade deterministically, and
record the table together with the run's parameters (signals, RRF constant, top-k,
chunking, corpus sizes). Exposed as `python -m ratified.bench`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from . import grade, graph_runner, make_keys, rag
except ImportError:  # python bench/run.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import grade  # type: ignore
    import graph_runner  # type: ignore
    import make_keys  # type: ignore
    import rag  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.json"
RESULTS = HERE / "results.json"


def _graph_meta() -> dict:
    from ratified.graph import connect, rows

    graph = connect()
    counts = rows(graph, "MATCH (n) RETURN count(n) AS nodes")[0]
    edges = rows(graph, "MATCH ()-[e]->() RETURN count(e) AS edges")[0]
    bodies = rows(graph, "MATCH (m:Message) WHERE m.has_body RETURN count(m) AS n")[0]
    return {"nodes": counts["nodes"], "edges": edges["edges"], "messages_with_body": bodies["n"]}


def _require_graph(graph_meta: dict) -> None:
    """Refuse to grade an empty graph: the app rebuilds it on boot, so wait for health."""
    if graph_meta["nodes"] == 0:
        raise SystemExit(
            "the graph is empty, so every answer would be a false negative.\n"
            "Boot the stack first and wait for it to be healthy — the app rebuilds the graph on "
            "start-up (`docker compose up --build -d`, then `docker compose ps`) — then re-run."
        )


def _hero_observation() -> dict:
    """The hero aggregate is a graph-negative; no independent authority exists for its count."""
    from ratified import tools
    from ratified.graph import connect

    card = tools.aggregate_unresolved(connect())
    attributed = sum(1 for claim in card["claims"] if claim["bucket"] == "cited" and claim["unresolved"])
    return {
        "title": card["title"],
        "attributed_unresolved": attributed,
        "topic_leads": sum(1 for claim in card["claims"] if claim["bucket"] == "topic"),
        "independently_keyed": False,
        "why": (
            "the hero number is a statement about the absence of a resolution trail in this corpus; "
            "there is no external record to key it against, so it is reported as an observation and "
            "excluded from the scored table"
        ),
    }


def _pipeline_answers(questions: list[dict], keys: dict) -> dict[str, dict]:
    """The shipped path: free-text question -> routing.route -> catalogue tool -> card.

    Reported separately from the graph's direct answers because the router is a UX
    convenience, not the graph: where routing guesses the wrong tool the graph has not
    failed, but the demo has.
    """
    from ratified import routing, tools
    from ratified.graph import connect

    graph = connect()
    answers: dict[str, dict] = {}
    for question in questions:
        tool, arguments = routing.route(question["q"])
        card = tools.run(graph, tool, **arguments)
        abstain = card["outcome"] == tools.OUTCOME_UNKNOWN
        answers[question["id"]] = {
            # The card's canonical answer when it carries one (the new tools do),
            # else its title: this is the answer a reader takes off the card.
            "answer": None if abstain else card.get("answer", card["title"]),
            "abstain": abstain,
            "tool": tool,
            "arguments": arguments,
            "outcome": card["outcome"],
            "text": " ".join([card["title"], *[claim["text"] for claim in card["claims"]]]),
        }
    return answers


def build_results(questions_path: Path = QUESTIONS, out_path: Path = RESULTS) -> dict:
    questions = json.loads(questions_path.read_text())
    keys_record = make_keys.build(questions_path)
    keys = keys_record["keys"]
    graph_meta = _graph_meta()
    _require_graph(graph_meta)

    graph_answers = graph_runner.answer_all(questions, keys)
    retriever = rag.Rag()
    retrievals = {q["id"]: retriever.retrieve(q["q"]) for q in questions}
    graded = grade.grade(keys, questions, graph_answers, retrievals)
    pipeline = _pipeline_answers(questions, keys)
    pipeline_graded = grade.score_system(keys, questions, pipeline)
    for entry in graded["questions"]:
        entry["pipeline"] = pipeline[entry["id"]]

    (HERE / "keys.json").write_text(json.dumps(keys_record, indent=2) + "\n")
    chunks = retriever.chunks
    results = {
        "meta": {
            "n_questions": len(questions),
            "categories": keys_record["meta"]["categories"],
            "graph": graph_meta,
            "hero_card": _hero_observation(),
            "rag": {
                "model": rag.MODEL,
                "signals": list(rag.SIGNALS),
                "combination": f"reciprocal rank fusion, equal weight, k={rag.RRF_K}",
                "top_k": rag.TOP_K,
                "chunking": (
                    "one chunk per message (subject + body, capped at 8000 chars, the ingest's cap); "
                    "one chunk per RFC 8446 section (heading + body, same cap)"
                ),
                "corpus_chunks": len(chunks),
                "corpus_messages": sum(1 for c in chunks if c["kind"] == "message"),
                "corpus_sections": sum(1 for c in chunks if c["kind"] == "section"),
                "dense_model_loaded_from_disk": retriever.model_was_cached,
                "hf_hub_offline": retriever.offline,
            },
            "keys_source": keys_record["meta"]["derived_from"],
            "record_counts": keys_record["meta"]["record_counts"],
            "scoring": (
                "exact = normalised equality against the key (RAG: key atoms present in the rank-1 chunk); "
                "substring = every key atom present in the answer text (RAG: in the top-k context); "
                "count questions are not scoreable by retrieval and are reported separately"
            ),
        },
        "table": graded["table"],
        "totals": graded["totals"],
        "abstain": graded["abstain"],
        "subset": grade.subset_summary(graded["questions"], keys),
        "product_pipeline": pipeline_graded,
        "questions": graded["questions"],
    }
    out_path.write_text(json.dumps(results, indent=2) + "\n")
    return results


def _row(label: str, system: dict, total: int) -> str:
    return (
        f"{label:15s} {system['exact']:>7d}/{total:<4d} {system['substring']:>8d}/{total:<4d} "
        f"{system['ties']:>6d} {system['negatives']:>9d}"
    )


def render(results: dict) -> str:
    head = f"{'category':15s} {'exact':>12s} {'substring':>13s} {'ties':>6s} {'negatives':>9s}"
    lines = []
    columns = {
        "GRAPH (direct)": {c: results["table"][c]["graph"] for c in results["table"]},
        "graph via router": results["product_pipeline"]["table"],
    }
    for title, table in columns.items():
        lines.append(title)
        lines.append(head)
        for category, cells in table.items():
            lines.append(_row(category, cells, cells["total"]))
        totals = {field: sum(table[c][field] for c in table) for field in table[next(iter(table))]}
        lines.append(_row("TOTAL", totals, totals["total"]))
        lines.append("")
    lines.append("RAG (BM25 + bge-small, RRF k=60, top-10)")
    lines.append(head)
    for category, cells in results["table"].items():
        lines.append(_row(category, cells["rag"], cells["rag"]["total"]))
    lines.append(_row("TOTAL", results["totals"]["rag"], results["totals"]["rag"]["total"]))
    lines.append(
        f"not scoreable by retrieval: {results['totals']['rag']['not_scoreable']} "
        f"(count questions — a retriever cannot emit a count)"
    )
    abstain = results["abstain"]
    lines.append(
        f"abstain: graph correct on {abstain['graph_correct']}/{abstain['unanswerable']} unanswerable, "
        f"false abstains {abstain['graph_false_abstain']}; rag substance-free on "
        f"{abstain['rag_substance_free']}/{abstain['unanswerable']}"
    )
    subset = results["subset"]
    if subset.get("n"):
        lines.append(
            f"text-supported subset ({subset['n']}: {', '.join(subset['ids'])}): "
            f"graph {subset['graph']['exact']}/{subset['n']} exact, rag {subset['rag']['exact']}/{subset['n']} exact"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Ratified bench and write bench/results.json.")
    parser.add_argument("--questions", default=str(QUESTIONS))
    parser.add_argument("--out", default=str(RESULTS))
    args = parser.parse_args(argv)
    results = build_results(Path(args.questions), Path(args.out))
    print(render(results))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
