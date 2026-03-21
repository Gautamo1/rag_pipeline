#!/bin/bash
# ─────────────────────────────────────────────────────────────────
#  setup_and_run.sh  —  one command to go from fresh droplet to
#                        running RAG API with sample policy docs
#
#  Usage:
#    chmod +x setup_and_run.sh
#    ./setup_and_run.sh                   # full setup + start API
#    ./setup_and_run.sh --skip-install    # skip pip if already done
#    ./setup_and_run.sh --skip-index      # skip re-indexing
# ─────────────────────────────────────────────────────────────────

set -e  # exit on any error

# ── Colours ──────────────────────────────────────────────────────
GREEN='\033[0;32m'; CYAN='\033[0;36m'
YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info()    { echo -e "${CYAN}[•] $1${NC}"; }
success() { echo -e "${GREEN}[✓] $1${NC}"; }
warn()    { echo -e "${YELLOW}[!] $1${NC}"; }
error()   { echo -e "${RED}[✗] $1${NC}"; exit 1; }

# ── Flags ────────────────────────────────────────────────────────
SKIP_INSTALL=false
SKIP_INDEX=false
for arg in "$@"; do
  [[ "$arg" == "--skip-install" ]] && SKIP_INSTALL=true
  [[ "$arg" == "--skip-index"   ]] && SKIP_INDEX=true
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       Policy RAG Pipeline — Demo         ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Python venv ──────────────────────────────────────────
if [ ! -d "venv" ]; then
  info "Creating Python virtual environment..."
  python3 -m venv venv
  success "venv created"
else
  success "venv already exists"
fi

source venv/bin/activate

# ── Step 2: Install dependencies ─────────────────────────────────
if [ "$SKIP_INSTALL" = false ]; then
  info "Installing dependencies (this takes ~2 min on first run)..."

  # Detect ROCm
  if command -v rocminfo &>/dev/null; then
    ROCM_VER=$(rocminfo 2>/dev/null | grep -oP 'ROCm Runtime Version:\s*\K[\d.]+' | head -1 || echo "6.0")
    ROCM_MAJOR=$(echo "$ROCM_VER" | cut -d. -f1,2)
    info "Detected ROCm $ROCM_VER — installing ROCm PyTorch..."
    pip install -q torch --index-url "https://download.pytorch.org/whl/rocm${ROCM_MAJOR}"
  else
    warn "ROCm not detected — installing CPU PyTorch (demo will be slower)"
    pip install -q torch --index-url https://download.pytorch.org/whl/cpu
  fi

  pip install -q -r requirements.txt
  success "Dependencies installed"
else
  success "Skipping install (--skip-install)"
fi

# ── Step 3: Check for docs ───────────────────────────────────────
mkdir -p data/docs data/index

DOC_COUNT=$(find data/docs -type f \( -iname "*.pdf" -o -iname "*.docx" -o -iname "*.txt" -o -iname "*.md" \) | wc -l)

if [ "$DOC_COUNT" -eq 0 ]; then
  warn "No documents found in data/docs/"
  warn "Add your policy PDFs/DOCXs there, then re-run with --skip-install"
  warn ""
  warn "Quick demo: creating a sample policy doc for you..."

  cat > data/docs/sample_policy.txt << 'POLICY'
ACME Corp — Employee Policy Manual v2.1

REMOTE WORK POLICY
Employees may work remotely up to 3 days per week with manager approval.
Contractors may work fully remote provided they attend weekly team syncs.
All remote workers must use a VPN when accessing company systems.

LEAVE POLICY
Full-time employees receive 20 days of paid leave annually.
Sick leave is uncapped but must be reported to HR within 24 hours.
Contractors are not entitled to paid leave under this policy.

IT SECURITY
All company laptops must have full-disk encryption enabled.
Passwords must be at least 14 characters and rotated every 90 days.
Use of personal devices for work purposes requires prior IT approval.

DATA HANDLING
Customer data must never be stored on personal devices.
All data transfers must use encrypted channels (TLS 1.2 or higher).
Breach incidents must be reported to the security team within 1 hour.
POLICY

  success "Sample policy document created at data/docs/sample_policy.txt"
  DOC_COUNT=1
fi

success "Found $DOC_COUNT document(s) in data/docs/"

# ── Step 4: Build index ──────────────────────────────────────────
if [ "$SKIP_INDEX" = false ]; then
  info "Building FAISS index (downloads embed model ~430 MB on first run)..."
  python scripts/build_index.py
  success "Index built"
else
  if [ ! -f "data/index/faiss.index" ]; then
    error "Index not found and --skip-index was set. Run without --skip-index first."
  fi
  success "Skipping index build (--skip-index)"
fi

# ── Step 5: Start API ────────────────────────────────────────────
PORT=${API_PORT:-8000}

# Kill anything already on that port
if lsof -ti tcp:"$PORT" &>/dev/null; then
  warn "Port $PORT in use — killing existing process..."
  kill -9 $(lsof -ti tcp:"$PORT") 2>/dev/null || true
  sleep 1
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  API starting on http://0.0.0.0:${PORT}${NC}"
echo -e "${GREEN}  Docs: http://0.0.0.0:${PORT}/docs${NC}"
echo -e "${GREEN}  Press Ctrl+C to stop${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Note: --workers 1 for demo; bump to 4+ for load testing
uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --workers 1 \
  --log-level info
