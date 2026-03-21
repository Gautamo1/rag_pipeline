"""
ingestion.py — Load PDF / DOCX / TXT / MD → clean text chunks
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Generator

from loguru import logger


# ── Loaders ─────────────────────────────────────────────────────

def _load_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def _load_docx(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _load_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


LOADERS = {
    ".pdf":  _load_pdf,
    ".docx": _load_docx,
    ".doc":  _load_docx,
    ".txt":  _load_txt,
    ".md":   _load_txt,
}


def load_document(path: Path) -> str:
    """Return raw text for any supported file type."""
    suffix = path.suffix.lower()
    loader = LOADERS.get(suffix)
    if loader is None:
        raise ValueError(f"Unsupported file type: {suffix}")
    logger.info(f"Loading {path.name}")
    return loader(path)


# ── Cleaning ─────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)       # collapse blank lines
    text = re.sub(r"[ \t]+", " ", text)           # collapse spaces
    text = re.sub(r"\x00", "", text)              # null bytes from PDFs
    return text.strip()


# ── Chunking ─────────────────────────────────────────────────────

def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[str]:
    """
    Split text into overlapping word-boundary chunks.
    Splits on sentence endings when possible to preserve context.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        words = sent.split()
        if current_len + len(words) > chunk_size:
            if current:
                chunks.append(" ".join(current))
            # keep overlap words from the end
            current = current[-overlap:] if overlap else []
            current_len = len(current)
        current.extend(words)
        current_len += len(words)

    if current:
        chunks.append(" ".join(current))

    return [c for c in chunks if len(c.strip()) > 40]  # discard tiny fragments


# ── Pipeline ─────────────────────────────────────────────────────

def ingest_directory(
    docs_dir: Path,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[dict]:
    """
    Walk docs_dir, load every supported file, return list of chunk dicts:
      { "text": str, "source": str, "chunk_id": int }
    """
    supported = set(LOADERS.keys())
    all_chunks: list[dict] = []

    files = [p for p in docs_dir.rglob("*") if p.suffix.lower() in supported]
    if not files:
        logger.warning(f"No supported documents found in {docs_dir}")
        return all_chunks

    for path in files:
        try:
            raw = load_document(path)
            clean = clean_text(raw)
            chunks = chunk_text(clean, chunk_size=chunk_size, overlap=overlap)
            for i, chunk in enumerate(chunks):
                all_chunks.append({
                    "text": chunk,
                    "source": path.name,
                    "chunk_id": i,
                })
            logger.success(f"  {path.name}: {len(chunks)} chunks")
        except Exception as e:
            logger.error(f"  Failed to process {path.name}: {e}")

    logger.info(f"Total chunks: {len(all_chunks)}")
    return all_chunks


def save_chunks(chunks: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2))
    logger.success(f"Saved {len(chunks)} chunks → {path}")


def load_chunks(path: Path) -> list[dict]:
    return json.loads(path.read_text())
