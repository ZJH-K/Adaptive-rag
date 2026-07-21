# Day 1 Acceptance Report

## Scope

Day 1 validates the baseline technical-document retrieval chain:

```text
Markdown / PDF
-> Parser
-> RecursiveChunker
-> OpenAI-compatible Embedding
-> persistent Chroma
-> DenseRetriever
```

No Day 2 features such as structure-aware chunking, answer generation, hybrid
retrieval, reranking, FastAPI, or LangGraph orchestration are included.

## Environment

- Operating system: Windows
- Python: 3.13.13 (project requirement is Python 3.11+)
- Dependency manager: uv 0.11.7
- Chroma: 1.5.9
- Automated embeddings: deterministic Fake Embedding Client, no network
- Manual smoke embeddings: configured OpenAI-compatible service

## Automated Verification

From the backend directory:

```powershell
uv sync
uv run pytest -q
```

The acceptance suite includes unit tests for Settings, schemas, parsers,
recursive chunking, embedding responses, and Chroma, plus integration tests for
ingestion, persistence, idempotency, and dense retrieval.

Latest result on 2026-07-22:

```text
81 passed in 10.08s
```

The offline end-to-end acceptance test ingested both bundled documents twice,
reopened the persistent Chroma directory, and returned the expected Markdown and
PDF sources for all three deterministic queries.

## Real Smoke Test

Create `.env` from `.env.example`, provide a valid embedding API key, and run:

```powershell
cd backend
uv run python scripts/day1_smoke_test.py
```

The script does not print the API key. It ingests the bundled Markdown and PDF,
repeats both ingestions, restarts Chroma, and performs three real dense queries.
It uses a dedicated collection whose name ends in `_day1_smoke`, leaving the main
configured collection untouched.
If `EMBEDDING_API_KEY` is absent, it exits with code 2 and prints configuration
instructions without attempting a network request.

Latest real-service result on 2026-07-22:

```text
Markdown: 1 chunk
PDF: 2 chunks
Idempotency: 3 -> 3 (unchanged)
Persistence: restored 3 chunks after restart
All three real dense queries returned the expected source as Top-1.
Day 1 real smoke test passed.
```

The real smoke test used Alibaba Cloud Model Studio's
`qwen3.7-text-embedding` model with 1,024-dimensional vectors. The ignored
project-root `.env` supplied the API key without exposing or committing it.

## Manual Acceptance Checklist

- [x] Markdown ingestion succeeds with the offline acceptance client.
- [x] Two-page PDF ingestion succeeds with the offline acceptance client.
- [x] PDF chunks retain page numbers 1 and 2.
- [x] Markdown chunks retain `langgraph_checkpoint.md` as their source.
- [x] Repeated ingestion leaves the Chroma count unchanged.
- [x] A new Chroma store instance reads the persisted chunks.
- [x] All three offline acceptance questions return the expected chunks.
- [x] The missing-key path gives a clear prompt and does not expose a secret.
- [x] Run all three questions through the configured real embedding service.
- [x] Review successful real output for text, source, page, and dense score.

## Acceptance Status

Passed:

- All Day 1 unit and offline integration tests.
- Markdown and two-page PDF parsing, chunking, ingestion, and metadata checks.
- Stable IDs, idempotent upsert, Chroma restart persistence, and Dense Retrieval.
- PDF visual and extractable-text inspection.
- Missing API key safety behavior.
- Real embedding-service ingestion, persistence, idempotency, and retrieval.
- Expected Top-1 source for all three real-service acceptance questions.

Day 1 acceptance is complete.

## Known Limitations

- The baseline chunker sizes text by characters rather than tokenizer tokens.
- Scanned PDFs and OCR are not supported.
- Dense retrieval quality depends on the configured embedding model.
- The smoke script is synchronous and intended for developer acceptance only.
- There is no API, UI, answer generation, hybrid retrieval, or reranking on Day 1.
