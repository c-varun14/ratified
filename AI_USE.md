# AI-use disclosure (Graph Hacks rules require this)

AI coding assistants were used throughout this project for research, planning, implementation, tests and documentation. The participant is responsible for the code, can explain the graph model, the Cypher queries and the architecture, and checks results with the reproducible commands in the README (`python -m ratified.bench`, `pytest`, `bench/verify_chips.py`).

Log of assistance (newest last):

- **2026-10-17, idea and critique.** The idea, risk tests and plan were drafted with AI assistance. An external critique by DeepSeek V4.1 Flash (via Command Code) scored it, found prior art (mnot/ietf-llm, cited in the README) and moved the hero away from IESG ballot objections, which the datatracker already documents.
- **2026-10-17, Phase 0–1 (repo skeleton, frozen schema, heading-text alignment, cache-first fetcher, graph rebuild, FastAPI page, tool catalogue, docker compose).** Written by an AI coding agent via Command Code. The seven Phase 1 commits carry its `Co-authored-by: CommandCodeBot` trailer. Human to verify: the schema in `src/ratified/schema.py` and the alignment precision note.
- **2026-10-17, Phase 2–3 (topic-link precision census, traced-path receipt view, sync, the bench, the RAG baseline, citation-link click checks, deterministic router).** Written by an AI coding agent via Command Code, supervised by the participant. The topic-link census (103 links) and the click checks are recorded with their failures, not only their pass rates.
- **2026-10-17 (night), packaging.** Claude Code (Opus 5.5): the `why_clause` tool and the scenario landing page, real chair and area-director names from the datatracker (and the matching fix to the `b2` answer key), rewording of the aggregate card from "argued against" to "discussed while still changing" (the edge never showed an objection), committing the cached public record so a fresh clone builds, and this README. Human to verify: open the scenario on the live page and click every link on the traced path; `pytest` and `python -m ratified.bench` pass.

No model writes Cypher or citations at runtime. The optional LLM only breaks router ties and rephrases a card, labelled as not a source.
