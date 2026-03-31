# Windows Startup Guide

You now have **two options** to run everything with a single command:

## Option 1: Batch File (Simplest)

Just double-click:
```
setup_and_run.bat
```

This will:
✅ Create virtual environment (if needed)
✅ Start FastAPI backend on port 8000
✅ Start Vite frontend on port 5173
✅ Show you the URLs

## Option 2: PowerShell (More Powerful)

Open PowerShell in this folder and run:
```powershell
.\setup_and_run.ps1
```

Or double-click from File Explorer if you allow script execution:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## What You Need First

### 1. **Python 3.9+**
Check if installed:
```bash
python --version
```

### 2. **Node.js** (for frontend dev)
Get the latest from: https://nodejs.org/

Or install via Chocolatey (Windows):
```powershell
choco install nodejs
```

### 3. **Install Dependencies**
```bash
pip install -r requirements.txt
```

### 4. **Build the Search Index** (one-time)
```bash
python scripts/build_index.py
```

This downloads the embedding model (~430 MB) and builds `data/index/`.

---

## Then Run

**Both backend and frontend start automatically:**

```
setup_and_run.bat
```

---

## Access Points

| Service | URL |
|---------|-----|
| **Backend API** | http://localhost:8000 |
| **API Docs** | http://localhost:8000/docs |
| **Frontend** | http://localhost:5173 |

---

## Stopping

- **Batch**: Close both console windows
- **PowerShell**: Press `Ctrl+C` in the PowerShell window

---

## If npm install fails

You may need Visual Studio Build Tools:
```powershell
winget install Microsoft.VisualStudio.Community
```

Install the "Desktop development with C++" workload.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "uvicorn not found" | `pip install uvicorn` |
| "npm not found" | Install Node.js from nodejs.org |
| Port 8000 already in use | `$port = 8001; .\setup_and_run.ps1 -BackendPort 8001` |
| Python venv errors | Delete `venv/` folder and re-run |

Enjoy! 🚀
