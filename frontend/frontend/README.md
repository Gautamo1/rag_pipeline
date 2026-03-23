# Policy RAG Frontend (React)

Minimal React UI with:

- Upload button (interactive styling)
- Chat-like interface to ask policy questions
- Works **even if backend is offline** (offline/mock mode)

## Run (frontend only)

```bash
cd rag_pipeline/frontend
npm install
npm run dev
```

Open: http://localhost:5173

## Run with backend

1. Start the API (in a separate terminal):

```bash
cd rag_pipeline
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

2. Keep frontend running (`npm run dev`).

The frontend uses a dev proxy so it can call the API at `/api/*` without CORS changes.

## Notes

- When the backend is reachable, questions are sent to `POST /query-file`.
- When it is not reachable, the app answers in **Offline mode**. For `.txt` / `.md` files it does a basic keyword search locally.
