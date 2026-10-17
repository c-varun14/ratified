# Ratified

**Ask why a decision was made, and get the dated discussion behind it, the people who were there, and who to ask now. Every answer is a FalkorDB graph path that ends in a public link.**

Every team argues in chat and forgets who decided what. Ratified is a company brain built on an organisation where every argument is public, the IETF's TLS working group, so a judge can click any answer through to the original email.

Graph Hacks 2026 (WeMakeDevs × FalkorDB) · **Track 03: Company Brain** · Live demo: _link added at deploy_ · Demo video: _link added before submission_

![The scenario answered: RFC 8446 §4.2.1 traced from a 2018 mailing-list message, through draft revisions -24 to -28, to the section that shipped](assets/scenario-path.png)

## The scenario (one click on the live page)

You just joined a team shipping TLS 1.3. RFC 8446 negotiates the protocol version in a `supported_versions` extension instead of the version field everyone used before. Why? The people who settled it are spread across years of mailing-list threads.

Ask *"I'm new here: why does RFC 8446 section 4.2.1 read the way it does, and who do I ask?"* and the graph returns:

1. **The discussion.** 6 messages from 5 people in the thread *"draft-ietf-tls-tls13-24 supported_versions complexity"* (1–3 March 2018) cited §4.2.1 while the draft was at -24, and the clause's text at -24 still differed from what shipped.
2. **The traced path.** message → thread → draft-ietf-tls-tls13-24 → -25 → -26 → -27 → -28 → RFC 8446 → §4.2.1. Every node is a link to the datatracker, the mail archive or the RFC Editor.
3. **Who to ask now.** The 5 people who cited the clause, plus the current TLS chairs and area directors, by name from the datatracker.
4. **A drafted question.** Addressed to them, citing the thread and the section. It is rendered on the page and **never sent**: Ratified sends no email.

Ask about a section the RFC doesn't have (§9.4) and the card says **"the graph does not know"**. Ask about IESG ballots or meeting minutes, which were never ingested, and it declines rather than guessing.

## What the graph holds

One FalkorDB graph per working group, rebuilt from the cached public record in one command:

| | Count | Source |
|---|---:|---|
| Mailing-list messages | 2,011 (291 threads, 339 people) | mailarchive.ietf.org browse pages and message downloads |
| Drafts / draft revisions | 113 / 839 | datatracker API (`/api/v1/doc/…`) |
| RFCs a draft became | 66 | datatracker `became_rfc` relations |
| RFC 8446 sections | 84 | rfc-editor.org text |
| Chairs / area directors | 3 / 2 | datatracker roles and person records |
| **Total** | **5,760 nodes · 9,814 edges** | |

### Graph data model

```
(Person)-[:AUTHORED]->(Message)-[:IN_THREAD]->(Thread)
(Message)-[:DISCUSSED]->(DraftRevision)            message names the revision, e.g. "draft-ietf-tls-tls13-24"
(Message)-[:CITES]->(Section)                      "Section 4.2.1" in the message, resolved through that revision's alignment
(Thread)-[:ABOUT_SECTION {matched_tokens}]->(Section)   subject-token overlap (a lead, 17.3% precise; see limits)
(Draft)-[:HAS_REVISION]->(DraftRevision)-[:SUPERSEDED]->(DraftRevision)
(DraftRevision)-[:BECAME]->(RFC)-[:HAS_SECTION]->(Section)
(DraftRevision)-[:ALIGNS_SECTION {similarity, changed, how}]->(Section)
(Draft)-[:IN_WG]->(Wg)<-[:CHAIRS]-(Chair)    (Wg)<-[:AD_FOR]-(AreaDirector)
(Message)-[:HAS_BODY]->(MessageBody)
```

| Node | Key properties |
|---|---|
| `Message` | `id` (mailarchive id), `subject`, `date`, `from`, `url`, `depth`, `has_body` |
| `Thread` | `id` (`tls:<n>`), `subject`, `url`, `n_messages`, `first_date`, `last_date` |
| `DraftRevision` | `id` (`draft-ietf-tls-tls13-24`), `rev`, `date` |
| `Section` | `id` (`rfc8446#4.2.1`), `number`, `title`, `url` (rfc-editor anchor) |
| `Person`, `Chair`, `AreaDirector` | `name`, `email` |

The schema is frozen in [`src/ratified/schema.py`](src/ratified/schema.py), and ingest and every query build their statements from it. Three edges carry the reasoning:

* **`ALIGNS_SECTION`** maps each section of each draft revision to the RFC section it became, **by heading text, not by number**, because numbers shift between revisions. `changed` is true when that revision's section text is less than 98% similar to the shipped text.
* **`DISCUSSED`** links a message to every draft revision it names.
* **`CITES`** links a message to an RFC section, but only through a revision the same message names. "Section 4.2.9" in a message about -21 means *-21's* §4.2.9, which the alignment resolves to RFC §4.2.10. 36 citations resolve; 32 that can't be resolved are dropped rather than guessed.

