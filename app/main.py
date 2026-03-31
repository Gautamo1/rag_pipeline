"""
main.py — FastAPI RAG service
"""
from __future__ import annotations

import os
import re
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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "Gautamo1/mistral-7b-rag-reader")
EMBED_MODEL      = os.getenv("EMBED_MODEL",     "BAAI/bge-base-en-v1.5")
DEVICE_MAP       = os.getenv("DEVICE_MAP",      "auto")
TORCH_DTYPE      = os.getenv("TORCH_DTYPE",     "bfloat16")
ATTN_IMPL        = os.getenv("ATTN_IMPL",       "eager")  # eager works everywhere; flash_attention_2 for ROCm
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

    state.retriever = Retriever(model_name=EMBED_MODEL)
    state.generator = Generator(
        model_name=GENERATOR_MODEL,
        torch_dtype=TORCH_DTYPE,
        device_map=DEVICE_MAP,
        max_new_tokens=MAX_NEW_TOKENS,
        temperature=TEMPERATURE,
        do_sample=DO_SAMPLE,
        compile_model=COMPILE_MODEL,
        attn_impl=ATTN_IMPL,
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


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Schemas ──────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    url: str = Field(..., description="URL to a PDF, DOCX, TXT, or MD file. Google Drive share links supported.")
    questions: list[str] = Field(..., min_length=1, description="One or more questions to answer from the document")
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

def _gdrive_direct_url(url: str) -> str:
    m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
    if not m:
        m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&confirm=t&id={m.group(1)}"
    return url


def _download_file(url: str, dest_dir: Path) -> Path:
    """
    Always download first, then detect type from magic bytes.
    Never rejects based on URL — works for extensionless URLs
    like SBI, insurance portals, Drive links, etc.
    """
    if "drive.google.com" in url:
        url = _gdrive_direct_url(url)
        logger.info(f"Resolved Google Drive URL → {url}")

    # ── Step 1: download to a raw temp file ──────────────────────
    raw = dest_dir / "download.tmp"
    ct_header, cd_header = "", ""
    try:
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/pdf,*/*",
        })
        resp = session.get(url, timeout=30, allow_redirects=True, stream=True)
        resp.raise_for_status()
        ct_header = resp.headers.get("Content-Type", "").lower()
        cd_header = resp.headers.get("Content-Disposition", "")
        with open(raw, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not download file: {e}")

    size_kb = raw.stat().st_size // 1024
    snippet  = raw.read_bytes()[:16]

    # ── Step 2: reject HTML error pages ──────────────────────────
    if b"<html" in snippet.lower() or b"<!doct" in snippet.lower():
        raise HTTPException(
            400,
            "Server returned an HTML page instead of a file. "
            "If using Google Drive, share as 'Anyone with the link'."
        )

    # ── Step 3: determine extension ──────────────────────────────
    # Priority: magic bytes > Content-Type > Content-Disposition > URL path

    magic_map = [
        (b"%PDF",                 ".pdf"),
        (b"PK\x03\x04",          ".docx"),
        (b"\xd0\xcf\x11\xe0",    ".doc"),
    ]
    ext = ""
    for magic, candidate in magic_map:
        if snippet.startswith(magic):
            ext = candidate
            break

    if not ext:
        ct_map = {
            "application/pdf":   ".pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/msword": ".doc",
            "text/plain":        ".txt",
            "text/markdown":     ".md",
        }
        for mime, candidate in ct_map.items():
            if mime in ct_header:
                ext = candidate
                break

    if not ext and cd_header:
        m = re.search(r'filename[^;=\n]*=[\'"]?([^\'";\n]+)', cd_header, re.IGNORECASE)
        if m:
            ext = Path(m.group(1).strip()).suffix.lower()

    if not ext:
        ext = Path(urlparse(url).path).suffix.lower()

    if not ext:
        ext = ".pdf"
        logger.warning("Could not detect file type — defaulting to .pdf")

    # ── Step 4: rename to final path ─────────────────────────────
    dest = raw.with_name("document" + ext)
    raw.rename(dest)
    logger.success(f"Downloaded → {dest.name} ({size_kb} KB)")
    return dest


def _build_temp_retriever(file_path: Path):
    from app.ingestion import ingest_directory
    from app.retriever import Retriever

    chunks = ingest_directory(file_path.parent, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    if not chunks:
        raise HTTPException(422, "No text could be extracted from the document.")

    retriever = Retriever(model_name=EMBED_MODEL)
    retriever.build_index(chunks)
    return retriever, chunks



def _direct_extract(text: str, question: str) -> str | None:
    """
    For key:value style questions, try direct regex extraction first
    before hitting the LLM. Handles insurance/policy documents reliably.
    """
    import re
    q = question.lower().strip().rstrip('?.').strip()

    # Map common question patterns to regex patterns on the document text
    patterns = {
        'certificate no':       r'(?:Policy\s*/\s*Certificate\s*No|Certificate\s*No)[^\w]*([A-Z0-9]+)',
        'policy no':            r'(?:Policy\s*/\s*Certificate\s*No|Policy\s*No)[^\w]*([A-Z0-9]+)',
        'policy number':        r'(?:Policy\s*/\s*Certificate\s*No|Policy\s*Number)[^\w]*([A-Z0-9]+)',
        'intermediary name':    r'Intermediary\s*Name[^\w]*([\w\s]+(?:Pvt\.?\s*Ltd\.?|Ltd\.?|Inc\.?|LLP)?)',
        'intermediary code':    r'Intermediary\s*Code[^\w]*([A-Z0-9]+)',
        'policy holder':        r'Policy\s*Holder\s*Name[^\w]*([\w\s.]+)',
        'insured name':         r'(?:Insured\s*Name|Name)[^\w]*(Mrs?\.?\s*[\w\s]+)',
        'policy issue date':    r'Policy\s*Issue\s*Date[^\w]*(\d{2}/\d{2}/\d{4})',
        'policy start date':    r'Policy\s*Start\s*Date[^\w]*(\d{2}/\d{2}/\d{4})',
        'policy end date':      r'Policy\s*End\s*Date[^\w]*(\d{2}/\d{2}/\d{4})',
        'premium':              r'(?:FINAL\s*PREMIUM|Policy\s*premium\s*including\s*Tax)[^\w]*(\d[\d,.]+)',
        'registration number':  r'Registration\s*Number[^\w]*([A-Z]{2}\s*\d+\s*[A-Z]+\s*\d+)',
        'vehicle make':         r'Vehicle\s*Make[^\w]*([\w\s]+)',
        'engine number':        r'Engine\s*(?:Number|No)[^\w]*([A-Z0-9]+)',
        'chassis number':       r'Chassis\s*(?:Number|No)[^\w]*([A-Z0-9]+)',
        'contact':              r'Contact\s*No[^\w]*(\d{10})',
        'email':                r'Email\s*(?:Id|Address)?[^\w]*([\w.]+@[\w.]+)',
        'address':              r'Address[^\w]*([\w\s,.-]+(?:Punjab|Delhi|Mumbai|Bangalore|Chennai|Hyderabad|Kolkata)[\w\s,.-]*\d{6})',
        'gst':                  r'GST[^\w]*(\d[\d,.]+)',
        'period of insurance tp': r'Period of Insurance TP[^\w]*From:?\s*([\d/: ]+To:[\d/: ]+)',
        'period of insurance':    r'Period of Insurance TP[^\w]*From:?\s*([\d/: ]+To:[\d/: ]+)',
        'period':                 r'Period of Insurance TP[^\w]*From:?\s*([\d/: ]+To:[\d/: ]+)',
        'name':                   r'(?:Insured Name|Policy Holder Name|Name)[^\w]*(Mrs?\.?\s*[\w\s]+)',
        'customer id':            r'Customer ID[^\w]*([\w]+)',
        'branch':                 r'Policy Servicing Branch[^\w]*([\w\s]+)',
        'receipt number':       r'Receipt\s*Number[^\w]*([A-Z0-9]+)',
    }

    for key, pattern in patterns.items():
        if key in q:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()

    return None


