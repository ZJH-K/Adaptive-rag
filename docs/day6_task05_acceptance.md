# Day 6 Task 05 Acceptance: Documents API

## Scope

This task adds the three browser-demo document endpoints. All ingestion uses the
single `DocumentService` and `RetrievalRuntime` created by FastAPI lifespan; no
route constructs a parser, chunker, embedding client, vector store, BM25 index,
or second runtime.

## Endpoints

### `POST /api/documents/upload`

Multipart request:

```text
file=@guide.md
knowledge_base_id=technical_docs
chunk_strategy=markdown_heading
```

Complete response:

```json
{
  "document_id": "sha256-content-id",
  "filename": "guide.md",
  "chunks_count": 3,
  "status": "done",
  "duplicate": false,
  "bm25_generation": 1,
  "error_code": null
}
```

`done` is returned only after an atomic runtime snapshot confirms that BM25 is
not stale and its chunk count matches the authoritative Chroma corpus. A Chroma
write followed by a failed BM25 rebuild returns `status=degraded` with a safe
error code instead of ordinary success.

### `POST /api/documents/load-default`

An empty body selects automatic strategies: `markdown_heading` for Markdown and
`pdf_page_aware` for PDF. A request may instead specify one strategy:

```json
{
  "knowledge_base_id": "technical_docs",
  "chunk_strategy": "recursive"
}
```

Example response:

```json
{
  "status": "done",
  "knowledge_base_id": "technical_docs",
  "processed": 5,
  "skipped": 0,
  "failed": 0,
  "chunks_count": 22,
  "items": []
}
```

The real response includes one safe item per file. A second load identifies the
same content-and-strategy representation and reports it as `skipped`, without
embedding or increasing Chroma counts. One file failure is isolated and changes
the aggregate status to `degraded`; if every file fails it is `failed`.

### `GET /api/documents/stats`

Example response:

```json
{
  "knowledge_base_id": "technical_docs",
  "documents_count": 5,
  "chunks_count": 22,
  "chroma": {"status": "ready", "chunk_count": 22},
  "bm25": {
    "status": "ready",
    "generation": 6,
    "chunk_count": 22,
    "needs_rebuild": false
  }
}
```

Counts come from an atomic live Chroma/BM25 runtime snapshot, not from scanning
the upload or built-in knowledge directories.

## Validation and Security

- Accepted extensions are `.pdf`, `.md`, and `.markdown`; the extension is the
  primary type selector and MIME is an additional consistency check.
- PDF bytes must contain a PDF signature in the first 1024 bytes.
- Empty and over-limit uploads are rejected before ingestion. The default limit
  is 10 MiB and is configurable with `UPLOAD_MAX_BYTES`.
- Only the configured `KNOWLEDGE_BASE_ID` is accepted; this remains a
  single-knowledge-base MVP and does not create collections dynamically.
- Strategy names and source compatibility are validated before ingestion.
- Path components and control characters are removed/rejected from filenames.
- Upload bytes are written under a unique `TemporaryDirectory`; the entire
  directory is removed on success and on every failure path.
- Parser, embedding, Chroma, BM25, missing-directory, and request-validation
  failures map to stable codes and the common request-ID error envelope.
- Client errors never include exception stacks, provider responses, or local
  filesystem paths.

## Status Semantics

| Status | Meaning |
| --- | --- |
| `done` | Chroma persistence and the latest BM25 snapshot are consistent |
| `degraded` | Dense content exists, but BM25 publication/verification is not ready, or a batch has partial failures |
| `failed` | Batch-level result where every supported document failed |
| `skipped` | Exact content and chunk strategy already exist |

Request failures use HTTP status codes: validation `400/413/415/422`, embedding
provider failure `502`, and document-store/runtime failure `503`.

## Concurrency and Consistency

The existing ingestion consistency lock serializes Chroma publish and BM25
rebuild. D6-05 extends the runtime with `get_corpus_snapshot()`, which reads the
Chroma corpus and BM25 status under the same lock. Concurrent upload responses
and stats therefore cannot observe the transient interval between vector write
and lexical-index publication.

## Automated Verification

Executed from `backend/` on 2026-07-23:

```text
uv run pytest -q tests/test_api_documents.py
15 passed, 1 warning

uv run pytest -q tests/test_ingestion.py
16 passed

uv run pytest -q
437 passed, 3 skipped, 1 warning
```

Coverage includes Markdown/PDF upload, page metadata, immediate retrieval,
concurrent ingestion, real index stats, empty/unsupported/oversized input, PDF
without text, filename traversal, temporary cleanup, duplicate upload,
idempotent default loading, partial batch failure, missing corpus, BM25 failure,
embedding failure, vector-store failure, knowledge-base validation, and strategy
compatibility. Provider calls are replaced by deterministic fake embeddings.

The warning is an upstream Starlette TestClient deprecation warning and does not
affect the result.

## Manual Offline Smoke

An application was started with the real built-in corpus, temporary Chroma, and
a fake embedding client:

```text
upload:      HTTP 200, done, 3 chunks
first load:  done, processed=4, skipped=1, failed=0, new chunks=19
second load: done, processed=0, skipped=5, failed=0, new chunks=0
stats:       documents=5, Chroma chunks=22, BM25 chunks=22, BM25 ready
```

The first load skipped the document already uploaded by the smoke step. All
temporary Chroma and upload data were removed when the smoke process exited.
