"""
retriever.py — Embed chunks with bge-small-en, build/query FAISS index
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import faiss
import numpy as np
from loguru import logger
from sentence_transformers import SentenceTransformer


class Retriever:
    """
    Wraps sentence-transformers + FAISS for fast semantic retrieval.
    Uses BAAI/bge-small-en-v1.5 (~33M params) — runs fine on CPU.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        index_path: Path | None = None,
        chunks_path: Path | None = None,
    ):
        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()
        self.index: faiss.IndexFlatIP | None = None
        self.chunks: list[dict] = []

        # Auto-load if paths given and files exist
        if index_path and chunks_path:
            if Path(index_path).exists() and Path(chunks_path).exists():
                self.load(index_path, chunks_path)

    # ── Build ────────────────────────────────────────────────────

    def build_index(self, chunks: list[dict], batch_size: int = 64) -> None:
        """Embed all chunks and build a FAISS inner-product index."""
        texts = [c["text"] for c in chunks]
        logger.info(f"Embedding {len(texts)} chunks (batch={batch_size})…")

        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,   # needed for cosine via inner product
            convert_to_numpy=True,
        )

        self.index = faiss.IndexFlatIP(self.dim)
        self.index.add(embeddings.astype(np.float32))
        self.chunks = chunks
        logger.success(f"FAISS index built: {self.index.ntotal} vectors")

    # ── Retrieve ─────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Return top-k chunk dicts with an added 'score' key.
        """
        if self.index is None:
            raise RuntimeError("Index not built. Call build_index() or load() first.")

        q_emb = self.model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype(np.float32)

        scores, indices = self.index.search(q_emb, top_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            chunk = dict(self.chunks[idx])
            chunk["score"] = float(score)
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
        logger.success(f"Chunks saved → {chunks_path}")

    def load(self, index_path: Path, chunks_path: Path) -> None:
        index_path = Path(index_path)
        chunks_path = Path(chunks_path)
        self.index = faiss.read_index(str(index_path))
        self.chunks = json.loads(chunks_path.read_text())
        logger.success(f"Loaded index ({self.index.ntotal} vectors) + {len(self.chunks)} chunks")