# ── Endpoints ────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "generator_loaded": state.generator is not None}


@app.get("/index/stats", response_model=IndexStats)
def index_stats():
    if state.retriever is None or state.retriever.index is None:
        return IndexStats(total_chunks=0, sources=[], index_exists=False)
    sources = sorted({c["source"] for c in state.retriever.chunks})
    return IndexStats(total_chunks=len(state.retriever.chunks), sources=sources, index_exists=True)


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    top_k = req.top_k or TOP_K

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        file_path = _download_file(req.url, tmp_dir)
        retriever, chunks = _build_temp_retriever(file_path)

        results: list[QuestionAnswer] = []
        for question in req.questions:
            if not question.strip():
                continue
            # Try direct extraction first for key:value questions
            full_text = " ".join(c["text"] for c in chunks)
            direct = _direct_extract(full_text, question)
            if direct:
                results.append(QuestionAnswer(
                    question=question,
                    answer=direct,
                    sources=[chunks[0]["source"] if chunks else "document"],
                ))
                logger.success(f"  Q (direct): {question[:70]}")
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
            # Truncate runaway answers and strip repetition
            answer = answer[:500].strip()
            # Detect and cut repetitive loops (same phrase repeated 3+ times)
            import re as _re
            rep = _re.search(r'(.{20,}?)\1{2,}', answer)
            if rep:
                answer = answer[:rep.start()].strip()
            results.append(QuestionAnswer(
                question=question,
                answer=answer or "Could not extract a clear answer from the document.",
                sources=list({c["source"] for c in retrieved}),
            ))
            logger.success(f"  Q: {question[:70]}")

    return QueryResponse(
        url=req.url,
        filename=file_path.name,
        total_chunks_indexed=len(chunks),
        results=results,
    )


