#!/bin/bash
# stop.sh — kill the API and optionally wipe the index

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PORT=${API_PORT:-8000}

echo -e "${YELLOW}[•] Stopping RAG API on port $PORT...${NC}"
if lsof -ti tcp:"$PORT" &>/dev/null; then
  kill -9 $(lsof -ti tcp:"$PORT") 2>/dev/null
  echo -e "${GREEN}[✓] Stopped.${NC}"
else
  echo -e "${GREEN}[✓] Nothing running on port $PORT.${NC}"
fi

if [[ "$1" == "--clean" ]]; then
  echo -e "${YELLOW}[•] Removing index (keeping docs)...${NC}"
  rm -f data/index/faiss.index data/index/chunks.json
  echo -e "${GREEN}[✓] Index removed. Run setup_and_run.sh to rebuild.${NC}"
fi
