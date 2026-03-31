# Quick Start - 3 Steps Only

## You Handle: Git Clone

```bash
git clone https://github.com/your-username/rag_pipeline.git
cd rag_pipeline
```

---

## Step 1: Setup Everything

**Just run this batch file:**

```
setup_droplet.bat
```

**What it does:**
- ✅ Creates Python virtual environment
- ✅ Installs all dependencies (`pip install -r requirements.txt`)
- ✅ Verifies PyTorch
- ✅ Builds FAISS index (~5-10 minutes)
- ✅ Creates data directories

---

## Step 2: Start Dev Server

**Run this when setup is done:**

```
run_dev.bat
```

**What it does:**
- ✅ Starts FastAPI backend on port **8000**
- ✅ Starts Vite frontend on port **5173**
- ✅ Opens in separate windows (close to stop)

---

## Step 3: Access Your Services

| Service | URL |
|---------|-----|
| **Backend** | http://localhost:8000 |
| **API Docs** | http://localhost:8000/docs |
| **Frontend** | http://localhost:5173 |

---

## That's It! 🚀

No bash needed. Just:
1. Clone repo yourself
2. Run `setup_droplet.bat`
3. Run `run_dev.bat`

Done!

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Python not found" | Install Python 3.9+ from python.org |
| "npm not found" | Install Node.js from nodejs.org |
| Port 8000 in use | Change `BACKEND_PORT` in `run_dev.bat` |
| Port 5173 in use | Change `FRONTEND_PORT` in `run_dev.bat` |
| Setup fails | Delete `venv/` folder and re-run `setup_droplet.bat` |

---

## Optional: For Production (Single Port)

```bash
cd frontend
npm run build
cd ..

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Access everything at: http://localhost:8000
