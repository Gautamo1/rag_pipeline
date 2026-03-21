"""
retriever.py — Embed chunks with bge-base-en, build/query FAISS index.
Uses hybrid retrieval: semantic (FAISS) + keyword (BM25-style TF) with
score fusion so identity/name questions that have low semantic overlap
still surface the right chunks.
"""
from __future__ import annotations

import json
import math
import re
import string
from collections import Counter
from pathlib import Path

import faiss
import numpy as np
from loguru import logger
from sentence_transformers import SentenceTransformer


# ── Tiny keyword scorer (no extra deps) ──────────────────────────

def _tokenize(text: str) -> list[str]:
    text = text.lower().translate(str.maketrans("", "", string.punctuation))
    return [t for t in text.split() if len(t) > 1]


def _bm25_scores(query_tokens: list[str], chunks: list[dict],
                 k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    """Minimal BM25 over chunk texts. Returns score array aligned with chunks."""
    corpus = [_tokenize(c["text"]) for c in chunks]
    N = len(corpus)
    avgdl = sum(len(d) for d in corpus) / max(N, 1)

    # document frequency per term
    df: dict[str, int] = {}
    for doc in corpus:
        for t in set(doc):
            df[t] = df.get(t, 0) + 1

    scores = np.zeros(N, dtype=np.float32)
    for term in query_tokens:
        idf = math.log((N - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5) + 1)
        for i, doc in enumerate(corpus):
            tf = doc.count(term)
            if tf == 0:
                continue
            dl = len(doc)
            scores[i] += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))

    return scores


class Retriever:
    """
    Hybrid retriever: dense semantic (bge) + sparse keyword (BM25).
    Scores are min-max normalised then fused with a configurable alpha:
      final = alpha * semantic + (1 - alpha) * keyword
    alpha=1.0  → pure semantic
    alpha=0.0  → pure keyword
    alpha=0.6  → default (semantic-leaning hybrid)
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-base-en-v1.5",
        index_path: Path | None = None,
        chunks_path: Path | None = None,
        alpha: float = 0.6,
    ):
        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()
        self.index: faiss.IndexFlatIP | None = None
        self.chunks: list[dict] = []
        self.alpha = alpha

        if index_path and chunks_path:
            if Path(index_path).exists() and Path(chunks_path).exists():
                self.load(index_path, chunks_path)

    # ── Build ────────────────────────────────────────────────────

    def build_index(self, chunks: list[dict], batch_size: int = 64) -> None:
        texts = [c["text"] for c in chunks]
        logger.info(f"Embedding {len(texts)} chunks…")

        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

        self.index = faiss.IndexFlatIP(self.dim)
        self.index.add(embeddings.astype(np.float32))
        self.chunks = chunks
        logger.success(f"FAISS index built: {self.index.ntotal} vectors")

    # ── Retrieve ─────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Hybrid retrieval — fuses semantic + BM25 scores.
        Always includes chunk_id=0 (document header) when top_k >= 3,
        since identity info (name, contact) lives there.
        """
        if self.index is None:
            raise RuntimeError("Index not built. Call build_index() or load() first.")

        n = self.index.ntotal

        # ── Semantic scores (all chunks) ─────────────────────────
        q_emb = self.model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype(np.float32)

        sem_scores, _ = self.index.search(q_emb, n)
        sem = sem_scores[0]                          # shape (n,)

        # ── Keyword scores ───────────────────────────────────────
        q_tokens = _tokenize(query)
        kw = _bm25_scores(q_tokens, self.chunks) if q_tokens else np.zeros(n)

        # ── Normalise each to [0, 1] ─────────────────────────────
        def _norm(arr: np.ndarray) -> np.ndarray:
            lo, hi = arr.min(), arr.max()
            return (arr - lo) / (hi - lo + 1e-9)

        fused = self.alpha * _norm(sem) + (1 - self.alpha) * _norm(kw)

        # ── Always include the first chunk (doc header / name / contact) ──
        # It's tiny and almost never wins on semantics, but contains identity info.
        top_indices = list(np.argsort(fused)[::-1][:top_k])
        if top_k >= 3 and 0 not in top_indices:
            top_indices[-1] = 0        # replace lowest-ranked with header chunk

        results = []
        for idx in top_indices:
            chunk = dict(self.chunks[idx])
            chunk["score"] = float(fused[idx])
            results.append(chunk)

        return results

    # ── Persist ──────────────────────────────────────────────────

    def save(self, index_path: Path, chunks_path: Path) -> None:
        index_path = Path(index_path)
        chunks_path = Path(chunks_path)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(index_path))
        chunks_path.write_text(json.dumps(self.chunks, ensure_ascii=False, indent=2))
        logger.success(f"Index saved → {index_path}")

    def load(self, index_path: Path, chunks_path: Path) -> None:
        index_path = Path(index_path)
        chunks_path = Path(chunks_path)
        self.index = faiss.read_index(str(index_path))
        self.chunks = json.loads(chunks_path.read_text())
        logger.success(f"Loaded index ({self.index.ntotal} vectors) + {len(self.chunks)} chunks")