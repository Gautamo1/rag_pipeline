@echo off
REM setup_droplet.bat — Quick setup for already-cloned repo
REM Assumes you've already: git clone https://github.com/.../rag_pipeline.git
REM This script: venv -> install deps -> build index -> start services

setlocal enabledelayedexpansion

REM ── Config ─────────────────────────────────────────────────────────────────
set "BACKEND_HOST=0.0.0.0"
set "BACKEND_PORT=8000"
set "FRONTEND_DIR=frontend"
set "FRONTEND_PORT=5173"

echo.
echo ════════════════════════════════════════════════════════════════
echo   RAG Pipeline Setup - Simplified
echo ════════════════════════════════════════════════════════════════
echo.

REM ── Check if we're in the right directory ───────────────────────────────────
if not exist "app\main.py" (
    echo [ERROR] app/main.py not found!
    echo Are you in the rag_pipeline directory?
    echo Current: %cd%
    pause
    exit /b 1
)

echo [INFO] Directory: %cd%
echo.

REM ── 1. Create virtual environment ───────────────────────────────────────────
if exist "venv\Scripts\activate.bat" (
    echo [SKIP] Virtual environment already exists
) else (
    echo [START] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [✓] Virtual environment created
)

echo.

REM ── 2. Activate virtual environment ───────────────────────────────────────
echo [START] Activating virtual environment...
call venv\Scripts\activate.bat
echo [✓] Virtual environment activated

echo.

REM ── 3. Check for uvicorn ──────────────────────────────────────────────────
where uvicorn >nul 2>&1
if errorlevel 1 (
    echo [START] Installing dependencies...
    pip install -q -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo [✓] Dependencies installed
) else (
    echo [SKIP] Dependencies already installed
)

echo.

REM ── 4. Verify PyTorch ─────────────────────────────────────────────────────
echo [START] Verifying PyTorch...
python -c "import torch; print(f'✓ PyTorch: {torch.__version__}'); print(f'✓ CUDA: {torch.cuda.is_available()}')" >nul 2>&1
if errorlevel 1 (
    echo [WARN] PyTorch verification failed
) else (
    echo [✓] PyTorch verified
)

echo.

REM ── 5. Create data directories ────────────────────────────────────────────
if not exist "data\docs" mkdir data\docs
if not exist "data\index" mkdir data\index
echo [✓] Data directories ready

echo.

REM ── 6. Build FAISS index ──────────────────────────────────────────────────
if exist "data\index\faiss.index" (
    echo [SKIP] FAISS index already exists
) else (
    echo [START] Building FAISS index...
    echo (This may take 5-10 minutes)
    echo.
    python scripts\build_index.py
    if errorlevel 1 (
        echo [WARN] Index build had issues, but continuing...
    ) else (
        echo [✓] FAISS index built
    )
)

echo.

REM ── 7. Summary ────────────────────────────────────────────────────────────
echo ════════════════════════════════════════════════════════════════
echo   Setup Complete!
echo ════════════════════════════════════════════════════════════════
echo.
echo   Next step: Start the services
echo.
echo   Option A - Vite dev server (separate backend + frontend):
echo     run_dev.bat
echo.
echo   Option B - Production (both on one port):
echo     cd frontend
echo     npm run build
echo     cd ..
echo     uvicorn app.main:app --host 0.0.0.0 --port 8000
echo.
echo   Services will be at:
echo     Backend:  http://localhost:8000
echo     API Docs: http://localhost:8000/docs
echo     Frontend: http://localhost:5173 (if using Option A)
echo.
echo ════════════════════════════════════════════════════════════════
echo.

pause
