# Embedding Client Operations

This guide describes the batching contract used by the Adaptive RAG embedding
client. Document ingestion and query retrieval share one remote embedding model,
but they use different public methods and validation rules.

## Document embedding

`embed_documents(texts)` accepts an ordered list of non-empty strings. The client
divides that list into batches controlled by `EMBEDDING_BATCH_SIZE`. A batch size
of 32 means that 70 documents produce three upstream requests containing 32, 32,
and 6 inputs. Returned vectors are restored to input order before the method
returns, even when the provider returns indexed items out of order.

### Failure contract

If any batch fails, ingestion stops and no partial vector-store write should be
performed. The client raises `EmbeddingRequestError` for upstream failures and
`EmbeddingResponseError` when vector count, index order, or dimension is invalid.

## Query embedding

`embed_query(text)` accepts exactly one non-blank query and returns one vector.
It reuses the document embedding validation path, but it does not use a separate
query model. This keeps document and query vectors in the same vector space.

### Query failure contract

A blank query fails locally with `EmbeddingInputError` before any network call.
Remote failures use the same project-level exceptions as document embedding.

## Runtime configuration

`EMBEDDING_MODEL` selects the provider model, `EMBEDDING_DIMENSION` validates
vector width, and `EMBEDDING_TIMEOUT_SECONDS` bounds each request. Configuration
values come from `.env`; API keys must never be committed or included in errors.
