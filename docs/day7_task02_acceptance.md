# Day 7 Task 02 Acceptance: Request ID and Trace Lifecycle Hardening

## Identifier contract

- `request_id`: a server-generated 32-character UUID hex value unique to every
  HTTP request. It is the only key used for Observer state and Langfuse roots.
- `client_request_id`: optional correlation metadata from `X-Request-ID`. It is
  accepted only when it matches `[A-Za-z0-9._:-]{1,128}` and never keys resources.
- `trace_id`: a real provider trace identifier. No-op/unavailable tracing leaves
  it unset.
- `trace_exported`: true only after the configured provider confirms a successful
  flush.

Responses expose the internal ID as `X-Request-ID`. A valid client correlation ID
is echoed separately as `X-Client-Request-ID` and in the terminal SSE `done` data.
Invalid client IDs receive a JSON `400 invalid_client_request_id` response while
still receiving a safe internal request ID.

## Lifecycle and release policy

`SafeTraceObserver` owns active request state until exactly one terminal operation:
`finish_request`, `fail_request`, or `cancel_request`. A terminal operation moves
the entry into a transient finishing guard, releases it after provider finalization,
returns an immutable terminal snapshot, and is safe to repeat. SSE `done` consumes
the snapshot returned in the LangGraph state rather than querying a completed
request from global state.

For short-term idempotency, terminal snapshots use an LRU cache with capacity 256
and TTL 300 seconds. It never owns provider resources. Both normal shutdown and
exception paths close active requests; Langfuse roots are keyed only by the unique
internal request ID and removed at terminal completion.

## Verification coverage

- concurrent API requests with the same client correlation ID retain distinct
  internal request IDs, trace IDs, roots, and terminal events;
- missing, invalid, and oversized client IDs;
- 1000 completed No-op requests return active state to zero and stay within the
  bounded terminal cache;
- success, known failure, unknown failure, cancellation, provider-finalization
  failure, and repeated terminal calls all release active state;
- tracing-unavailable responses never claim a trace ID or successful export.
