"""
ingestion.py — Load PDF / DOCX / TXT / MD → clean text chunks
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from loguru import logger


# ── Loaders ─────────────────────────────────────────────────────

def _load_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
        text = re.sub(r"([.!?])([A-Z])", r"\1 \2", text)
        pages.append(text)
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
    suffix = path.suffix.lower()
    loader = LOADERS.get(suffix)
    if loader is None:
        raise ValueError(f"Unsupported file type: {suffix}")
    logger.info(f"Loading {path.name}")
    return loader(path)


# ── Cleaning ─────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    text = re.sub(r"\x00", "", text)
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Chunking ─────────────────────────────────────────────────────

def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[str]:
    """
    Sliding-window word chunker that splits on paragraph boundaries first,
    then falls back to sentence boundaries.

    Keeps adjacent lines together so key:value fields (Certificate No,
    Intermediary Name, etc.) stay in the same chunk as their values.
    """
    # Split into paragraphs (double newline = paragraph break)
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    chunks: list[str] = []
    current_words: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_words = para.split()

        # If adding this paragraph exceeds chunk_size, flush current buffer
        if current_len + len(para_words) > chunk_size and current_words:
            chunks.append(" ".join(current_words))
            # Keep overlap from end of current buffer
            current_words = current_words[-overlap:] if overlap else []
            current_len = len(current_words)

        # If a single paragraph is itself larger than chunk_size, split by sentence
        if len(para_words) > chunk_size:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                sent_words = sent.split()
                if current_len + len(sent_words) > chunk_size and current_words:
                    chunks.append(" ".join(current_words))
                    current_words = current_words[-overlap:] if overlap else []
                    current_len = len(current_words)
                current_words.extend(sent_words)
                current_len += len(sent_words)
        else:
            current_words.extend(para_words)
            current_len += len(para_words)

    if current_words:
        chunks.append(" ".join(current_words))

    return [c for c in chunks if len(c.strip()) > 20]


# ── Pipeline ─────────────────────────────────────────────────────

def ingest_directory(
    docs_dir: Path,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[dict]:
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
            logger.error(f"  Failed {path.name}: {e}")

    logger.info(f"Total chunks: {len(all_chunks)}")
    return all_chunks


def save_chunks(chunks: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2))
    logger.success(f"Saved {len(chunks)} chunks → {path}")


def load_chunks(path: Path) -> list[dict]:
    return json.loads(path.read_text())