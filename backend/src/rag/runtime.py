"""Application composition root for a restart-safe retrieval runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Self

from src.config import Settings
from src.rag.ingestion import DocumentEmbedder, IngestionPipeline
from src.rag.retrieval.bm25 import BM25Retriever
from src.rag.retrieval.bm25_index import BM25Index
from src.rag.retrieval.dense import DenseRetriever, QueryEmbedder
from src.rag.retrieval.pipeline import HybridRetrievalPipeline
from src.rag.retrieval.reranker import Reranker, build_reranker
from src.rag.retrieval.tokenizer import Tokenizer
from src.rag.vectorstore.chroma import ChromaVectorStore


class RuntimeEmbeddingClient(DocumentEmbedder, QueryEmbedder, Protocol):
    """Embedding operations needed by retrieval and ingestion."""


class RetrievalRuntimeBootstrapError(RuntimeError):
    """Raised when persisted chunks cannot initialize the retrieval runtime."""


class RetrievalRuntime:
    """Hold consistently assembled retrieval and ingestion components."""

    def __init__(
        self,
        *,
        vector_store: ChromaVectorStore,
        bm25_index: BM25Index,
        dense_retriever: DenseRetriever,
        bm25_retriever: BM25Retriever,
        reranker: Reranker,
        retriever: HybridRetrievalPipeline,
        ingestion_pipeline: IngestionPipeline,
        owns_vector_store: bool,
    ) -> None:
        """Store components created by :func:`build_retrieval_runtime`."""
        self.vector_store = vector_store
        self.bm25_index = bm25_index
        self.dense_retriever = dense_retriever
        self.bm25_retriever = bm25_retriever
        self.reranker = reranker
        self.retriever = retriever
        self.ingestion_pipeline = ingestion_pipeline
        self._owns_vector_store = owns_vector_store

    def rebuild_bm25(self) -> None:
        """Rebuild BM25 from the authoritative persisted Chroma corpus."""
        self.bm25_index.rebuild(self.vector_store.get_all_chunks())

    def close(self) -> None:
        """Close the vector store when this runtime created it."""
        if self._owns_vector_store:
            self.vector_store.close()

    def __enter__(self) -> Self:
        """Return this initialized runtime as a context manager."""
        return self

    def __exit__(self, *_: object) -> None:
        """Release owned resources when leaving the context."""
        self.close()


def build_retrieval_runtime(
    embedding_client: RuntimeEmbeddingClient,
    *,
    settings: Settings | None = None,
    vector_store: ChromaVectorStore | None = None,
    tokenizer: Tokenizer | None = None,
    persist_dir: str | Path | None = None,
    collection_name: str | None = None,
    reranker: Reranker | None = None,
) -> RetrievalRuntime:
    """Restore BM25 from Chroma and assemble the complete retrieval runtime."""
    configured = settings or Settings()
    owns_vector_store = vector_store is None
    store = vector_store or ChromaVectorStore(
        configured,
        persist_dir=persist_dir,
        collection_name=collection_name,
    )
    index = BM25Index(tokenizer=tokenizer)
    try:
        index.rebuild(store.get_all_chunks())
    except Exception as exc:
        if owns_vector_store:
            store.close()
        raise RetrievalRuntimeBootstrapError(
            "Failed to restore BM25 from the persisted Chroma corpus"
        ) from exc

    dense = DenseRetriever(
        embedding_client,
        store,
        top_k=configured.dense_top_n,
    )
    bm25 = BM25Retriever(index, top_n=configured.bm25_top_n)
    configured_reranker = (
        reranker if reranker is not None else build_reranker(configured)
    )
    retriever = HybridRetrievalPipeline(
        dense,
        bm25,
        reranker=configured_reranker,
        settings=configured,
    )
    ingestion = IngestionPipeline(
        embedding_client,
        store,
        bm25_index=index,
    )
    return RetrievalRuntime(
        vector_store=store,
        bm25_index=index,
        dense_retriever=dense,
        bm25_retriever=bm25,
        reranker=configured_reranker,
        retriever=retriever,
        ingestion_pipeline=ingestion,
        owns_vector_store=owns_vector_store,
    )