@app.post("/ingest")
async def ingest(files: list[UploadFile] = File(...)):
    from app.ingestion import ingest_directory, save_chunks
    from app.retriever import Retriever

    if not files:
        raise HTTPException(400, "No files provided")

    for upload in files:
        dest = DOCS_DIR / upload.filename
        with dest.open("wb") as f:
            shutil.copyfileobj(upload.file, f)

    chunks = ingest_directory(DOCS_DIR, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    if not chunks:
        raise HTTPException(422, "No text could be extracted.")

    save_chunks(chunks, CHUNKS_PATH)
    new_retriever = Retriever(model_name=EMBED_MODEL)
    new_retriever.build_index(chunks)
    new_retriever.save(INDEX_PATH, CHUNKS_PATH)
    state.retriever = new_retriever
    return {"message": "Index rebuilt", "total_chunks": len(chunks)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=os.getenv("API_HOST", "0.0.0.0"), port=int(os.getenv("API_PORT", "8000")))


@app.post("/query-file", response_model=QueryResponse)
async def query_file(
    file: UploadFile = File(...),
    questions: str = "",
):
    """
    Upload a file directly + questions as a JSON array string.
    Use this when the URL requires login or JS (SBI, insurance portals, etc.)

    curl -X POST http://localhost:8000/query-file \
      -F "file=@certificate.pdf" \
      -F 'questions=["What is Certificate No.", "Whose policy is this"]'
    """
    import json

    try:
        question_list = json.loads(questions)
        if not isinstance(question_list, list) or not question_list:
            raise ValueError
    except Exception:
        raise HTTPException(400, 'questions must be a JSON array e.g. ["What is X?", "What is Y?"]')

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        suffix = Path(file.filename).suffix.lower() or ".pdf"
        dest = tmp_dir / ("document" + suffix)
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)

        snippet = dest.read_bytes()[:8]
        if b"<html" in snippet.lower():
            raise HTTPException(400, "Uploaded file appears to be HTML, not a document.")

        retriever, chunks = _build_temp_retriever(dest)

        results: list[QuestionAnswer] = []
        for question in question_list:
            if not question.strip():
                continue
            full_text = " ".join(c["text"] for c in chunks)
            direct = _direct_extract(full_text, question)
            if direct:
                results.append(QuestionAnswer(
                    question=question,
                    answer=direct,
                    sources=[chunks[0]["source"] if chunks else "document"],
                ))
                logger.success(f"  Q (direct): {question[:70]}")
                continue

            retrieved = retriever.retrieve(question, top_k=TOP_K)
            if not retrieved:
                results.append(QuestionAnswer(
                    question=question,
                    answer="No relevant content found in the document.",
                    sources=[],
                ))
                continue
            prompt = state.generator.build_prompt(question, retrieved)
            answer = state.generator.generate(prompt)
            # Truncate runaway answers and strip repetition
            answer = answer[:500].strip()
            # Detect and cut repetitive loops (same phrase repeated 3+ times)
            import re as _re
            rep = _re.search(r'(.{20,}?)\1{2,}', answer)
            if rep:
                answer = answer[:rep.start()].strip()
            results.append(QuestionAnswer(
                question=question,
                answer=answer or "Could not extract a clear answer from the document.",
                sources=list({c["source"] for c in retrieved}),
            ))
            logger.success(f"  Q: {question[:70]}")

    return QueryResponse(
        url=f"upload://{file.filename}",
        filename=file.filename,
        total_chunks_indexed=len(chunks),
        results=results,
    )



app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")