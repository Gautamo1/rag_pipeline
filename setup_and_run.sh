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

set -e

GREEN='\033[0;32m'; CYAN='\033[0;36m'
YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info()    { echo -e "${CYAN}[•] $1${NC}"; }
success() { echo -e "${GREEN}[✓] $1${NC}"; }
warn()    { echo -e "${YELLOW}[!] $1${NC}"; }
error()   { echo -e "${RED}[✗] $1${NC}"; exit 1; }

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
# Prefer existing system python that already has torch (common on GPU droplets)
PYTHON_BIN=""

# Check if system python already has torch — if so, skip venv entirely
for py in python3 python; do
  if command -v "$py" &>/dev/null; then
    if "$py" -c "import torch" 2>/dev/null; then
      PYTHON_BIN=$(command -v "$py")
      success "System Python at $PYTHON_BIN already has torch — using it directly"
      break
    fi
  fi
done

# Fall back to venv if no system torch found
if [ -z "$PYTHON_BIN" ]; then
  if [ ! -d "venv" ]; then
    info "Creating Python virtual environment..."
    python3 -m venv venv
    success "venv created"
  else
    success "venv already exists"
  fi
  source venv/bin/activate
  PYTHON_BIN=$(command -v python)
fi

# ── Step 2: Install dependencies ─────────────────────────────────
if [ "$SKIP_INSTALL" = false ]; then
  info "Installing dependencies..."

  # Check if torch is already importable
  if "$PYTHON_BIN" -c "import torch" 2>/dev/null; then
    TORCH_VER=$("$PYTHON_BIN" -c "import torch; print(torch.__version__)")
    success "torch $TORCH_VER already installed — skipping torch install"
  else
    info "torch not found — attempting to install..."

    # Try to detect ROCm version
    ROCM_TAG=""
    if command -v rocminfo &>/dev/null; then
      ROCM_TAG=$(rocminfo 2>/dev/null \
        | grep -oP '(?<=ROCm Runtime Version:\s{0,10})[\d]+\.[\d]+' \
        | head -1 || true)
    fi
    if [ -z "$ROCM_TAG" ] && command -v hipcc &>/dev/null; then
      ROCM_TAG=$(hipcc --version 2>/dev/null \
        | grep -oP '(?<=HIP version: )[\d]+\.[\d]+' | head -1 || true)
    fi

    if [ -n "$ROCM_TAG" ]; then
      info "Detected ROCm ${ROCM_TAG} — trying matching PyTorch wheel..."
      WHEEL_URL="https://download.pytorch.org/whl/rocm${ROCM_TAG}"
      pip install torch --index-url "$WHEEL_URL" 2>/dev/null \
        || pip install torch --index-url https://download.pytorch.org/whl/rocm6.0 \
        || error "Could not install PyTorch. Try manually: pip install torch --index-url https://download.pytorch.org/whl/rocm6.0"
    else
      warn "No ROCm detected. Installing CPU torch as fallback..."
      pip install torch --index-url https://download.pytorch.org/whl/cpu \
        || error "torch install failed. Install it manually then re-run with --skip-install"
    fi
  fi

  info "Installing remaining requirements..."
  pip install -q -r requirements.txt
  success "Dependencies installed"
else
  success "Skipping install (--skip-install)"
fi

# ── Step 3: Check for docs ───────────────────────────────────────
mkdir -p data/docs data/index

DOC_COUNT=$(find data/docs -type f \( -iname "*.pdf" -o -iname "*.docx" -o -iname "*.txt" -o -iname "*.md" \) | wc -l)

if [ "$DOC_COUNT" -eq 0 ]; then
  warn "No documents found in data/docs/ — creating sample policy for demo..."
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
  success "Sample policy created at data/docs/sample_policy.txt"
  DOC_COUNT=1
fi

success "Found $DOC_COUNT document(s) in data/docs/"

# ── Step 4: Build index ──────────────────────────────────────────
if [ "$SKIP_INDEX" = false ]; then
  info "Building FAISS index..."
  "$PYTHON_BIN" scripts/build_index.py
  success "Index built"
else
  if [ ! -f "data/index/faiss.index" ]; then
    error "Index not found and --skip-index was set. Run without --skip-index first."
  fi
  success "Skipping index build (--skip-index)"
fi

# ── Step 5: Start API ────────────────────────────────────────────
PORT=${API_PORT:-8000}

if lsof -ti tcp:"$PORT" &>/dev/null 2>&1; then
  warn "Port $PORT in use — killing existing process..."
  kill -9 $(lsof -ti tcp:"$PORT") 2>/dev/null || true
  sleep 1
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  API starting on http://0.0.0.0:${PORT}${NC}"
echo -e "${GREEN}  Docs UI: http://0.0.0.0:${PORT}/docs${NC}"
echo -e "${GREEN}  Press Ctrl+C to stop${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

"$PYTHON_BIN" -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --workers 1 \
  --log-level info
