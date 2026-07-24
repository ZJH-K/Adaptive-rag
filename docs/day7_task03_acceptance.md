# Day 7 Task 03 Acceptance: Async SSE Cancellation and Resource Release

## Production async path

The compiled LangGraph generation nodes now use a dual `RunnableLambda` contract:

- synchronous `graph.invoke()` uses `generate()` / `stream_generate()`;
- production `graph.astream()` uses `astream_generate()` and forwards each exact
  provider delta through LangGraph custom events.

Every async provider iterator is closed in `finally`. Provider errors retain their
typed failure classification, while task cancellation closes the generation
observation and propagates to the SSE adapter.

## Disconnect propagation

```text
HTTP socket closes
  -> ASGI http.disconnect
  -> route races disconnect against anext(service stream)
  -> pending graph event task is cancelled
  -> LangGraph async generation node is cancelled
  -> provider async iterator aclose/finally runs
  -> Trace root finishes with outcome=cancelled
  -> Observer active request count returns to zero
```

Route cleanup uses an AnyIO shield because Starlette may cancel the body iterator
from its response task group. The shield protects cleanup only; it does not suppress
the cancellation delivered to the graph/provider.

The real-disconnect integration test starts Uvicorn on an OS-assigned localhost
port, reads through the first token with `httpx.AsyncClient.stream()`, and closes
the HTTP response. Threading events—not timing sleeps—prove provider closure and
Trace completion. The test also proves that only `route` and the first `token`
were observed and that the provider never produced its second delta.

## Shared client shutdown

- `DeepSeekClient.close()` closes the synchronous OpenAI-compatible client.
- `DeepSeekClient.aclose()` closes the asynchronous client.
- `EmbeddingClient.close()` closes its provider client.
- `RetrievalRuntime.close()` independently closes embedding and owned Chroma
  resources, continues after one close failure, and is idempotent.
- FastAPI lifespan awaits async LLM close and runs blocking LLM, Observer, and
  runtime cleanup outside the event loop. Each resource is isolated so one cleanup
  failure cannot prevent later resources from closing.

## Remaining boundary

The integration test proves local TCP disconnect propagation through Uvicorn and
the application. Reverse-proxy buffering, process termination, and cross-process
cancellation remain deployment concerns outside this task.
