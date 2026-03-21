"""
main.py — FastAPI RAG service
Endpoints:
  POST /query           — pass a file URL + list of questions, get answers for all
  POST /ingest          — upload documents directly, rebuild index
  GET  /health          — liveness check
  GET  /index/stats     — chunks / sources in the index
"""
from __future__ import annotations

import os
import shutil
import tempfile
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel, Field

load_dotenv()

GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "Gautamo1/mistral-7b-rag-reader")
EMBED_MODEL      = os.getenv("EMBED_MODEL",     "BAAI/bge-base-en-v1.5")
DEVICE_MAP       = os.getenv("DEVICE_MAP",      "auto")
TORCH_DTYPE      = os.getenv("TORCH_DTYPE",     "bfloat16")
CHUNK_SIZE       = int(os.getenv("CHUNK_SIZE",   "512"))
CHUNK_OVERLAP    = int(os.getenv("CHUNK_OVERLAP","64"))
TOP_K            = int(os.getenv("TOP_K",        "8"))
INDEX_PATH       = Path(os.getenv("INDEX_PATH",  "data/index/faiss.index"))
CHUNKS_PATH      = Path(os.getenv("CHUNKS_PATH", "data/index/chunks.json"))
DOCS_DIR         = Path("data/docs")
MAX_NEW_TOKENS   = int(os.getenv("MAX_NEW_TOKENS","512"))
TEMPERATURE      = float(os.getenv("TEMPERATURE", "0.1"))
DO_SAMPLE        = os.getenv("DO_SAMPLE","false").lower() == "true"
COMPILE_MODEL    = os.getenv("COMPILE_MODEL","true").lower() == "true"

SUPPORTED_EXTS = {".pdf", ".docx", ".doc", ".txt", ".md"}


class AppState:
    retriever = None
    generator = None

state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
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
        compile_model=COMPILE_MODEL,
    )
    logger.info("── Service ready ──")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="Policy RAG API",
    description="Pass a document URL and a list of questions — get answers grounded in that document.",
    version="2.0.0",
    lifespan=lifespan,
)


# ── Schemas ──────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    url: str = Field(
        ...,
        description="Publicly accessible URL to a PDF, DOCX, TXT, or MD file",
        examples=["https://example.com/hr_policy.pdf"]
    )
    questions: list[str] = Field(
        ...,
        min_length=1,
        description="One or more questions to answer from the document",
        examples=[["What is the remote work policy?", "How many leave days do contractors get?"]]
    )
    top_k: Optional[int] = Field(None, ge=1, le=20, description="Chunks to retrieve per question (default: 8)")

class QuestionAnswer(BaseModel):
    question: str
    answer: str
    sources: list[str]

class QueryResponse(BaseModel):
    url: str
    filename: str
    total_chunks_indexed: int
    results: list[QuestionAnswer]

class IndexStats(BaseModel):
    total_chunks: int
    sources: list[str]
    index_exists: bool


# ── Helpers ──────────────────────────────────────────────────────

def _download_file(url: str, dest_dir: Path) -> Path:
    """Download a file from a URL into dest_dir, return local path."""
    parsed = urlparse(url)
    filename = Path(parsed.path).name or "document"

    # Ensure extension is supported
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTS:
        raise HTTPException(
            400,
            f"Unsupported file type '{suffix}'. Supported: {', '.join(SUPPORTED_EXTS)}"
        )

    dest = dest_dir / filename
    try:
        logger.info(f"Downloading {url}")
        urllib.request.urlretrieve(url, dest)
        logger.success(f"Downloaded → {dest} ({dest.stat().st_size // 1024} KB)")
    except Exception as e:
        raise HTTPException(400, f"Could not download file from URL: {e}")
    return dest


def _build_temp_index(file_path: Path):
    """Ingest a single file and return a fresh Retriever with its index."""
    from app.ingestion import ingest_directory, save_chunks
    from app.retriever import Retriever

    tmp_docs = file_path.parent
    chunks = ingest_directory(tmp_docs, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    if not chunks:
        raise HTTPException(422, "No text could be extracted from the document.")

    retriever = Retriever(model_name=EMBED_MODEL)
    retriever.build_index(chunks)
    return retriever, chunks


# ── Endpoints ────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "generator_loaded": state.generator is not None,
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


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    """
    Download a policy document from a URL, index it on the fly,
    then answer every question in the list.

    Example request body:
    {
      "url": "https://example.com/hr_policy.pdf",
      "questions": [
        "What is the remote work policy?",
        "How many sick days are employees entitled to?",
        "What are the IT security requirements?"
      ]
    }
    """
    top_k = req.top_k or TOP_K

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # 1. Download
        file_path = _download_file(req.url, tmp_dir)

        # 2. Ingest + index (in-memory, not saved to disk)
        retriever, chunks = _build_temp_index(file_path)

        # 3. Answer each question
        results: list[QuestionAnswer] = []
        for question in req.questions:
            if not question.strip():
                continue

            retrieved = retriever.retrieve(question, top_k=top_k)
            if not retrieved:
                results.append(QuestionAnswer(
                    question=question,
                    answer="No relevant content found in the document.",
                    sources=[],
                ))
                continue

            prompt = state.generator.build_prompt(question, retrieved)
            answer = state.generator.generate(prompt)

            results.append(QuestionAnswer(
                question=question,
                answer=answer,
                sources=list({c["source"] for c in retrieved}),
            ))
            logger.success(f"  Q: {question[:60]}…")

    return QueryResponse(
        url=req.url,
        filename=file_path.name,
        total_chunks_indexed=len(chunks),
        results=results,
    )


@app.post("/ingest", summary="Upload documents and persist them in the permanent index")
async def ingest(files: list[UploadFile] = File(...)):
    """
    Alternative to /query: upload docs to the permanent index.
    Useful when you want to keep a document available across requests
    without re-downloading it each time.
    """
    from app.ingestion import ingest_directory, save_chunks
    from app.retriever import Retriever

    if not files:
        raise HTTPException(400, "No files provided")

    saved = []
    for upload in files:
        dest = DOCS_DIR / upload.filename
        with dest.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
        saved.append(upload.filename)

    chunks = ingest_directory(DOCS_DIR, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    if not chunks:
        raise HTTPException(422, "No text could be extracted.")

    save_chunks(chunks, CHUNKS_PATH)
    new_retriever = Retriever(model_name=EMBED_MODEL)
    new_retriever.build_index(chunks)
    new_retriever.save(INDEX_PATH, CHUNKS_PATH)
    state.retriever = new_retriever

    return {
        "message": "Index rebuilt",
        "uploaded": saved,
        "total_chunks": len(chunks),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=False,
    )