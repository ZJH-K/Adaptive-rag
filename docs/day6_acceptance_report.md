# Day 6 Acceptance Report

## Scope and result

D6-01 through D6-07 are integrated into one FastAPI-backed Adaptive RAG demo. The
Streamlit process owns only browser-session UI state; parsing, ingestion,
retrieval, model calls, and tracing remain in the backend. D6-07 automated tests
and the available real end-to-end paths passed.

Real optional Reranker and Langfuse exports were **NOT RUN** because the active
configuration reported both capabilities as disabled and unconfigured. Their
unavailable UI states and backend contracts were tested; no successful external
integration is claimed.

## Frontend structure

| File | Responsibility |
| --- | --- |
| `frontend/app.py` | Sidebar controls, chat rendering, incremental placeholders, Sources, and observable RAG process panel |
| `frontend/api_client.py` | Pooled JSON/SSE HTTP client, `BACKEND_URL`, timeouts, safe transport/backend errors, and stream closure |
| `frontend/sse.py` | Incremental UTF-8 SSE framing and JSON validation |
| `frontend/state.py` | Bounded history, chat event accumulation, partial-answer preservation, and local conversation clearing |
| `frontend/tests/` | Parser, client, state-machine, Fake Backend AppTest, error, and unavailable-backend coverage |

The frontend environment contains only `BACKEND_URL`. Provider model keys are
read by the FastAPI backend and are neither cached nor rendered by Streamlit.

## Backend calls made by Streamlit

| UI operation | Backend call | Consumption |
| --- | --- | --- |
| Upload PDF/Markdown | `POST /api/documents/upload` | Multipart file, knowledge-base ID, and file-compatible chunk strategy |
| Load built-in corpus | `POST /api/documents/load-default` | Per-file done/skipped/failed result and aggregate status |
| Refresh sidebar statistics | `GET /api/documents/stats` | Document/chunk counts plus BM25 readiness and generation |
| Send a chat message | `POST /api/chat/stream` | Incremental `text/event-stream` events |
| Read optional capability readiness | `GET /api/health` | Chroma/BM25/model readiness and honest Reranker/tracing states |

## Streaming and presentation contract

`SSEParser` incrementally decodes UTF-8 before framing lines, so a Chinese code
point or CRLF delimiter may be split across arbitrary network chunks. It ignores
comments, accepts multiple events per chunk and multiple `data:` lines, flushes a
final event on close, and converts malformed UTF-8/JSON/non-object payloads into
safe diagnostic errors. `AdaptiveRAGAPIClient.stream_chat()` iterates
`response.iter_bytes()` and closes the response when the generator is closed,
including Streamlit reruns or interruption.

`token` events update the assistant placeholder immediately. `route`, `rewrite`,
`retrieval`, and `done` populate the collapsed process panel. A received partial
answer remains visible if an `error` event follows it. Only the `sources` event
can populate citations; retrieval candidates are never reinterpreted as final
sources.

Sources are ordered by citation ID. PDF sources show the source filename and
one-based page; Markdown sources show section or heading path. Direct answers do
not render an empty Sources expander.

The process panel displays:

- Router retrieval decision and short public reason;
- rewritten standalone query;
- Dense/BM25 candidate counts and degraded source state;
- RRF entry and fused/final candidate counts;
- Reranker enabled/configured/used/degraded and final Top-K;
- request ID and tracing enabled/trace ID/export/error state.

It does not display prompts, private chain-of-thought, provider keys, stack
traces, or fabricated trace links.

## Automated verification

| Command | Result |
| --- | --- |
| `cd frontend && uv run pytest -q` | **20 passed in 7.48s** |
| `cd backend && uv run pytest -q` | **457 passed, 3 skipped, 1 warning in 64.49s** |

The three backend skips are optional external smoke tests gated by configuration.
The warning is Starlette's deprecation notice for its current `httpx` TestClient
integration and is not a test failure.

Frontend coverage includes arbitrary byte boundaries, byte-by-byte Chinese UTF-8,
multiple events, comments, final-event flushing, invalid JSON/UTF-8, JSON endpoint
contracts, early stream close, direct/RAG/error/done state transitions, bounded
history, local clear behavior, a Fake Backend Streamlit chat contract, partial
text on a structured stream error, and graceful backend unavailability.

## Real end-to-end evidence

