@echo off
REM run_dev.bat — Start backend + frontend (Vite dev server)

setlocal enabledelayedexpansion

set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"

echo.
echo ════════════════════════════════════════════════════════════════
echo   Starting FastAPI Backend + Vite Frontend
echo ════════════════════════════════════════════════════════════════
echo.

REM ── Activate virtual environment ───────────────────────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Run: setup_droplet.bat
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

REM ── Start backend ─────────────────────────────────────────────────────────
echo [START] Starting FastAPI backend on port %BACKEND_PORT%...
echo.

start "RAG-Backend" cmd /k ^
    uvicorn app.main:app ^
    --host 0.0.0.0 ^
    --port %BACKEND_PORT% ^
    --reload

timeout /t 3 /nobreak

REM ── Start frontend ────────────────────────────────────────────────────────
if exist "frontend" (
    echo [START] Starting Vite frontend on port %FRONTEND_PORT%...
    echo.
    
    cd frontend
    
    if not exist "node_modules" (
        echo [INFO] Installing npm dependencies...
        call npm install
    )
    
    start "RAG-Frontend" cmd /k npm run dev -- --port %FRONTEND_PORT%
    
    cd ..
) else (
    echo [WARN] frontend directory not found
)

echo.
echo ════════════════════════════════════════════════════════════════
echo   Services Running
echo ════════════════════════════════════════════════════════════════
echo.
echo   Backend   ^> http://localhost:%BACKEND_PORT%
echo   API Docs  ^> http://localhost:%BACKEND_PORT%/docs
echo   Frontend  ^> http://localhost:%FRONTEND_PORT%
echo.
echo   Close the windows to stop services
echo.
echo ════════════════════════════════════════════════════════════════
echo.

pause
