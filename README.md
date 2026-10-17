# Ratified

A FalkorDB knowledge graph over one IETF working group's public record — drafts,
RFCs, mailing-list threads, chairs and area directors.

## Evaluation

Thirteen questions over the TLS working group's record, in four categories:
single-lookup, collect, aggregate and unanswerable. Every answer key is derived from
the primary record — the RFC Editor text, the datatracker API and the mailarchive
browse pages — by `bench/make_keys.py`, which is a second parser and refuses to run
if the product has been imported. No key is produced by the graph it is used to
grade. `bench/results.json` is the authoritative artefact; this table is read from it.

| Questions answered | Graph (direct) | Graph via the shipped router (post-fix) | RAG (BM25 + bge-small) |
|---|---|---|---|
| single-lookup | 4/4 exact | 3/4 exact, 1 negative | 1/4 exact |
| collect | 3/3 exact | 1/3 exact, 2 negatives | 0/3 |
| aggregate | 3/3 exact | 1/3 exact, 2 negatives | 0/0 *not scoreable* |
| unanswerable | 3/3 abstained | 1/3 abstained, 2 negatives | 0/3 abstained |
| **overall** | **13/13 exact, 0 ties, 0 negatives** | **6/13 exact, 0 ties, 7 negatives** | **1/10 exact, 0 ties, 9 negatives** |

* Graph (direct) is the graph answering the question. "Graph via the shipped router
  (post-fix)" is the free-text path the demo actually runs — question → router →
  catalogue tool — with each card's canonical answer graded, and it is reported
  separately because where the router picks a tool that cannot answer the question's
  shape the graph has not failed but the demo has. A deterministic shape router took
  this column from **1/13** to **6/13**: heading lookup (`a1`, `a2`), the latest
  revision (`a3`), a revision range (`b1`) and a revision count (`c3`) now reach the
  tools that answer them, and the section-number question (`d1`) still abstains.
* The **7 negatives that remain** are not router mislabels: they are shapes the fixed
  catalogue still has no tool for — which RFC a draft became (`a4`), the chairs (`b2`),
  threads named by a subject (`b3`), counting drafts that became an RFC (`c1`) or
  messages in a thread (`c2`), and the out-of-scope ballot/minutes questions (`d2`,
  `d3`), which fall through to the aggregate default rather than abstaining. The
  residual is reported, not hidden: those seven are the next catalogue gaps to close.
* RAG is the comparison baseline: BM25 (rank_bm25) and dense (fastembed's
  `bge-small-en-v1.5`) over the same text the graph ingests, fused by reciprocal rank
  at equal weight, k=60, top-10. It is scored as a retriever, so the aggregate
  questions are marked not scoreable rather than credited: a rank-1 chunk that merely
  contains the digits of a count is not a count.
* Unanswerable, and the honest hard case: for all three, RAG returned confident,
  substance-free context and the graph — read directly — abstained (`the graph does
  not know`). Through the shipped router only `d1` (a section-number shape) abstains;
  the ballot/minutes shapes (`d2`, `d3`) have no catalogue tool to abstain with yet.
* Text-supported subset (`a1`, `a2`, `b3` — the questions whose evidence is inside
  text the RAG corpus indexes): graph 3/3, RAG 1/3. The baseline's weakness on the
  rest is partly structural: only 69 of 2,011 messages carry a body, and the graph
  materialises draft revisions as structure rather than text. Both effects are
  reported rather than hidden.

### Reproduce the table

Needs Python 3.11+ and the offline FalkorDB Docker container available locally.

```sh
docker compose up --build -d               # boots FalkorDB; the app rebuilds the graph on boot
pip install -e '.[bench]'                  # rank_bm25 + fastembed + numpy, once
RATIFIED_FALKOR_PORT=16379 RATIFIED_OFFLINE=1 python -m ratified.bench
```

`RATIFIED_OFFLINE=1` goes on the last line: it is what makes the run provably
network-free, and the bench still needs the local container because line 1 boots it.
`RATIFIED_FALKOR_PORT=16379` is the host-side port compose publishes FalkorDB on
(`127.0.0.1:16379 -> 6379`); without it the bench looks on 6379 and finds nothing.
Wait for `docker compose ps` to report the app healthy before line 3 — the app builds
the graph during start-up, and `python -m ratified.bench` refuses to grade an empty
graph rather than report false negatives. `python -m ratified.bench` derives the keys
from the raw record, answers every question with the graph, retrieves with the RAG
baseline, grades both deterministically and rewrites `bench/results.json`.

## Run

```sh
docker compose up --build        # FalkorDB + the app on http://127.0.0.1:8000
```

## Rebuild the graph

The graph is rebuilt from the record cached in `data/`. With the package installed
(`pip install -e .`) or inside the app container:

```sh
python -m ratified            # rebuild from the local cache
python -m ratified --refresh  # re-fetch datatracker and section text first, then rebuild
```

`--refresh` warms the cache with fresh pulls; without it the command replays the
cache and never touches the network. Both print the node and edge counts.
