#!/bin/bash
# start.sh — Run FastAPI backend + Vite frontend together
# Usage: chmod +x start.sh && ./start.sh

set -e

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[start]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC}  $1"; }
err()  { echo -e "${RED}[error]${NC} $1"; }

# ── Config ────────────────────────────────────────────────────────────────────
BACKEND_HOST="${API_HOST:-0.0.0.0}"
BACKEND_PORT="${API_PORT:-8000}"
FRONTEND_DIR="${FRONTEND_DIR:-frontend}"   # path to the Vite project folder

# ── Cleanup on exit ───────────────────────────────────────────────────────────
PIDS=()
cleanup() {
    echo ""
    log "Shutting down..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null
    log "Done."
}
trap cleanup EXIT INT TERM

# ── 1. Start FastAPI ──────────────────────────────────────────────────────────
log "Starting FastAPI on ${BACKEND_HOST}:${BACKEND_PORT} ..."

if ! command -v uvicorn &>/dev/null; then
    err "uvicorn not found. Run:  pip install uvicorn"
    exit 1
fi

uvicorn main:app \
    --host "$BACKEND_HOST" \
    --port "$BACKEND_PORT" \
    --reload \
    2>&1 | sed 's/^/[backend] /' &

PIDS+=($!)
log "FastAPI PID: ${PIDS[-1]}"

# Give FastAPI a moment to start before the frontend tries /health
sleep 2

# ── 2. Start Vite dev server ──────────────────────────────────────────────────
if [ ! -d "$FRONTEND_DIR" ]; then
    err "Frontend directory '$FRONTEND_DIR' not found."
    err "Set FRONTEND_DIR=path/to/your/vite/project or adjust the variable at the top of this script."
    exit 1
fi

log "Starting Vite dev server in '$FRONTEND_DIR' ..."

cd "$FRONTEND_DIR"

if [ ! -d "node_modules" ]; then
    warn "node_modules not found — running npm install first..."
    npm install
fi

npm run dev 2>&1 | sed 's/^/[frontend] /' &

PIDS+=($!)
log "Vite PID: ${PIDS[-1]}"

# ── 3. Wait ───────────────────────────────────────────────────────────────────
echo ""
log "Both servers running. Press Ctrl+C to stop."
echo ""
echo "  Backend  → http://localhost:${BACKEND_PORT}"
echo "  Frontend → http://localhost:5173"
echo "  API docs → http://localhost:${BACKEND_PORT}/docs"
echo ""

wait