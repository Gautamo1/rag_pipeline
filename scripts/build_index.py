#!/usr/bin/env python3
"""
scripts/build_index.py
──────────────────────
Offline script: ingest all documents in data/docs/ and build the FAISS index.
Run this BEFORE starting the API server (or whenever you add new documents).

Usage:
  python scripts/build_index.py
  python scripts/build_index.py --docs-dir /path/to/policies
  python scripts/build_index.py --docs-dir ./docs --chunk-size 256 --overlap 32
"""
import argparse
import sys
from pathlib import Path

# Add project root to path so 'app' package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import os
from loguru import logger
from app.ingestion import ingest_directory, save_chunks
from app.retriever import Retriever


def main():
    parser = argparse.ArgumentParser(description="Build FAISS index from policy documents")
    parser.add_argument("--docs-dir",   default="data/docs",          help="Directory with policy files")
    parser.add_argument("--index-path", default="data/index/faiss.index")
    parser.add_argument("--chunks-path",default="data/index/chunks.json")
    parser.add_argument("--embed-model",default=os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5"))
    parser.add_argument("--chunk-size", type=int, default=int(os.getenv("CHUNK_SIZE", 512)))
    parser.add_argument("--overlap",    type=int, default=int(os.getenv("CHUNK_OVERLAP", 64)))
    args = parser.parse_args()

    docs_dir    = Path(args.docs_dir)
    index_path  = Path(args.index_path)
    chunks_path = Path(args.chunks_path)

    if not docs_dir.exists():
        logger.error(f"Docs directory not found: {docs_dir}")
        sys.exit(1)

    # 1. Ingest
    chunks = ingest_directory(docs_dir, chunk_size=args.chunk_size, overlap=args.overlap)
    if not chunks:
        logger.error("No chunks produced. Make sure your docs directory has PDF/DOCX/TXT/MD files.")
        sys.exit(1)

    save_chunks(chunks, chunks_path)

    # 2. Embed + index
    retriever = Retriever(model_name=args.embed_model)
    retriever.build_index(chunks)
    retriever.save(index_path, chunks_path)

    logger.success(f"Done. {len(chunks)} chunks indexed from {docs_dir}")
    logger.success(f"Index: {index_path}  |  Chunks: {chunks_path}")


if __name__ == "__main__":
    main()
