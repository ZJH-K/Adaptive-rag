"""Synchronous single-document ingestion orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from src.rag.chunking.factory import (
    Chunker,
    ChunkerFactory,
    ChunkingStrategy,
)
from src.rag.chunking.recursive import RecursiveChunker
from src.rag.parsers.factory import ParserFactory
from src.rag.retrieval.bm25_index import BM25Index
from src.rag.vectorstore.chroma import ChromaVectorStore


class DocumentEmbedder(Protocol):
    """Embedding capability required by the ingestion pipeline."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector for every input text in the same order."""
        ...


class IngestionError(RuntimeError):
    """Raised when a parsed document cannot produce ingestible chunks."""


class BM25IndexSyncError(IngestionError):
    """Raised when vectors persisted but the in-memory BM25 refresh failed."""


class IngestionResult(BaseModel):
    """Summary returned after a document is successfully persisted."""

    document_id: str
    filename: str
    chunks_count: int
    status: Literal["done"] = "done"


class IngestionPipeline:
    """Coordinate parsing, selected chunking, embedding, and persistence."""

    def __init__(
        self,
        embedding_client: DocumentEmbedder,
        vector_store: ChromaVectorStore,
        *,
        chunker: Chunker | None = None,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        bm25_index: BM25Index | None = None,
    ) -> None:
        """Inject pipeline components and configure factory-created chunkers."""
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        self.chunker: Chunker = chunker or RecursiveChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.bm25_index = bm25_index

    def ingest(
        self,
        file_path: str | Path,
        chunk_strategy: ChunkingStrategy | None = None,
    ) -> IngestionResult:
        """Synchronously ingest a file with an optional explicit strategy."""
        parser = ParserFactory.get_parser(file_path)
        document = parser.parse(file_path)
        if chunk_strategy is None:
            chunker = self.chunker
        else:
            chunker = ChunkerFactory.create(
                chunk_strategy,
                source_type=document.source_type,
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )
        chunks = chunker.chunk(document)
        if not chunks:
            raise IngestionError(
                f"Document '{document.filename}' produced no ingestible chunks"
            )

        embeddings = self.embedding_client.embed_documents(
            [chunk.text for chunk in chunks]
        )
        self.vector_store.upsert_chunks(chunks, embeddings)
        if self.bm25_index is not None:
            try:
                self.bm25_index.rebuild(self.vector_store.get_all_chunks())
            except Exception as exc:
                self.bm25_index.mark_needs_rebuild()
                raise BM25IndexSyncError(
                    "Vector persistence succeeded, but BM25 refresh failed; "
                    "the index is marked for a full rebuild"
                ) from exc
        return IngestionResult(
            document_id=document.document_id,
            filename=document.filename,
            chunks_count=len(chunks),
        )
