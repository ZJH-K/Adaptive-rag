"""Persistent Chroma adapter for pre-computed chunk embeddings."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from src.config import Settings
from src.rag.schemas import Chunk
from src.rag.vectorstore.exceptions import (
    VectorStoreConfigurationError,
    VectorStoreInputError,
    VectorStoreResponseError,
)


ScalarMetadata = str | int | float | bool


@dataclass(frozen=True, slots=True)
class VectorQueryResult:
    """One vector query result returned in Chroma ranking order."""

    chunk_id: str
    text: str
    metadata: dict[str, Any]
    distance: float


def serialize_chunk_metadata(chunk: Chunk) -> dict[str, ScalarMetadata]:
    """Convert Chunk metadata into Chroma-supported scalar values."""
    metadata: dict[str, ScalarMetadata] = {
        "document_id": chunk.document_id,
        "chunk_index": chunk.chunk_index,
        "source": chunk.source,
        "source_type": chunk.source_type,
        "chunk_strategy": chunk.chunk_strategy,
        "content_hash": chunk.content_hash,
        "heading_path": json.dumps(
            chunk.heading_path,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    if chunk.page is not None:
        metadata["page"] = chunk.page
    if chunk.section is not None:
        metadata["section"] = chunk.section
    return metadata


def deserialize_chunk_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Restore JSON-encoded complex metadata from Chroma."""
    restored = dict(metadata)
    encoded_heading_path = restored.get("heading_path", "[]")
    if not isinstance(encoded_heading_path, str):
        raise VectorStoreResponseError("Stored heading_path metadata is not a string")
    try:
        heading_path = json.loads(encoded_heading_path)
    except json.JSONDecodeError as exc:
        raise VectorStoreResponseError(
            "Stored heading_path metadata is not valid JSON"
        ) from exc
    if not isinstance(heading_path, list) or not all(
        isinstance(item, str) for item in heading_path
    ):
        raise VectorStoreResponseError(
            "Stored heading_path metadata is not a string list"
        )
    restored["heading_path"] = heading_path
    restored.setdefault("page", None)
    restored.setdefault("section", None)
    return restored


