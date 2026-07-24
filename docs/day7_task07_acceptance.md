# Day 7 Task 07 Acceptance

## Start the local demo

1. Copy `.env.example` to `.env` and fill the backend provider keys.
2. From the repository root, run `docker compose up --build -d --wait`.
3. Open `http://127.0.0.1:8501` and inspect backend readiness at
   `http://127.0.0.1:8000/api/health`.
4. Stop the stack with `docker compose down`.

The backend is deliberately limited to one Uvicorn worker because the in-memory
BM25 index is rebuilt from the persisted Chroma collection during startup. Chroma
data is bind-mounted at `./data`, while the built-in documents are mounted
read-only from `./knowledge`.

The frontend container receives only `BACKEND_URL`; model-provider and Langfuse
credentials are loaded from the root `.env` into the backend container only.
Langfuse remains an optional cloud integration and is not self-hosted by this
Compose stack.

Docker checks process liveness through `/api/live`, which remains HTTP 200 even
when provider credentials are absent. `/api/health` is the stricter readiness and
capability report; it can return HTTP 503 with a structured `unavailable` payload
until the core LLM and embedding settings are configured.

## Automated smoke

Run:

```powershell
./scripts/docker-smoke.ps1
```

The script validates Compose, builds both images, waits for both health endpoints,
restarts the backend to exercise shutdown/startup, verifies readiness again, and
always tears the stack down. Use `-KeepRunning` to leave successful containers up.

The health checks are local and do not invoke the embedding, chat, reranker, or
Langfuse APIs. Uploading/loading documents and sending chat messages can invoke
configured external providers and should be tested intentionally with valid keys.
