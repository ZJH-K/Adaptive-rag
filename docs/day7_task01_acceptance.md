# Day 7 Task 01 Acceptance: Unified LangGraph and SSE Orchestration

## Authoritative production path

```text
POST /api/chat/stream
  -> lifespan-owned compiled LangGraph
  -> route_query
     -> direct_answer
     -> rewrite_query -> retrieve/context -> generate_answer
  -> ChatStreamingService (SSE mapping only)
```

`ApplicationServices.workflow` is compiled once during FastAPI lifespan startup.
`ChatStreamingService.workflow` references that exact object and consumes its
`astream(..., stream_mode=["custom", "tasks", "updates"])` output. The adapter no longer
calls Router, Rewrite, Retriever, ContextBuilder, or generation helpers itself.

## Streaming contract

Graph node updates produce `route`, `rewrite`, `retrieval`, and `sources` events.
Generation nodes consume `stream_generate()` and publish each unchanged provider
delta through LangGraph's custom event channel, which maps one-to-one to `token`.
The normal `graph.invoke()` path still uses `generate()`, so Evaluation and SSE
share graph topology, prompts, retrieval/context state, and failure contracts
without forcing Evaluation to consume a token stream.

The public event order remains:

- Direct: `route -> token... -> done`
- RAG: `route -> rewrite -> retrieval -> token... -> sources -> done`
- Fatal failure: observable events already completed, then `error -> done`

Sources and context chunk IDs are emitted only from the graph state populated by
`ContextBuilder`; the SSE adapter does not derive them from raw retrieval hits.
An empty retrieval result follows the graph's no-evidence generation result and
does not call grounded LLM generation.

## Automated verification

The tests cover direct zero-retrieval behavior, rewritten-query propagation,
ContextBuilder source identity, empty retrieval, known failure mapping, exact
provider deltas, Graph/SSE state agreement, and the shared lifespan workflow
object.

```text
backend:  459 passed, 3 skipped
frontend: 20 passed
```

## Remaining limitation

The compiled graph runs the synchronous provider stream inside LangGraph's node
execution. The provider iterator is closed when the graph stream closes, but
precise disconnect timing and request-state cleanup remain scoped to the later
Day 7 disconnect/request-lifecycle tasks.
