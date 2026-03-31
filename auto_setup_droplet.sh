#!/bin/bash
# auto_setup_droplet.sh — Complete RAG Pipeline setup for AMD droplet
# Usage: bash auto_setup_droplet.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# ─────────────────────────────────────────────────────────────────────────────
# 1. System dependencies
# ─────────────────────────────────────────────────────────────────────────────
log "Installing system dependencies..."

apt-get update -qq
apt-get install -y -qq \
    git \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    nodejs \
    npm \
    build-essential \
    libssl-dev \
    curl \
    wget \
    2>&1 | grep -i "done\|processing" || true

log "System dependencies installed"

# ─────────────────────────────────────────────────────────────────────────────
# 2. Clone repository
# ─────────────────────────────────────────────────────────────────────────────
REPO_URL="${1:-https://github.com/your-username/rag_pipeline.git}"
PROJECT_DIR="rag_pipeline"

if [ -d "$PROJECT_DIR" ]; then
    warn "Directory '$PROJECT_DIR' already exists. Skipping clone..."
else
    log "Cloning repository from $REPO_URL..."
    git clone "$REPO_URL" "$PROJECT_DIR"
fi

cd "$PROJECT_DIR"
log "Moved to $(pwd)"

# ─────────────────────────────────────────────────────────────────────────────
# 3. Create virtual environment
# ─────────────────────────────────────────────────────────────────────────────
if [ -d "venv" ]; then
    warn "Virtual environment already exists"
else
    log "Creating Python virtual environment..."
    python3.11 -m venv venv
fi

log "Activating virtual environment..."
source venv/bin/activate

# ─────────────────────────────────────────────────────────────────────────────
# 4. Install Python dependencies
# ─────────────────────────────────────────────────────────────────────────────
log "Upgrading pip, setuptools, wheel..."
pip install --upgrade pip setuptools wheel -q

log "Installing Python dependencies from requirements.txt..."
pip install -r requirements.txt -q

log "All Python dependencies installed"

# ─────────────────────────────────────────────────────────────────────────────
# 5. Verify PyTorch on ROCm
# ─────────────────────────────────────────────────────────────────────────────
log "Verifying PyTorch installation on ROCm..."

python << PYEOF
import torch
print(f"✓ PyTorch Version: {torch.__version__}")
print(f"✓ CUDA Available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"✓ Device: {torch.cuda.get_device_name(0)}")
    print(f"✓ HIP Version: {torch.version.hip}")
else:
    print("⚠ GPU not detected (CPU mode)")
PYEOF

# ─────────────────────────────────────────────────────────────────────────────
# 6. Create data directories
# ─────────────────────────────────────────────────────────────────────────────
log "Creating data directories..."
mkdir -p data/docs
mkdir -p data/index

log "Directory structure ready"

# ─────────────────────────────────────────────────────────────────────────────
# 7. Build FAISS index
# ─────────────────────────────────────────────────────────────────────────────
if [ -f "data/index/faiss.index" ]; then
    warn "FAISS index already exists"
else
    log "Building FAISS index... (this may take 5-10 minutes)"
    python scripts/build_index.py
    log "FAISS index built successfully"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 8. Summary and next steps
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════════════════"
echo "  ✓ Setup Complete!"
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo ""
echo "  1. (Optional) Add policy documents to data/docs/"
echo "     e.g., cp /path/to/policies/*.pdf data/docs/"
echo ""
echo "  2. Start the services:"
echo "     bash setup_and_run.sh"
echo ""
echo "  3. Or start in background:"
echo "     nohup bash setup_and_run.sh > server.log 2>&1 &"
echo ""
echo "  4. Access your services:"
echo "     Backend:  http://your_droplet_ip:8000"
echo "     API Docs: http://your_droplet_ip:8000/docs"
echo "     Frontend: http://your_droplet_ip:5173"
echo ""
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 9. Offer to start services
# ─────────────────────────────────────────────────────────────────────────────
read -p "Start services now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    log "Starting FastAPI + Frontend..."
    bash setup_and_run.sh
fi
