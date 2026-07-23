# Notices and Reference Boundaries

## AnyKB

Reference repository: [GU-Cryptography/anykb](https://github.com/GU-Cryptography/anykb)

The project reviewed AnyKB at commit
`aa7c02e8d70a383c2535cd31109a43e11aa303bd` and used it as an architectural
reference, not as the project foundation.

### High-level ideas referenced

- parser responsibility boundaries and minimal Markdown cleanup;
- recursive chunking fallback from paragraphs to sentences to characters;
- separation of ingestion, embedding, retrieval, and reranking concerns.

### Independently redesigned and implemented here

- page-preserving PDF and heading-aware Markdown schemas/parsers;
- stable content-derived Chunk identifiers and three Chunk strategies;
- OpenAI-compatible batched Embedding Client;
- Chroma persistence, in-process BM25, RRF, and failure-aware Hybrid Retrieval;
- provider-neutral Reranker Adapter and fallback contract;
- Context/Sources identity mapping;
- LangGraph/SSE orchestration, cancellation, Request ID, and Trace lifecycle;
- Evaluation dataset, metrics, A/B/C/D Runner, API, frontend, and deployment.

### Not reused

- AnyKB Agent Tool Loop and skill/report framework;
- authentication, users, permissions, collaboration, or multi-tenancy;
- conversation/long-term memory;
- Next.js frontend, Web Search, admin system;
- Redis, PostgreSQL, Milvus/Qdrant infrastructure and deployment topology.

Repository-wide attribution search and implementation review found no AnyKB
source file copied into this repository. This statement describes the engineering
review performed for this project; it is not a legal or exhaustive source-code
provenance audit.

## LICENSE VERIFICATION REQUIRED

As rechecked on 2026-07-23, the AnyKB README labels the project as MIT, but its
repository root does not expose a LICENSE file and GitHub does not provide a
verifiable license document for this repository. The README label alone is not a
substitute for the license text.

Do not copy or adapt AnyKB source code unless the upstream license is independently
verified and all copyright/attribution conditions are retained. If source is
copied later, update this NOTICE with the exact upstream commit, file paths,
copyright notice, license text/location, and local modifications.

## This repository

This repository currently has no project-level LICENSE file. Its owner must select
and add one before public distribution terms can be represented as settled.
