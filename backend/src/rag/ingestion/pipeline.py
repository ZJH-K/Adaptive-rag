"""Synchronous single-document ingestion orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from src.rag.chunking.recursive import RecursiveChunker
from src.rag.parsers.factory import ParserFactory
from src.rag.vectorstore.chroma import ChromaVectorStore


class DocumentEmbedder(Protocol):
    """Embedding capability required by the ingestion pipeline."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector for every input text in the same order."""
        ...


class IngestionError(RuntimeError):
    """Raised when a parsed document cannot produce ingestible chunks."""


class IngestionResult(BaseModel):
    """Summary returned after a document is successfully persisted."""

    document_id: str
    filename: str
    chunks_count: int
    status: Literal["done"] = "done"


class IngestionPipeline:
    """Coordinate parsing, recursive chunking, embedding, and persistence."""

    def __init__(
        self,
        embedding_client: DocumentEmbedder,
        vector_store: ChromaVectorStore,
        *,
        chunker: RecursiveChunker | None = None,
    ) -> None:
        """Inject pipeline components without performing any work."""
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        self.chunker = chunker or RecursiveChunker()

    def ingest(self, file_path: str | Path) -> IngestionResult:
        """Synchronously ingest one supported document file."""
        parser = ParserFactory.get_parser(file_path)
        document = parser.parse(file_path)
        chunks = self.chunker.chunk(document)
        if not chunks:
            raise IngestionError(
                f"Document '{document.filename}' produced no ingestible chunks"
            )

        embeddings = self.embedding_client.embed_documents(
            [chunk.text for chunk in chunks]
        )
        self.vector_store.upsert_chunks(chunks, embeddings)
        return IngestionResult(
            document_id=document.document_id,
            filename=document.filename,
            chunks_count=len(chunks),
        )