### The Cypher the product depends on

All Cypher is hand-written and lives in [`src/ratified/tools.py`](src/ratified/tools.py). A free-text question is routed by a deterministic shape router ([`routing.py`](src/ratified/routing.py)) to **one tool from a fixed catalogue**. No model writes Cypher, and no model output becomes a citation.

**`why_clause`: the discussion behind a shipped clause** (the scenario):

```cypher
MATCH (s:Section {id:$sid})
MATCH (m:Message)-[:CITES]->(s)
MATCH (m)-[:DISCUSSED]->(dr:DraftRevision)-[al:ALIGNS_SECTION]->(s)
WHERE al.changed = true
MATCH (m)-[:IN_THREAD]->(t:Thread)
OPTIONAL MATCH (p:Person)-[:AUTHORED]->(m)
RETURN m.id AS mid, m.url AS murl, m.date AS date, m.subject AS subject,
       coalesce(p.name, m.from) AS person, t.id AS tid, t.url AS turl, t.subject AS tsubject,
       collect(DISTINCT dr.id) AS revisions
ORDER BY date, mid
```

**`clause_receipt`: the traced path**, a variable-length walk down the revision chain to the RFC section that shipped:

```cypher
MATCH (s:Section {id:$sid})
MATCH (m:Message)-[:CITES]->(s)
MATCH (m)-[:DISCUSSED]->(dr:DraftRevision)
MATCH (dr)-[al:ALIGNS_SECTION]->(s)
MATCH (m)-[:IN_THREAD]->(t:Thread)
MATCH p=(dr)-[:SUPERSEDED*0..]->(last:DraftRevision)
MATCH (last)-[:BECAME]->(rfc:RFC)-[:HAS_SECTION]->(s)
WHERE al.changed = true
RETURN DISTINCT m.id AS mid, m.url AS murl, m.date AS date, m.subject AS subject,
       t.id AS tid, t.url AS turl,
       [n IN nodes(p) | n.id] AS chain, rfc.id AS rfc,
       s.number AS number, s.title AS title, s.url AS surl,
       al.similarity AS similarity, al.changed AS changed
ORDER BY m.date
```

**`aggregate_unresolved`: clauses discussed while still changing, with no later trail.** Clauses are aggregated across every revision of the draft; for each one, the tool then checks whether any message cites it after the last discussion:

```cypher
MATCH (d:Draft {id:$draft})-[:HAS_REVISION]->(dr:DraftRevision)-[al:ALIGNS_SECTION]->(s:Section)
WHERE al.changed = true
MATCH (m:Message)-[:DISCUSSED]->(dr)
MATCH (m)-[:CITES]->(s)
OPTIONAL MATCH (p:Person)-[:AUTHORED]->(m)
OPTIONAL MATCH (m)-[:IN_THREAD]->(t:Thread)
RETURN s.id AS sid, s.number AS number, s.title AS title, s.url AS url,
       collect(DISTINCT dr.id) AS revisions,
       collect(DISTINCT m.id) AS messages, collect(DISTINCT m.url) AS message_urls,
       collect(DISTINCT m.date) AS dates, collect(DISTINCT p.name) AS people,
       collect(DISTINCT t.id) AS threads, collect(DISTINCT t.url) AS thread_urls
```

Ingest is batched `UNWIND $rows AS r MERGE …` statements generated from the schema ([`schema.py`](src/ratified/schema.py)).

Every answer card carries one of four outcomes: **answer**, **partial** (some evidence missing, and the card says which), **the graph does not know**, or **conflict** (the record disagrees with itself, e.g. a citation that resolves to two clauses).

The full catalogue is `why_clause`, `aggregate_unresolved`, `who_argued`, `what_happened_to`, `precedent`, `sync`, `section_by_heading`, `revisions`, `count_unresolved`, `chairs`, `became_rfc`, `threads_by_subject`, `count_became` and `count_thread_messages`. `sync` re-fetches the last 24 hours of the list and reports what changed.

## Evaluation

Thirteen questions over the TLS working group's record, in four categories. Every answer key is derived from the primary record (the RFC Editor text, the datatracker API, the mailarchive browse pages) by [`bench/make_keys.py`](bench/make_keys.py). That is a second, independent parser, and it refuses to run if the product has been imported, so no key is produced by the graph it grades. [`bench/results.json`](bench/results.json) is the authoritative artefact.

| Questions | Graph (direct Cypher) | Graph via the shipped router | RAG baseline (BM25 + bge-small) |
|---|---|---|---|
| single-lookup | 4/4 | 4/4 | 1/4 |
| collect | 3/3 | 3/3 | 0/3 |
| aggregate (counts) | 3/3 | 3/3 | not scoreable |
| unanswerable | 3/3 abstained | 3/3 abstained | 0/3 (no abstention) |

