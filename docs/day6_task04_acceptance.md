# Day 6 Task 04 Acceptance: FastAPI Foundation and Health

## Scope

This task adds only the FastAPI application foundation, shared lifecycle,
dependency accessors, health endpoint, and common safe error envelope. Document
upload and chat/SSE business routes are intentionally deferred to later Day 6
tasks.

## Application Assembly

```text
src.main:app
    -> create_app(settings, runtime_factory, observer_factory)
        -> lifespan startup (once)
            -> observer
            -> retrieval runtime (Chroma + restored BM25 + retriever + ingestion)
            -> LLM client
            -> compiled chat workflow placeholder
            -> app.state.services
        -> /api/health reads app.state.services only
        -> dependency functions return the same shared objects
        -> lifespan shutdown (once)
            -> stop accepting operations
            -> observer.flush()
            -> observer.shutdown()
            -> runtime.close()
```

Importing `src.main` constructs only the FastAPI object and settings. External
resource construction remains inside lifespan. The default runtime factory calls
the existing `build_retrieval_runtime()`, whose startup restores BM25 from the
persisted Chroma collection.

## Health Contract

`GET /api/health` performs local state checks only and never invokes LLM,
embedding, reranker, or Langfuse network APIs.

| Field | Meaning |
| --- | --- |
| `status` | Overall `ok`, `degraded`, or `unavailable` readiness |
| `request_id` | Local HTTP correlation ID; not a Langfuse trace ID |
| `chroma` | Local vector-store availability and chunk count |
| `bm25` | Generation, chunk count, rebuild/stale state, and safe error code |
| `llm` | Configuration presence and selected model |
| `embedding` | Configuration presence and selected model |
| `reranker` | Optional enabled/configured/available state and safe error code |
| `tracing` | Optional enabled/configured/available state and safe error code |

HTTP semantics:

- `200 / ok`: core components are ready and enabled optional components are
  available.
- `200 / degraded`: the BM25 index is stale/rebuilding/unavailable, or an
  enabled optional reranker/tracing component is unavailable.
- `503 / unavailable`: application runtime, Chroma, LLM configuration, or
  embedding configuration is unavailable.
- Disabled or unconfigured optional reranker/tracing components do not degrade
  the core service.

## Error Contract

Known application errors and unknown server errors use:

```json
{
  "error": {
    "code": "service_unavailable",
    "message": "The requested service is temporarily unavailable.",
    "request_id": "local-request-id"
  }
}
```

The request ID is returned in both the JSON body and `X-Request-ID` response
header. Unknown exceptions are logged server-side and return a generic message;
stack traces, paths, prompts, and credentials are not returned to clients.

## Verification

Executed from `backend/` on 2026-07-23:

```text
uv run pytest -q tests/test_api_health.py
7 passed, 1 warning

uv run pytest -q tests/test_app_lifespan.py
4 passed, 1 warning

uv run pytest -q
421 passed, 3 skipped, 1 warning
```

The warning is an upstream Starlette deprecation notice concerning TestClient's
current HTTPX adapter; it does not affect application behavior or test results.

Tests are deterministic and inject fake runtimes/observers. They make no real
provider or network calls.

## Acceptance Checklist

- [x] Application factory supports injected runtime and observer factories.
- [x] Module import does not start external resources.
- [x] Lifespan constructs one shared runtime and compiled workflow.
- [x] Dependencies reuse lifespan-owned services without hidden rebuilding.
- [x] Shutdown flushes/shuts down observability before closing runtime.
- [x] Cleanup failures are logged and do not prevent remaining cleanup steps.
- [x] Health covers ok, degraded, and unavailable states.
- [x] Missing Langfuse extra is explicitly diagnostic but not a core outage.
- [x] BM25 `needs_rebuild` is reported as degraded.
- [x] Core startup/Chroma failures return HTTP 503.
- [x] Success and error responses carry a local request ID.
- [x] Common error responses are stable and secret-free.
- [x] Document and chat business endpoints remain unimplemented in this task.
