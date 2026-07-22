# Day 6 Task 06 Acceptance: Chat SSE and Provider Token Streaming

## Endpoint and Request Boundary

`POST /api/chat/stream` accepts JSON:

```json
{
  "question": "文档中的 RRF 如何计算？",
  "knowledge_base_id": "technical_docs",
  "chat_history": []
}
```

Question whitespace is stripped and blank input is rejected. The request model
limits the question and each history message to 4000 characters and the submitted
history to 20 messages. Before Router, Rewrite, and Direct Answer run, all three
reuse `bounded_chat_history()`, which selects at most the newest six messages and
4000 total history characters. Only the configured MVP knowledge base is accepted.
Validation failures return the normal JSON error envelope before an SSE response
is opened.

## Typed SSE Contract

Every event is a Pydantic model from `src/api/sse.py` and is serialized by one
`encode_sse_event()` function as:

```text
event: <name>
data: <UTF-8 JSON>

```

Events:

| Event | Data |
| --- | --- |
| `route` | `need_retrieval`, bounded safe `reason` |
| `rewrite` | standalone `rewritten_query` |
| `retrieval` | mode, counts, RRF/rerank flags, degradation codes, text-free hit summaries, safe latency |
| `token` | one unmodified provider text delta |
| `sources` | exact `ContextBuilder.sources` and `used_chunk_ids` |
| `error` | safe code/message and retryability |
| `done` | terminal status, local request ID, real trace ID/status, export result |

Fixed order:

```text
Direct: route -> token* -> done
RAG:    route -> rewrite -> retrieval -> token* -> sources -> done
Failed: emitted process events -> error -> done(status=failed)
```

The response sets:

```text
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
X-Accel-Buffering: no
```

## Real Provider Streaming

`DeepSeekClient.stream_generate()` sends `stream=true` to the OpenAI-compatible
chat-completions API and yields each SDK `choices[0].delta.content` unchanged.
`DeepSeekClient.astream_generate()` is the default production path used by the
chat service; it uses `AsyncOpenAI`, so task cancellation interrupts a pending
Provider read and closes the upstream stream in `finally`.

Empty deltas are ignored. Provider creation timeout, mid-stream timeout, malformed
chunks, and interrupted streams map to project-level LLM exceptions. The final
answer used for tracing is formed only by joining already-emitted deltas. No code
path calls non-streaming `generate()` and slices its completed response; tests use
a fake whose `generate()` raises immediately, while distinct Provider deltas still
produce distinct `token` events.

## Workflow Reuse

`ChatStreamingService` calls the existing `route_query()`, `rewrite_query()`, and
`retrieve()` business functions. Direct messages come from the same
`build_direct_answer_messages()` helper used by the synchronous node. Grounded
messages come from the existing `build_rag_messages()` function. Retrieval still
uses the existing retrieval pipeline, RRF, reranker, failure contracts, and
`ContextBuilder`; the API layer does not reproduce prompts or retrieval logic.

The compiled LangGraph workflow remains lifespan-owned for non-streaming workflow
consumers. The SSE service shares the same lifespan-owned LLM, retriever, observer,
context logic, and local request ID.

## Sources Mapping

The `sources` event is created only from `AgentState.context_sources` and
`context_chunk_ids`, which are direct outputs of `ContextBuilder.build()`. It is
not recalculated from raw `retrieved_documents`. Tests verify that content-hash
duplicates are omitted, budget-truncated context produces only its actual sources,
and citation IDs remain continuous (`S1`, `S2`, ...). PDF page and Markdown
section/heading locations are retained.

## Errors, Degradation, and Cancellation

- Router invalid structured output uses the existing conservative retrieval
  fallback and emits a safe route reason.
- Dense/BM25 single-path or reranker degradation remains answerable and is exposed
  in the `retrieval` diagnostics.
- Dual retrieval failure, unknown workflow exceptions, and generation failures
  emit a safe `error` followed by `done(status=failed)`; the connection does not
  terminate silently.
- Client disconnect closes the chat async generator, closes/cancels the Provider
  stream, suppresses subsequent business events, and finishes tracing with the
  `cancelled` outcome. Sending a `done` event to an already-disconnected socket is
  intentionally not attempted.
- `request_id` is always the local HTTP correlation ID. `trace_id` is only the
  actual provider trace ID. With tracing disabled it is null. Trace export failure
  does not fail the answer and is reported as `trace_exported=false` with a safe
  trace error code.

## Verification

Executed from `backend/` on 2026-07-23:

```text
uv run pytest -q tests/test_llm_streaming.py
7 passed

uv run pytest -q tests/test_sse_events.py
9 passed

uv run pytest -q tests/test_api_chat_stream.py
4 passed, 1 warning

uv run pytest -q
457 passed, 3 skipped, 1 warning
```

The warning is an upstream Starlette TestClient deprecation warning and does not
affect the result. All task tests are offline and use fake Provider streams.

## Offline Smoke and Redacted curl-equivalent Output

The FastAPI endpoint was exercised through a streaming HTTP test client with the
same request/response boundary as `curl -N`:

```text
HTTP 200
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
X-Accel-Buffering: no
X-Request-ID: smoke-chat-1

event: route
data: {"need_retrieval":true,"reason":"safe reason"}

event: rewrite
data: {"rewritten_query":"rewritten query"}

event: retrieval
data: {"mode":"unknown","dense_count":1,"bm25_count":0,"final_count":1,"hits":[{"chunk_id":"chunk-1","source":"manual.pdf","page":2}]}

event: token
data: {"text":"第一段"}

event: token
data: {"text":"第二段"}

event: sources
data: {"sources":[{"citation_id":"S1","source":"manual.pdf","page":2,"chunk_id":"chunk-1"}],"context_chunk_ids":["chunk-1"]}

event: done
data: {"status":"success","request_id":"smoke-chat-1","trace_id":null,"tracing_enabled":false,"trace_exported":false}
```

The sample is intentionally abbreviated to the contract-relevant, secret-free
fields. No real Provider network call was made during the offline smoke.
