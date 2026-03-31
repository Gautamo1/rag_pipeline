@echo off
REM setup_and_run.bat — Run FastAPI backend + serve frontend (Windows)
REM Usage: setup_and_run.bat

setlocal enabledelayedexpansion

REM ── Config ─────────────────────────────────────────────────────────────────
set "BACKEND_HOST=0.0.0.0"
set "BACKEND_PORT=8000"
set "FRONTEND_DIR=frontend"
set "FRONTEND_PORT=5173"

if defined API_HOST set "BACKEND_HOST=%API_HOST%"
if defined API_PORT set "BACKEND_PORT=%API_PORT%"
if defined FRONTEND_DIR set "FRONTEND_DIR=%FRONTEND_DIR%"
if defined FRONTEND_PORT set "FRONTEND_PORT=%FRONTEND_PORT%"

REM ── Detect correct app module ──────────────────────────────────────────────
set "APP_MODULE="
if exist "app\main.py" (
    set "APP_MODULE=app.main:app"
) else if exist "main.py" (
    set "APP_MODULE=main:app"
) else (
    echo [ERROR] Cannot find app/main.py or main.py in %cd%
    pause
    exit /b 1
)

echo [START] Detected app module: %APP_MODULE%

REM ── Check for virtual environment ──────────────────────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo [WARN] Virtual environment not found. Creating...
    python -m venv venv
)

REM ── Activate virtual environment ───────────────────────────────────────────
call venv\Scripts\activate.bat

REM ── Check for uvicorn ──────────────────────────────────────────────────────
where uvicorn >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uvicorn not found. Run: pip install uvicorn
    pause
    exit /b 1
)

REM ── 1. Start FastAPI ───────────────────────────────────────────────────────
echo [START] Starting FastAPI (%APP_MODULE%) on %BACKEND_HOST%:%BACKEND_PORT% ...

start "RAG-Backend" cmd /k ^
    uvicorn %APP_MODULE% ^
    --host %BACKEND_HOST% ^
    --port %BACKEND_PORT% ^
    --reload

timeout /t 3 /nobreak

REM ── 2. Serve frontend ──────────────────────────────────────────────────────
if not exist "%FRONTEND_DIR%" (
    echo [ERROR] Frontend directory '%FRONTEND_DIR%' not found. Backend-only mode.
    echo.
    echo [START] Backend running. Close this window to stop.
    echo   Backend  ^> http://localhost:%BACKEND_PORT%
    echo   API docs ^> http://localhost:%BACKEND_PORT%/docs
    pause
    exit /b 0
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [WARN] npm not found.
    
    if not exist "%FRONTEND_DIR%\dist" (
        echo [WARN] Attempting to install Node.js...
        echo [ERROR] Please install Node.js from https://nodejs.org/
        echo [ERROR] Then run this script again.
        pause
        exit /b 1
    ) else (
        echo [START] Building frontend...
        cd "%FRONTEND_DIR%"
        npm install
        npm run build
        cd ..
        
        REM Mount dist into FastAPI
        set "DIST_ABS=%cd%\%FRONTEND_DIR%\dist"
        echo [START] Frontend will be served by FastAPI from dist/ at http://localhost:%BACKEND_PORT%
    )
) else (
    REM npm available: start Vite dev server
    echo [START] npm found - starting Vite dev server on port %FRONTEND_PORT% ...
    
    cd "%FRONTEND_DIR%"
    if not exist "node_modules" (
        echo [WARN] Running npm install first...
        call npm install
    )
    
    start "RAG-Frontend" cmd /k npm run dev -- --port %FRONTEND_PORT%
    cd ..
)

REM ── 3. Summary ─────────────────────────────────────────────────────────────
echo.
echo [START] Services running. Close the windows to stop.
echo.
echo   Backend  ^> http://localhost:%BACKEND_PORT%
echo   API docs ^> http://localhost:%BACKEND_PORT%/docs

where npm >nul 2>&1
if errorlevel 0 (
    echo   Frontend ^> http://localhost:%FRONTEND_PORT%  (Vite - /api proxied automatically)
) else (
    echo   Frontend ^> http://localhost:%BACKEND_PORT%   (served by FastAPI from dist/)
)
echo.

REM Keep the main window open
pause