Backend and frontend were launched locally with an isolated temporary Chroma
directory. FastAPI health returned `status=ok`; Streamlit returned HTTP 200 at
`http://127.0.0.1:8501`. No repository data directory was used for the smoke run.

- Markdown upload: `langgraph_checkpoint.md`, status `done`, 3 chunks.
- PDF upload: `ingestion_recovery_manual.pdf`, status `done`, 3 chunks.
- Built-in load: status `done`, processed 3, skipped 2 idempotent files, failed 0;
  final corpus was 5 documents and 22 chunks before the immediate-upload check.
- Immediate upload/query: `e2e_immediate.md`, status `done`, followed immediately
  by a successful RAG SSE stream whose first source was
  `e2e_immediate.md | section Immediate Upload Check`.
- Direct query: `route -> token -> done`, no Sources.
- PDF query: `route -> rewrite -> retrieval -> token... -> sources -> done`; top
  locations included pages 2, 3, and 1 of `ingestion_recovery_manual.pdf`.
- Markdown query: the same RAG lifecycle; top locations included the document's
  `LangGraph Checkpoint Quick Guide`, `Configuration summary`, and
  `Required conversation identifier` sections.
- Ambiguous follow-up: “那如果它变化了会怎样？” was rewritten to
  “如果 thread_id 变化了会怎样？” before hybrid retrieval.
- Every real chat ended with `done.status=success`. Health reported Reranker and
  tracing as `enabled=false`, `configured=false`, and `available=false`.

## Fifteen-item acceptance checklist

| # | Acceptance item | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Start backend and frontend | **PASS** | Both local processes launched; Streamlit HTTP 200 |
| 2 | `/api/health` available | **PASS** | Real response `status=ok`, Chroma/BM25 ready |
| 3 | Upload Markdown | **PASS** | Real 3-chunk `langgraph_checkpoint.md` ingestion |
| 4 | Upload parseable PDF | **PASS** | Real 3-page/3-chunk PDF ingestion |
| 5 | Load built-in corpus | **PASS** | 3 processed, 2 idempotently skipped, 0 failed |
| 6 | Ask immediately after upload | **PASS** | Unique in-memory Markdown upload immediately followed by successful RAG chat and matching first source |
| 7 | Direct question takes direct branch | **PASS** | Real `need_retrieval=false`; no rewrite/retrieval/sources |
| 8 | Document question takes RAG branch | **PASS** | Real rewrite, hybrid retrieval, sources, and successful done event |
| 9 | Ambiguous reference triggers Rewrite | **PASS** | Real history-aware standalone rewrite observed |
| 10 | Answer tokens update incrementally | **PASS** | Real response delivered many token events; Fake Backend AppTest verified placeholder consumption |
| 11 | PDF source locates page | **PASS** | Real Sources included PDF pages 1, 2, and 3 |
| 12 | Markdown source locates section | **PASS** | Real Sources included named Markdown sections |
| 13 | Unconfigured Reranker/Langfuse UI | **PASS (UI state)** / **NOT RUN (real integrations)** | Health and AppTest show disabled/unavailable; no external rerank/export attempted |
| 14 | Backend error does not crash page | **PASS** | AppTest preserved partial text, showed safe error code, and had no exception; unreachable backend also rendered safely |
| 15 | Clear affects only current UI state | **PASS** | Pure state test removes only browser-session messages; no backend mutation call exists |

## Suggested local screenshots

1. **Complete RAG answer:** browser at `http://localhost:8501` showing the final
   Markdown answer, ordered Sources with a PDF page and/or Markdown section, and
   no empty panels.
2. **Upload and process panel:** sidebar after a successful PDF/Markdown upload
   with updated document/chunk metrics, plus the expanded RAG process panel showing
   Router, Rewrite, Dense/BM25, RRF, unavailable Reranker, and tracing status.

These are screenshot recommendations only; no screenshot artifact was captured by
the automated run.

## Known limitations

- The demo intentionally supports one `technical_docs` knowledge base.
- Conversation state is browser-session-local and is not persisted by the backend.
- The full browser interaction is covered with Streamlit AppTest plus a local HTTP
  smoke test, not a heavyweight browser automation suite.
- Real Reranker quality/latency and Langfuse export/link behavior remain **NOT RUN**
  until those integrations are explicitly enabled and configured.
- The frontend intentionally provides no file-management, authentication,
  multi-tenant, or conversation-persistence features.
