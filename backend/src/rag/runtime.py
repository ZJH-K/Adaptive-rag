"""Application composition root for a restart-safe retrieval runtime."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Protocol, Self

from src.config import Settings
from src.rag.ingestion import DocumentEmbedder, IngestionPipeline
from src.rag.retrieval.bm25 import BM25Retriever
from src.rag.retrieval.bm25_index import BM25Index, BM25IndexStatus
from src.rag.retrieval.dense import DenseRetriever, QueryEmbedder
from src.rag.retrieval.pipeline import HybridRetrievalPipeline
from src.rag.retrieval.reranker import Reranker, build_reranker
from src.rag.retrieval.tokenizer import Tokenizer
from src.rag.schemas import Chunk
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
        consistency_lock: RLock,
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
        self._consistency_lock = consistency_lock

    def rebuild_from_store(self) -> BM25IndexStatus:
        """Explicitly recover BM25 from the authoritative Chroma corpus."""
        with self._consistency_lock:
            self.bm25_index.mark_needs_rebuild()
            try:
                self.bm25_index.rebuild(self.vector_store.get_all_chunks())
            except Exception as exc:
                self.bm25_index.mark_needs_rebuild("bm25_rebuild_failed")
                raise RetrievalRuntimeBootstrapError(
                    "Failed to restore BM25 from the persisted Chroma corpus"
                ) from exc
            return self.bm25_index.status()

    def rebuild_bm25(self) -> None:
        """Backward-compatible alias for explicit BM25 recovery."""
        self.rebuild_from_store()

    def startup(self) -> BM25IndexStatus:
        """Restore the persisted BM25 corpus for application lifespan startup."""
        return self.rebuild_from_store()

    def get_index_status(self) -> BM25IndexStatus:
        """Return the current request-safe BM25 health snapshot."""
        return self.bm25_index.status()

    def get_corpus_snapshot(self) -> tuple[list[Chunk], BM25IndexStatus]:
        """Atomically read the authoritative corpus and its BM25 status."""
        with self._consistency_lock:
            return self.vector_store.get_all_chunks(), self.bm25_index.status()

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
    consistency_lock = RLock()

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
        consistency_lock=consistency_lock,
    )
    runtime = RetrievalRuntime(
        vector_store=store,
        bm25_index=index,
        dense_retriever=dense,
        bm25_retriever=bm25,
        reranker=configured_reranker,
        retriever=retriever,
        ingestion_pipeline=ingestion,
        owns_vector_store=owns_vector_store,
        consistency_lock=consistency_lock,
    )
    try:
        runtime.startup()
    except RetrievalRuntimeBootstrapError:
        runtime.close()
        raise
    return runtime
