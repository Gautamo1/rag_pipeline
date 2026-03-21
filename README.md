# Policy RAG Pipeline

FastAPI service for Retrieval-Augmented Generation over policy documents.

**Generator** — `Gautamo1/mistral-7b-rag-reader` (Mistral-7B fine-tune)  
**Retriever** — `BAAI/bge-base-en-v1.5` (109M params) + FAISS-GPU  
**Target hardware** — AMD MI300X / 192 GB HBM3 (ROCm)

---

## Project layout

```
rag_pipeline/
├── app/
│   ├── ingestion.py   # PDF/DOCX/TXT/MD → clean text chunks
│   ├── retriever.py   # bge-base + FAISS-GPU index
│   ├── generator.py   # Mistral-7B, FlashAttn2, torch.compile
│   └── main.py        # FastAPI app
├── scripts/
│   └── build_index.py # offline index builder
├── data/
│   ├── docs/          # put your policy documents here
│   └── index/         # FAISS index + chunks.json (auto-created)
├── .env               # all configuration knobs
├── requirements.txt
└── rag-api.service    # systemd unit for the droplet
```

---

## AMD MI300X / ROCm setup

### 1. Install ROCm PyTorch

Always install PyTorch for your exact ROCm version. Check yours with `rocminfo | grep 'ROCm'`.

```bash
# ROCm 6.x example (adjust rocm version as needed)
pip install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/rocm6.0
```

Verify:
```bash
python -c "import torch; print(torch.cuda.is_available(), torch.version.hip)"
```

### 2. Install Flash Attention 2 (for fast long-context prefill)

Flash Attention 2 must be compiled from source for ROCm:

```bash
pip install packaging ninja
git clone https://github.com/ROCmSoftwarePlatform/flash-attention
cd flash-attention
GPU_ARCHS=gfx942 pip install -e . --no-build-isolation
# gfx942 = MI300X; use gfx90a for MI250X
```

If you skip this step, set `attn_implementation="eager"` in `generator.py`
(the model will still work, just slightly slower on long contexts).

### 3. Install FAISS-GPU for ROCm

```bash
# Pre-built wheels via conda (easiest)
conda install -c pytorch faiss-gpu

# Or install faiss-cpu and it will still work — FAISS search is fast
# even on CPU for millions of vectors
pip install faiss-cpu
```

### 4. Install everything else

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 5. Add policy documents

```bash
cp /path/to/policies/*.pdf   data/docs/
cp /path/to/policies/*.docx  data/docs/
```

### 6. Build the index (offline, run once)

```bash
python scripts/build_index.py
```

Downloads `bge-base-en-v1.5` (~430 MB) and builds `data/index/`.

### 7. Start the API

```bash
# Single worker dev run
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Production — each worker loads its own model copy (~14 GB each)
# With 192 GB VRAM you can run up to ~10 parallel workers
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

# Or as a systemd service
sudo cp rag-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rag-api
sudo journalctl -u rag-api -f
```

---

## API endpoints

### `GET /health`
```json
{ "status": "ok", "index_ready": true, "chunks": 1432 }
```

### `GET /index/stats`
```json
{
  "total_chunks": 1432,
  "sources": ["hr_policy_2024.pdf", "it_security.docx"],
  "index_exists": true
}
```

### `POST /ingest`
Upload documents and rebuild the index on-the-fly.

```bash
curl -X POST http://localhost:8000/ingest \
  -F "files=@hr_policy.pdf" \
  -F "files=@it_security.docx"
```

### `POST /query`
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the remote work policy for contractors?"}'
```

```json
{
  "question": "What is the remote work policy for contractors?",
  "answer": "According to the HR Policy document, contractors may work remotely...",
  "sources": [
    {
      "source": "hr_policy_2024.pdf",
      "chunk_id": 42,
      "score": 0.8934,
      "text": "Contractors are permitted to work remotely provided..."
    }
  ]
}
```

Override `top_k` per request:
```bash
curl -X POST http://localhost:8000/query \
  -d '{"question": "...", "top_k": 10}'
```

---

## MI300X performance notes

| Setting | Value | Reason |
|---|---|---|
| `TORCH_DTYPE` | `bfloat16` | Native BF16 on MI300X, no accuracy loss |
| `COMPILE_MODEL` | `true` | ~20-30% throughput via `reduce-overhead` |
| `attn_implementation` | `flash_attention_2` | Faster prefill on long RAG contexts |
| `EMBED_MODEL` | `bge-base-en-v1.5` | Upgraded from bge-small, fits easily |
| `TOP_K` | `8` | More context = better answers, VRAM not a concern |
| Workers | up to 10 | Each worker = ~14 GB; 192 GB fits ~10 |

## Tuning TOP_K

Since VRAM is not a constraint, tuning `TOP_K` is purely about answer quality:
- `TOP_K=5` — good for narrow factual questions
- `TOP_K=8` — default, good balance
- `TOP_K=12` — better for broad or multi-part questions
- Beyond 15 — context window fills up, model may lose focus

## torch.compile troubleshooting

If you see a ROCm compilation error on startup, disable it:
```
COMPILE_MODEL=false
```
in `.env`. The model works correctly without it — you just lose the throughput boost.
