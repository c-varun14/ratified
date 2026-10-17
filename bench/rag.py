"""The RAG baseline the graph is compared against: BM25 + dense, RRF-combined.

Corpus and chunking are the ones the graph ingests, so the text volume is the same:
one chunk per message (subject plus body, capped at the ingest's 8000 characters)
and one chunk per RFC 8446 section (heading plus body, same cap). Chunks are built
with `ratified.ingest.load_dataset`, so the two systems provably read the same text.

Retrieval combines the two signals reciprocally and with equal weight:

    score(chunk) = 1 / (60 + rank_bm25(chunk)) + 1 / (60 + rank_dense(chunk))

top-k = 10 (rank_bm25's BM25Okapi over the same tokens; fastembed's
BAAI/bge-small-en-v1.5 for the 384-dim dense side, cosine scored on unit vectors).

Everything here runs offline against `data/` and the local HTTP cache. The dense
model is fetched once on a cold machine and cached in the Hugging Face home; after
that `local_files_only` keeps the run on disk.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np

from ratified.ingest import TEXT_CAP, load_dataset

MODEL = "BAAI/bge-small-en-v1.5"
RRF_K = 60
TOP_K = 10
SIGNALS = ("bm25", "dense")
TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


def corpus(data_dir: str | None = None) -> list[dict]:
    """The chunk list: messages first, then RFC 8446 sections, each capped like ingest."""
    data = load_dataset(data_dir) if data_dir else load_dataset()
    chunks: list[dict] = []
    for message in data["messages"]:
        text = (message.get("subject") or "") + "\n" + (message.get("body") or "")
        chunks.append({"id": f"msg:{message['id']}", "kind": "message", "text": text[:TEXT_CAP]})
    sections = data["sections"]["rfc"]["sections"]
    rfc = data["sections"]["rfc"]["name"]
    for number, section in sections.items():
        text = f"§{number} {section['title']}\n{section.get('text') or ''}"
        chunks.append({"id": f"sec:{rfc}#{number}", "kind": "section", "text": text[:TEXT_CAP]})
    return chunks


def _embedder():
    from fastembed import TextEmbedding

    try:
        return TextEmbedding(MODEL, local_files_only=True), True
    except Exception:  # cold machine: fetch the model once, then it is cached
        return TextEmbedding(MODEL), False


class Rag:
    """Hybrid retriever over the ingest corpus. Build once, then .retrieve(question)."""

    def __init__(self, chunks: list[dict] | None = None, data_dir: str | None = None):
        from rank_bm25 import BM25Okapi

        self.chunks = chunks if chunks is not None else corpus(data_dir)
        self.texts = [chunk["text"] for chunk in self.chunks]
        self.bm25 = BM25Okapi([tokens(text) for text in self.texts])
        embedder, cached = _embedder()
        self.model_was_cached = cached
        vectors = np.array(list(embedder.embed(self.texts)), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        self.dense = vectors / np.where(norms == 0, 1.0, norms)
        self.embedder = embedder
        self.offline = os.environ.get("HF_HUB_OFFLINE") == "1"

    def _ranks(self, question: str) -> dict[str, list[str]]:
        from rank_bm25 import BM25Okapi  # noqa: F401  (keep the dependency explicit)

        bm_scores = self.bm25.get_scores(tokens(question))
        bm_order = np.argsort(-bm_scores)
        query = np.array(list(self.embedder.embed([question]))[0], dtype=np.float32)
        query /= max(float(np.linalg.norm(query)), 1e-9)
        de_order = np.argsort(-(self.dense @ query))
        return {
            "bm25": [self.chunks[i]["id"] for i in bm_order],
            "dense": [self.chunks[i]["id"] for i in de_order],
        }

    def retrieve(self, question: str, top_k: int = TOP_K) -> dict:
        ranks = self._ranks(question)
        fused: dict[str, float] = {}
        for signal in SIGNALS:
            for rank, chunk_id in enumerate(ranks[signal]):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        order = sorted(fused, key=lambda cid: (-fused[cid], cid))[:top_k]
        by_id = {chunk["id"]: chunk for chunk in self.chunks}
        return {
            "ids": order,
            "texts": [by_id[cid]["text"] for cid in order],
            "rank_bm25": {cid: ranks["bm25"].index(cid) for cid in order},
            "rank_dense": {cid: ranks["dense"].index(cid) for cid in order},
        }
