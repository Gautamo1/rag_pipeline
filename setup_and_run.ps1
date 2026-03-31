#Requires -Version 5.0
<#
.SYNOPSIS
    Setup and run FastAPI backend + React frontend on Windows
.DESCRIPTION
    One-command startup for the RAG pipeline
.EXAMPLE
    .\setup_and_run.ps1
#>

param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [string]$BackendHost = "0.0.0.0"
)

# Enable error handling
$ErrorActionPreference = "Continue"

function Write-Log {
    param([string]$Message, [ValidateSet("Info", "Warn", "Error")]$Level = "Info")
    $timestamp = Get-Date -Format "HH:mm:ss"
    switch ($Level) {
        "Info"  { Write-Host "[$timestamp] [START] $Message" -ForegroundColor Green }
        "Warn"  { Write-Host "[$timestamp] [WARN]  $Message" -ForegroundColor Yellow }
        "Error" { Write-Host "[$timestamp] [ERROR] $Message" -ForegroundColor Red }
    }
}

# ── Config ──────────────────────────────────────────────────────────────────
$FrontendDir = "frontend"
$AppModule = ""

# ── Detect app module ───────────────────────────────────────────────────────
if (Test-Path "app/main.py") {
    $AppModule = "app.main:app"
} elseif (Test-Path "main.py") {
    $AppModule = "main:app"
} else {
    Write-Log "Cannot find app/main.py or main.py in $(Get-Location)" Error
    exit 1
}

Write-Log "Detected app module: $AppModule"

# ── Check for Python virtual environment ────────────────────────────────────
if (-not (Test-Path "venv/Scripts/activate.ps1")) {
    Write-Log "Virtual environment not found. Creating..."
    python -m venv venv
}

# ── Activate virtual environment ────────────────────────────────────────────
& ".\venv\Scripts\Activate.ps1"

# ── Check for uvicorn ──────────────────────────────────────────────────────
$uvicorn = Get-Command uvicorn -ErrorAction SilentlyContinue
if (-not $uvicorn) {
    Write-Log "uvicorn not found. Run: pip install uvicorn" Error
    exit 1
}

# ── Array to store process objects for cleanup ────────────────────────────
$processes = @()

# ── Cleanup on exit ────────────────────────────────────────────────────────
function Cleanup-Processes {
    Write-Log "Shutting down services..."
    foreach ($proc in $processes) {
        try {
            Stop-Process -InputObject $proc -Force -ErrorAction SilentlyContinue
        } catch {
            # Process already stopped
        }
    }
    Write-Log "Done."
}

trap {
    Cleanup-Processes
}

# ── 1. Start FastAPI backend ───────────────────────────────────────────────
Write-Log "Starting FastAPI ($AppModule) on ${BackendHost}:${BackendPort}..."

$backendProc = Start-Process -FilePath "uvicorn" `
    -ArgumentList "$AppModule", "--host", "$BackendHost", "--port", "$BackendPort", "--reload" `
    -WindowStyle Normal `
    -PassThru

$processes += $backendProc
Write-Log "Backend PID: $($backendProc.Id)"

Start-Sleep -Seconds 3

# ── 2. Serve frontend ──────────────────────────────────────────────────────
if (-not (Test-Path $FrontendDir)) {
    Write-Log "Frontend directory '$FrontendDir' not found. Backend-only mode."
    Write-Host ""
    Write-Log "Backend running. Press Ctrl+C to stop."
    Write-Host "  Backend  → http://localhost:${BackendPort}"
    Write-Host "  API docs → http://localhost:${BackendPort}/docs"
    Write-Host ""
    
    # Keep script alive
    while ($true) {
        Start-Sleep -Seconds 1
    }
}

$npm = Get-Command npm -ErrorAction SilentlyContinue

if ($npm) {
    # ── npm available: Vite dev server ────────────────────────────────────
    Write-Log "npm found - starting Vite dev server on port $FrontendPort..."
    
    Push-Location $FrontendDir
    
    if (-not (Test-Path "node_modules")) {
        Write-Log "Running npm install first..."
        npm install
    }
    
    $frontendProc = Start-Process -FilePath "npm" `
        -ArgumentList "run", "dev", "--", "--port", "$FrontendPort" `
        -WindowStyle Normal `
        -PassThru
    
    $processes += $frontendProc
    
    Pop-Location
    
} else {
    # ── no npm: build frontend and mount into FastAPI ────────────────────
    Write-Log "npm not found." Warn
    
    if (-not (Test-Path "$FrontendDir/dist")) {
        Write-Log "Attempting to install Node.js..." Warn
        Write-Log "Please install Node.js from https://nodejs.org/" Error
        Write-Log "Then run this script again." Error
        
        # Show user options
        Write-Host ""
        Write-Host "Options:"
        Write-Host "  1) Install Node.js from https://nodejs.org/"
        Write-Host "  2) Run this script again"
        Write-Host ""
        
        exit 1
    } else {
        Write-Log "Building frontend..."
        Push-Location $FrontendDir
        npm install
        npm run build
        Pop-Location
        
        $DistAbs = Join-Path (Get-Location) "$FrontendDir\dist"
        Write-Log "Frontend will be served by FastAPI from dist/ at http://localhost:${BackendPort}"
    }
}

# ── 3. Summary ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Log "Services running. Press Ctrl+C to stop all services."
Write-Host ""
Write-Host "  Backend  → http://localhost:${BackendPort}"
Write-Host "  API docs → http://localhost:${BackendPort}/docs"

if ($npm) {
    Write-Host "  Frontend → http://localhost:${FrontendPort}  (Vite - /api proxied automatically)"
} else {
    Write-Host "  Frontend → http://localhost:${BackendPort}   (served by FastAPI from dist/)"
}

Write-Host ""

# Keep script alive and wait for processes
while ($true) {
    # Check if any process has exited
    foreach ($proc in $processes) {
        if ($proc.HasExited) {
            Write-Log "A service stopped. Shutting down..." Warn
            Cleanup-Processes
            exit 1
        }
    }
    Start-Sleep -Seconds 1
}
