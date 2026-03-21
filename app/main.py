"""
main.py — FastAPI RAG service
Endpoints:
  POST /ingest          — upload documents, re-build index
  POST /query           — ask a question, get an answer
  GET  /health          — liveness check
  GET  /index/stats     — how many chunks / sources in the index
"""
from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field

load_dotenv()

# ── Config from .env ─────────────────────────────────────────────
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "Gautamo1/mistral-7b-rag-reader")
EMBED_MODEL      = os.getenv("EMBED_MODEL",     "BAAI/bge-small-en-v1.5")
DEVICE_MAP       = os.getenv("DEVICE_MAP",      "auto")
TORCH_DTYPE      = os.getenv("TORCH_DTYPE",     "bfloat16")
CHUNK_SIZE       = int(os.getenv("CHUNK_SIZE",  "512"))
CHUNK_OVERLAP    = int(os.getenv("CHUNK_OVERLAP","64"))
TOP_K            = int(os.getenv("TOP_K",       "5"))
INDEX_PATH       = Path(os.getenv("INDEX_PATH", "data/index/faiss.index"))
CHUNKS_PATH      = Path(os.getenv("CHUNKS_PATH","data/index/chunks.json"))
DOCS_DIR         = Path("data/docs")
MAX_NEW_TOKENS   = int(os.getenv("MAX_NEW_TOKENS", "512"))
TEMPERATURE      = float(os.getenv("TEMPERATURE",  "0.1"))
DO_SAMPLE        = os.getenv("DO_SAMPLE", "false").lower() == "true"

# ── App state ────────────────────────────────────────────────────
class AppState:
    retriever = None
    generator = None

state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models on startup."""
    from app.retriever import Retriever
    from app.generator import Generator

    logger.info("── Starting up RAG service ──")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

    state.retriever = Retriever(
        model_name=EMBED_MODEL,
        index_path=INDEX_PATH,
        chunks_path=CHUNKS_PATH,
    )

    state.generator = Generator(
        model_name=GENERATOR_MODEL,
        torch_dtype=TORCH_DTYPE,
        device_map=DEVICE_MAP,
        max_new_tokens=MAX_NEW_TOKENS,
        temperature=TEMPERATURE,
        do_sample=DO_SAMPLE,
    )
    logger.info("── Service ready ──")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="Policy RAG API",
    description="Retrieval-Augmented Generation over policy documents",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Schemas ──────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, description="Natural-language question")
    top_k: Optional[int] = Field(None, ge=1, le=20, description="Override default top-k")

class SourceChunk(BaseModel):
    source: str
    chunk_id: int
    score: float
    text: str

class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceChunk]

class IndexStats(BaseModel):
    total_chunks: int
    sources: list[str]
    index_exists: bool


# ── Endpoints ────────────────────────────────────────────────────

@app.get("/health")
def health():
    index_ready = state.retriever is not None and state.retriever.index is not None
    return {
        "status": "ok",
        "index_ready": index_ready,
        "chunks": len(state.retriever.chunks) if index_ready else 0,
    }


@app.get("/index/stats", response_model=IndexStats)
def index_stats():
    if state.retriever is None or state.retriever.index is None:
        return IndexStats(total_chunks=0, sources=[], index_exists=False)
    sources = sorted({c["source"] for c in state.retriever.chunks})
    return IndexStats(
        total_chunks=len(state.retriever.chunks),
        sources=sources,
        index_exists=True,
    )


@app.post("/ingest", summary="Upload documents and rebuild the index")
async def ingest(files: list[UploadFile] = File(...)):
    """
    Upload one or more policy documents (PDF, DOCX, TXT, MD).
    The index is rebuilt from all documents currently in data/docs/
    plus anything newly uploaded here.
    """
    from app.ingestion import ingest_directory, save_chunks
    from app.retriever import Retriever

    if not files:
        raise HTTPException(400, "No files provided")

    saved_names = []
    for upload in files:
        dest = DOCS_DIR / upload.filename
        with dest.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
        saved_names.append(upload.filename)
        logger.info(f"Saved upload: {upload.filename}")

    # Re-ingest entire docs dir
    chunks = ingest_directory(DOCS_DIR, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    if not chunks:
        raise HTTPException(422, "No text could be extracted from the uploaded files.")

    save_chunks(chunks, CHUNKS_PATH)

    # Rebuild FAISS index (replace in-memory state)
    new_retriever = Retriever(model_name=EMBED_MODEL)
    new_retriever.build_index(chunks)
    new_retriever.save(INDEX_PATH, CHUNKS_PATH)
    state.retriever = new_retriever

    return {
        "message": "Index rebuilt successfully",
        "uploaded": saved_names,
        "total_chunks": len(chunks),
        "total_sources": len({c["source"] for c in chunks}),
    }


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    """
    Ask a question over the ingested policy documents.
    Returns the answer and the source chunks used.
    """
    if state.retriever is None or state.retriever.index is None:
        raise HTTPException(503, "Index not ready. POST to /ingest first.")

    top_k = req.top_k or TOP_K

    # 1. Retrieve relevant chunks
    chunks = state.retriever.retrieve(req.question, top_k=top_k)
    if not chunks:
        raise HTTPException(404, "No relevant chunks found in the index.")

    # 2. Build prompt
    prompt = state.generator.build_prompt(req.question, chunks)

    # 3. Generate answer
    logger.info(f"Generating answer for: {req.question!r}")
    answer = state.generator.generate(prompt)

    return QueryResponse(
        question=req.question,
        answer=answer,
        sources=[
            SourceChunk(
                source=c["source"],
                chunk_id=c["chunk_id"],
                score=round(c["score"], 4),
                text=c["text"][:300] + ("…" if len(c["text"]) > 300 else ""),
            )
            for c in chunks
        ],
    )


# ── Dev runner ───────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=False,
    )
