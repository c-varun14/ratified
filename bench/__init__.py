"""The evaluation bench: independently keyed questions, a RAG baseline, a grader.

This package is deliberately separate from `ratified`'s ingest and query code so
that the answer keys cannot be derived by the system under test. See
`docs/phase3-notes.md` for the independence argument.
"""