**Read this table carefully, because it is easy to over-read:**

* **The fair comparison is the text-supported subset.** On the 3 questions whose evidence sits in text the RAG baseline indexes (`a1`, `a2`, `b3`), it is **graph 3/3, RAG 1/3**. On the other 7 scoreable questions, the answer isn't in any text RAG can retrieve (revision lists live in the datatracker structure, and only 69 of 2,011 messages carry a body), so RAG's 0s there mostly measure the corpus, not retrieval.
* **RAG cannot abstain by construction.** It is a top-10 retriever with no score cutoff, so "0/3 abstained" describes the baseline, not a finding.
* **The router column was fitted to these 13 questions.** Two passes of router work took it from 1/13 to 13/13, so it is not a held-out score. A question phrased differently can miss a route.
* **The questions come from the graph's own domain**, so the direct column is favourable by design. RAG is scored as a retriever (key atoms in the rank-1 chunk), with no LLM reading its context, which a generative answerer would improve on.
* **Small n:** 13 questions, reported as raw counts. `b1` and `c3` are the same fact in two forms.

**Citation links, click-verified:** [`bench/verify_chips.py`](bench/verify_chips.py) fetched a stratified sample of **10 of the 132** links the hero and receipt views render, applying the strictest check per kind (the `id="section-N"` anchor must exist; the revision page must name the revision). The first run found **every revision link was a 404** (wrong URL form), which was fixed. After the fix, 10/10 resolve. That is a sample, not the full set.

### Reproduce

```sh
docker compose up --build -d               # FalkorDB + the app; the app rebuilds the graph on boot
pip install -e '.[bench]'                  # rank_bm25 + fastembed + numpy, once
RATIFIED_FALKOR_PORT=16379 RATIFIED_OFFLINE=1 python -m ratified.bench
```

Wait for `docker compose ps` to report the app healthy before the last line. `RATIFIED_OFFLINE=1` makes the run network-free (the record is in `cache/http/`). `16379` is the host port compose publishes FalkorDB on.

## Run it

```sh
git clone <this repo> && cd ratified
docker compose up --build        # FalkorDB + the app on http://127.0.0.1:8000, offline, no keys
```

The public record the graph is built from is committed (`data/`, `cache/http/`, ~23 MB), so a fresh clone builds and runs with no network and no API key. To rebuild the graph by hand (`pip install -e .`):

```sh
python -m ratified            # rebuild from the committed record, no network
python -m ratified --refresh  # re-fetch the datatracker and section text first, then rebuild
```

Tests: `RATIFIED_FALKOR_PORT=16379 pytest` (81 tests against the compose FalkorDB; graph tests skip if none is reachable).

An LLM is optional and off in the demo (`RATIFIED_LLM=off`). When a provider key is set, it only breaks ties in the router and rephrases a card in one sentence, labelled *"LLM phrasing — not a source"*. Responses are cached by (model, prompt, graph hash).

## Prior art

[mnot/ietf-llm](https://github.com/mnot/ietf-llm) builds a queryable corpus of an IETF working group's public record (charter, drafts, RFCs, minutes, mail, GitHub issues) and summarises the positions argued on a topic. Ratified does not claim to be the first to mine working-group arguments. What it adds is a graph: answers are FalkorDB traversals that end in mechanical links (message → thread → revision → RFC section), an empty traversal is reported as "the graph does not know", and the aggregate is a graph-negative ("no later path found").

## Honest limits

**No causal claims.** The graph shows that an objection thread and a changed RFC clause are connected. It does not show that the objection caused the change.

* **Only 69 of 2,011 messages have a body in the record**, so `CITES` has 36 edges. Every "who discussed this clause" answer is drawn from those 69 messages. Clauses with no cited discussion are reported as *partial*, not filled in.
* **"Discussed while still changing" is mechanical**: a message cited the clause and named a revision whose text for it was under 98% similar to the RFC. It does not mean the person objected. Several people it names are the draft's own editors.
* **"No resolution trail"** means no later message in the record cites the clause. Decisions made at meetings, in minutes or in IESG ballots are outside the record and invisible to it.
* **Subject-token leads are weak.** The `ABOUT_SECTION` edges behind the aggregate card's "lead" bucket were hand-checked: **9 of 52** decided links correct (17.3%, 36 ties). They are labelled as leads and kept out of the headline count.
* **The draft↔RFC alignment** was precision-checked only for draft-ietf-tls-tls13 -18 to -28 against RFC 8446, not for the other 65 RFCs.
* **The chairs and area directors are the current ones**, not the ones who chaired in 2018.
* **One working group** (TLS) and one RFC's section text (RFC 8446).

## AI use

AI coding assistants were used throughout. See [AI_USE.md](AI_USE.md) for what each one did and what a person verified.
