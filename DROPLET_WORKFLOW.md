# Complete Droplet Workflow

## Overview

**Workflow:**
1. SSH into droplet
2. Open Jupyter Lab (optional)
3. Clone repo & run setup
4. Start services

---

## Option 1: Automated Setup (Recommended)

### One-Command Full Setup

```bash
# SSH into your droplet
ssh root@your_droplet_ip

# Run the auto-setup script (clones repo, installs everything, builds index)
bash <(curl -s https://raw.githubusercontent.com/your-username/rag_pipeline/main/auto_setup_droplet.sh)

# Or download and run locally
wget https://raw.githubusercontent.com/your-username/rag_pipeline/main/auto_setup_droplet.sh
bash auto_setup_droplet.sh https://github.com/your-username/rag_pipeline.git
```

This script:
- ✅ Installs all system dependencies
- ✅ Clones your repository
- ✅ Creates Python virtual environment
- ✅ Installs all Python packages
- ✅ Builds FAISS index
- ✅ Starts both backend & frontend (optional)

**Total time:** ~10-15 minutes

---

## Option 2: Manual Step-by-Step with Jupyter Lab

### 1. SSH & Install Jupyter

```bash
ssh root@your_droplet_ip

# Install Jupyter
apt update && apt install -y python3-pip
pip install jupyter jupyterlab

# Start Jupyter Lab
jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root
```

Access it at: `http://your_droplet_ip:8888`

### 2. Clone Repo in Jupyter Terminal

Click **Terminal** in Jupyter, then:

```bash
git clone https://github.com/your-username/rag_pipeline.git
cd rag_pipeline
```

### 3. Follow the Jupyter Notebook

Upload & open `DROPLET_SETUP.ipynb` in Jupyter Lab, run each cell in order:

1. **System dependencies** → Run in terminal, not Jupyter
2. **Clone repo** → Cell 2
3. **Create venv** → Cell 3
4. **Install dependencies** → Cell 4
5. **Verify PyTorch** → Cell 5
6. **Add documents** → Cell 6
7. **Build index** → Cell 7 (⚠️ takes 5-10 min)
8. **Start services** → Cell 8

### 4. Start Services in Jupyter Terminal

In Jupyter terminal:

```bash
# Activate venv
source venv/bin/activate

# Run both backend + frontend
bash setup_and_run.sh
```

Or run in background:
```bash
nohup bash setup_and_run.sh > server.log 2>&1 &
tail -f server.log
```

---

## Access Your Services

Once running:

| Service | URL |
|---------|-----|
| **Backend API** | `http://your_droplet_ip:8000` |
| **API Docs** | `http://your_droplet_ip:8000/docs` |
| **Frontend** | `http://your_droplet_ip:5173` |
| **Jupyter Lab** | `http://your_droplet_ip:8888` |

---

## Quick Commands Reference

```bash
# Activate venv
source venv/bin/activate

# Start services
bash setup_and_run.sh

# Start in background
nohup bash setup_and_run.sh > server.log 2>&1 &

# View logs
tail -f server.log

# Stop services (if running in background)
pkill -f uvicorn
pkill -f "npm run dev"

# Rebuild index
python scripts/build_index.py

# Add documents
cp /path/to/docs/* data/docs/
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Port 8000 already in use | `lsof -i :8000` then `kill -9 <PID>` |
| Port 5173 already in use | `export FRONTEND_PORT=5174` |
| FAISS build fails | Ensure 4+ GB RAM available: `free -h` |
| GPU not detected | Run `rocm-smi` to check ROCm |
| npm not found | `apt install -y nodejs npm` |
| Permission denied on script | `chmod +x auto_setup_droplet.sh` |

---

## Systemd Service (Production)

To run RAG pipeline as a service that auto-starts:

```bash
# Copy service file
sudo cp rag-api.service /etc/systemd/system/

# Edit to match your paths
sudo nano /etc/systemd/system/rag-api.service

# Enable & start
sudo systemctl daemon-reload
sudo systemctl start rag-api
sudo systemctl enable rag-api

# Check status
sudo systemctl status rag-api
```

---

## Environment Variables (.env)

Customize behavior by editing `.env` in the project root:

```bash
# Model
GENERATOR_MODEL=Gautamo1/mistral-7b-rag-reader
EMBED_MODEL=BAAI/bge-base-en-v1.5

# GPU/Device
DEVICE_MAP=auto
TORCH_DTYPE=bfloat16
COMPILE_MODEL=true

# API
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4  # More workers = higher throughput

# Retrieval
CHUNK_SIZE=512
TOP_K=8

# Generation
MAX_NEW_TOKENS=512
TEMPERATURE=0.1
```

---

## Network Configuration

### Allow external access

```bash
# Check firewall
sudo ufw status

# Allow ports
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8000/tcp
sudo ufw allow 5173/tcp
sudo ufw enable
```

### Use a domain with SSL (optional)

```bash
# Install Nginx + Let's Encrypt
apt install -y nginx certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## Performance Tips

1. **Increase workers** in `.env`:
   ```
   API_WORKERS=4  # or more based on CPU cores
   ```

2. **Use production app server** (not uvicorn with --reload):
   ```bash
   gunicorn -w 4 -b 0.0.0.0:8000 app.main:app
   ```

3. **Frontend build optimization**:
   ```bash
   cd frontend
   npm run build  # Builds optimized dist/
   # Then runs from FastAPI (single port)
   ```

---

## Monitoring

```bash
# Check resource usage
htop

# Check running processes
ps aux | grep python
ps aux | grep npm

# Check logs
tail -f server.log
journalctl -u rag-api -f  # systemd service logs
```

---

Enjoy your RAG pipeline! 🚀
