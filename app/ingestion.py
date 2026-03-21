"""
ingestion.py — Load PDF / DOCX / TXT / MD → clean text chunks
Chunks are split on section boundaries so headings stay glued
to their content (fixes career objective, skills, etc. sections).
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
        # pypdf sometimes joins words without spaces — fix common patterns
        text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)       # camelCase split
        text = re.sub(r"([.!?])([A-Z])", r"\1 \2", text)        # missing space after sentence
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
    text = re.sub(r"\x00", "", text)               # null bytes
    text = re.sub(r"\r\n", "\n", text)             # normalise line endings
    text = re.sub(r"[ \t]+", " ", text)            # collapse spaces/tabs
    text = re.sub(r"\n{3,}", "\n\n", text)         # max 2 blank lines
    return text.strip()


# ── Section-aware chunking ────────────────────────────────────────

# Matches typical resume / policy document section headings:
# ALL CAPS lines, or Title Case lines that are short (< 6 words) and
# followed by a newline — e.g. "Career Objective", "SKILLS", "Education"
SECTION_HEADING_RE = re.compile(
    r"(?m)^[ \t]*("
    r"[A-Z][A-Z\s]{2,40}"           # ALL CAPS heading
    r"|(?:[A-Z][a-z]+\s*){1,5}"     # Title Case short heading
    r"):?\s*$"
)


def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """
    Split text into (heading, body) pairs.
    If no headings found, returns [("", full_text)].
    """
    matches = list(SECTION_HEADING_RE.finditer(text))
    if not matches:
        return [("", text)]

    sections = []
    for i, match in enumerate(matches):
        heading = match.group(0).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections.append((heading, body))

    # Text before first heading (name, contact info, etc.)
    preamble = text[:matches[0].start()].strip()
    if preamble:
        sections.insert(0, ("", preamble))

    return sections


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[str]:
    """
    Section-aware chunking:
    1. Split on section headings first — heading stays glued to its content.
    2. If a section body exceeds chunk_size words, sub-split on sentences.
    3. Small sections (< 30 words) are merged with the next section to avoid
       orphan chunks like a lone heading with no content.
    """
    sections = _split_into_sections(text)
    raw_chunks: list[str] = []

    for heading, body in sections:
        # Combine heading + body as one unit
        full = (f"{heading}\n{body}").strip() if heading else body
        words = full.split()

        if len(words) <= chunk_size:
            raw_chunks.append(full)
        else:
            # Sub-split long sections on sentence boundaries
            sentences = re.split(r"(?<=[.!?])\s+", full)
            current: list[str] = []
            current_len = 0

            for sent in sentences:
                sent_words = sent.split()
                if current_len + len(sent_words) > chunk_size and current:
                    raw_chunks.append(" ".join(current))
                    current = current[-overlap:] if overlap else []
                    current_len = len(current)
                current.extend(sent_words)
                current_len += len(sent_words)

            if current:
                raw_chunks.append(" ".join(current))

    # Merge tiny orphan chunks into the next one
    merged: list[str] = []
    carry = ""
    for chunk in raw_chunks:
        combined = (carry + " " + chunk).strip() if carry else chunk
        if len(combined.split()) < 30 and chunk != raw_chunks[-1]:
            carry = combined   # too small — carry forward and merge with next
        else:
            merged.append(combined)
            carry = ""
    if carry:
        if merged:
            merged[-1] = (merged[-1] + " " + carry).strip()
        else:
            merged.append(carry)

    return [c for c in merged if len(c.strip()) > 20]


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