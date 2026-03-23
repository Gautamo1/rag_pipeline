#!/bin/bash
# setup_and_run.sh — Run FastAPI backend + serve frontend (no npm required)
# Usage: bash setup_and_run.sh

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
FRONTEND_DIR="${FRONTEND_DIR:-frontend}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

# ── Detect correct uvicorn app module ─────────────────────────────────────────
if [ -f "app/main.py" ]; then
    APP_MODULE="app.main:app"
elif [ -f "main.py" ]; then
    APP_MODULE="main:app"
else
    err "Cannot find main.py or app/main.py in $(pwd)"
    exit 1
fi
log "Detected app module: $APP_MODULE"

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
log "Starting FastAPI ($APP_MODULE) on ${BACKEND_HOST}:${BACKEND_PORT} ..."

if ! command -v uvicorn &>/dev/null; then
    err "uvicorn not found. Run: pip install uvicorn"
    exit 1
fi

uvicorn "$APP_MODULE" \
    --host "$BACKEND_HOST" \
    --port "$BACKEND_PORT" \
    --reload \
    2>&1 | sed "s/^/[backend] /" &

PIDS+=($!)
log "FastAPI PID: ${PIDS[-1]}"
sleep 2

# ── 2. Serve frontend ─────────────────────────────────────────────────────────
if [ ! -d "$FRONTEND_DIR" ]; then
    err "Frontend directory '$FRONTEND_DIR' not found. Backend-only mode."
    echo ""
    log "Backend running. Press Ctrl+C to stop."
    echo "  Backend  → http://localhost:${BACKEND_PORT}"
    echo "  API docs → http://localhost:${BACKEND_PORT}/docs"
    wait
    exit 0
fi

if command -v npm &>/dev/null; then
    # ── npm available: Vite dev server ──────────────────────────────────────
    log "npm found — starting Vite dev server on port $FRONTEND_PORT ..."
    cd "$FRONTEND_DIR"
    if [ ! -d "node_modules" ]; then
        warn "Running npm install first..."
        npm install
    fi
    npm run dev -- --port "$FRONTEND_PORT" 2>&1 | sed "s/^/[frontend] /" &
    PIDS+=($!)
    cd - > /dev/null

else
    # ── no npm: try to install Node, build once, then mount dist into FastAPI ─
    warn "npm not found."

    if [ ! -d "$FRONTEND_DIR/dist" ]; then
        warn "Attempting to install Node.js to build the frontend..."
        if command -v apt-get &>/dev/null; then
            apt-get update -qq && apt-get install -y -qq nodejs npm 2>&1 | sed "s/^/[node-install] /"
        elif command -v apk &>/dev/null; then
            apk add --quiet nodejs npm
        else
            err "Cannot install Node automatically."
            err "Fix options:"
            err "  1) Install Node: curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y nodejs"
            err "  2) Build the frontend elsewhere, copy dist/ here, re-run."
            err "  3) Visit the API docs at http://localhost:${BACKEND_PORT}/docs and use the backend directly."
            echo ""
            log "Backend-only mode. Press Ctrl+C to stop."
            echo "  Backend  → http://localhost:${BACKEND_PORT}"
            echo "  API docs → http://localhost:${BACKEND_PORT}/docs"
            wait
            exit 0
        fi

        log "Building frontend..."
        cd "$FRONTEND_DIR"
        npm install
        npm run build
        cd - > /dev/null
    fi

    # Mount the built dist/ directly into FastAPI so everything runs on one port
    DIST_ABS="$(pwd)/$FRONTEND_DIR/dist"
    log "Mounting dist/ into FastAPI at / ..."

    # Patch main.py to serve static files if not already done
    if ! grep -q "StaticFiles" "${APP_MODULE%%:*}".py 2>/dev/null; then
        MAIN_FILE="${APP_MODULE%%:*}"
        MAIN_FILE="${MAIN_FILE//.//}.py"
        warn "Adding StaticFiles mount to $MAIN_FILE ..."
        cat >> "$MAIN_FILE" << PATCH

# ── Static frontend (auto-added by setup_and_run.sh) ─────────────────────────
from fastapi.staticfiles import StaticFiles as _SF
app.mount("/", _SF(directory="${DIST_ABS}", html=True), name="static")
PATCH
    fi

    warn "Frontend served by FastAPI at http://localhost:${BACKEND_PORT}"
    warn "(Restart uvicorn to pick up the StaticFiles mount)"
fi

# ── 3. Summary ────────────────────────────────────────────────────────────────
echo ""
log "Services running. Press Ctrl+C to stop."
echo ""
echo "  Backend  → http://localhost:${BACKEND_PORT}"
echo "  API docs → http://localhost:${BACKEND_PORT}/docs"
if command -v npm &>/dev/null; then
    echo "  Frontend → http://localhost:${FRONTEND_PORT}  (Vite — /api proxied automatically)"
else
    echo "  Frontend → http://localhost:${BACKEND_PORT}   (served by FastAPI from dist/)"
fi
echo ""

wait