class ChromaVectorStore:
    """Persist and query pre-computed embeddings with a Chroma collection."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        persist_dir: str | Path | None = None,
        collection_name: str | None = None,
        client: ClientAPI | None = None,
    ) -> None:
        """Open or create a cosine-distance persistent collection."""
        configured = settings or Settings()
        self.persist_dir = Path(
            configured.chroma_persist_dir if persist_dir is None else persist_dir
        )
        self.collection_name = (
            configured.chroma_collection
            if collection_name is None
            else collection_name
        )
        if not self.collection_name.strip():
            raise VectorStoreConfigurationError(
                "Chroma collection name must not be empty"
            )

        self._owns_client = client is None
        self._client = client or chromadb.PersistentClient(path=self.persist_dir)
        self._collection: Collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )
        self._closed = False

    def upsert_chunks(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        """Insert or replace chunks and their already-computed embeddings."""
        self._ensure_open()
        if len(chunks) != len(embeddings):
            raise VectorStoreInputError(
                "Chunk count must match embedding count: "
                f"got {len(chunks)} chunks and {len(embeddings)} embeddings"
            )
        if not chunks:
            return

        chunk_ids = [chunk.chunk_id for chunk in chunks]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise VectorStoreInputError("Chunk IDs must be unique within an upsert")
        self._validate_embeddings(embeddings)

        self._collection.upsert(
            ids=chunk_ids,
            embeddings=embeddings,
            documents=[chunk.text for chunk in chunks],
            metadatas=[serialize_chunk_metadata(chunk) for chunk in chunks],
        )

    def query_by_vector(
        self,
        query_embedding: list[float],
        top_k: int,
    ) -> list[VectorQueryResult]:
        """Return nearest chunks for one query vector in distance order."""
        self._ensure_open()
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
            raise VectorStoreInputError("top_k must be a positive integer")
        self._validate_embeddings([query_embedding])

        collection_count = self.count()
        if collection_count == 0:
            return []
        result = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection_count),
            include=["documents", "metadatas", "distances"],
        )
        return self._parse_query_result(result)

    def count(self) -> int:
        """Return the number of unique chunks in the collection."""
        self._ensure_open()
        return self._collection.count()

    def get_chunks_by_document_id(self, document_id: str) -> list[Chunk]:
        """Load and reconstruct all chunks belonging to one document."""
        self._ensure_open()
        if not isinstance(document_id, str) or not document_id.strip():
            raise VectorStoreInputError("document_id must be a non-empty string")
        result = self._collection.get(
            where={"document_id": document_id},
            include=["documents", "metadatas"],
        )
        chunks = self._parse_stored_chunks(result)
        return sorted(chunks, key=lambda chunk: chunk.chunk_index)

    def get_all_chunks(self) -> list[Chunk]:
        """Load every stored Chunk in deterministic BM25 corpus order."""
        self._ensure_open()
        result = self._collection.get(include=["documents", "metadatas"])
        chunks = self._parse_stored_chunks(result)
        return sorted(
            chunks,
            key=lambda chunk: (
                chunk.document_id,
                chunk.chunk_index,
                chunk.chunk_id,
            ),
        )

    def contains_document(self, document_id: str) -> bool:
        """Return whether at least one chunk exists for a document."""
        self._ensure_open()
        if not isinstance(document_id, str) or not document_id.strip():
            raise VectorStoreInputError("document_id must be a non-empty string")
        result = self._collection.get(
            where={"document_id": document_id},
            limit=1,
            include=[],
        )
        return bool(result["ids"])

    def close(self) -> None:
        """Release an internally-created Chroma client and database handles."""
        if self._closed:
            return
        if self._owns_client:
            close_client = getattr(self._client, "close", None)
            if callable(close_client):
                close_client()
        self._closed = True

    def __enter__(self) -> ChromaVectorStore:
        """Return this open store as a context manager."""
        self._ensure_open()
        return self

    def __exit__(self, *_: object) -> None:
        """Close the store when leaving its context."""
        self.close()

    def _ensure_open(self) -> None:
        """Reject operations after the store has been closed."""
        if self._closed:
            raise VectorStoreConfigurationError("Chroma vector store is closed")

    def _validate_embeddings(self, embeddings: Sequence[Sequence[float]]) -> None:
        """Validate non-empty numeric vectors with consistent dimensions."""
        expected_dimension: int | None = None
        for index, embedding in enumerate(embeddings):
            if (
                not isinstance(embedding, Sequence)
                or isinstance(embedding, (str, bytes))
                or not embedding
            ):
                raise VectorStoreInputError(
                    f"Embedding at index {index} must be a non-empty sequence"
                )
            if not all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in embedding
            ):
                raise VectorStoreInputError(
                    f"Embedding at index {index} contains a non-numeric value"
                )
            if expected_dimension is None:
                expected_dimension = len(embedding)
            elif len(embedding) != expected_dimension:
                raise VectorStoreInputError(
                    "All embeddings in one operation must have the same dimension"
                )

    def _parse_query_result(self, result: Mapping[str, Any]) -> list[VectorQueryResult]:
        """Validate Chroma's nested single-query response."""
        ids = self._first_result_list(result, "ids")
        documents = self._first_result_list(result, "documents")
        metadatas = self._first_result_list(result, "metadatas")
        distances = self._first_result_list(result, "distances")
        lengths = {len(ids), len(documents), len(metadatas), len(distances)}
        if len(lengths) != 1:
            raise VectorStoreResponseError(
                "Chroma query returned inconsistent result lengths"
            )

        parsed: list[VectorQueryResult] = []
        for chunk_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=True
        ):
            if not isinstance(chunk_id, str) or not isinstance(document, str):
                raise VectorStoreResponseError(
                    "Chroma query returned an invalid ID or document"
                )
            if not isinstance(metadata, Mapping):
                raise VectorStoreResponseError(
                    "Chroma query returned invalid metadata"
                )
            if not isinstance(distance, (int, float)) or isinstance(distance, bool):
                raise VectorStoreResponseError(
                    "Chroma query returned an invalid distance"
                )
            parsed.append(
                VectorQueryResult(
                    chunk_id=chunk_id,
                    text=document,
                    metadata=deserialize_chunk_metadata(metadata),
                    distance=float(distance),
                )
            )
        return parsed

    def _parse_stored_chunks(self, result: Mapping[str, Any]) -> list[Chunk]:
        """Reconstruct Chunk models from a Chroma get response."""
        ids = result.get("ids")
        documents = result.get("documents")
        metadatas = result.get("metadatas")
        if not isinstance(ids, list) or not isinstance(documents, list):
            raise VectorStoreResponseError("Chroma get returned invalid chunk data")
        if not isinstance(metadatas, list):
            raise VectorStoreResponseError("Chroma get returned invalid metadata")
        if len({len(ids), len(documents), len(metadatas)}) != 1:
            raise VectorStoreResponseError(
                "Chroma get returned inconsistent result lengths"
            )

        chunks: list[Chunk] = []
        for chunk_id, document, metadata in zip(
            ids, documents, metadatas, strict=True
        ):
            if not isinstance(chunk_id, str) or not isinstance(document, str):
                raise VectorStoreResponseError(
                    "Chroma get returned an invalid ID or document"
                )
            if not isinstance(metadata, Mapping):
                raise VectorStoreResponseError("Chroma get returned invalid metadata")
            restored = deserialize_chunk_metadata(metadata)
            try:
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        document_id=restored["document_id"],
                        text=document,
                        chunk_index=restored["chunk_index"],
                        source=restored["source"],
                        source_type=restored["source_type"],
                        page=restored["page"],
                        section=restored["section"],
                        heading_path=restored["heading_path"],
                        chunk_strategy=restored["chunk_strategy"],
                        content_hash=restored["content_hash"],
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise VectorStoreResponseError(
                    "Stored Chroma metadata cannot reconstruct a Chunk"
                ) from exc
        return chunks

    @staticmethod
    def _first_result_list(result: Mapping[str, Any], key: str) -> list[Any]:
        """Extract the first list from a single-query nested result field."""
        nested = result.get(key)
        if not isinstance(nested, list) or not nested:
            raise VectorStoreResponseError(
                f"Chroma query returned invalid {key} data"
            )
        first = nested[0]
        if not isinstance(first, list):
            raise VectorStoreResponseError(
                f"Chroma query returned invalid {key} data"
            )
        return first
