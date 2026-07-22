"""Integration tests for the persistent Chroma vector store adapter."""

from pathlib import Path

import httpx
import pytest

from src.rag.schemas import Chunk
from src.rag.vectorstore import (
    ChromaVectorStore,
    VectorStoreInputError,
    VectorStoreUnavailableError,
)


def _chunk(
    index: int,
    *,
    document_id: str = "doc-1",
    text: str | None = None,
    page: int | None = None,
    heading_path: list[str] | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=f"{document_id}-chunk-{index}",
        document_id=document_id,
        text=text or f"Chunk {index}",
        chunk_index=index,
        source="manual.pdf" if page is not None else "guide.md",
        source_type="pdf" if page is not None else "markdown",
        page=page,
        section="Overview" if heading_path else None,
        heading_path=heading_path or [],
        chunk_strategy="recursive",
        content_hash=f"hash-{index}",
    )


def _store(path: Path) -> ChromaVectorStore:
    return ChromaVectorStore(
        persist_dir=path,
        collection_name="test_chunks",
    )


def test_batch_upsert_and_count(tmp_path: Path) -> None:
    with _store(tmp_path / "chroma") as store:
        store.upsert_chunks(
            [_chunk(0), _chunk(1), _chunk(2)],
            [[1.0, 0.0], [0.8, 0.2], [0.0, 1.0]],
        )

        assert store.count() == 3


def test_get_all_chunks_returns_deterministic_complete_corpus(
    tmp_path: Path,
) -> None:
    with _store(tmp_path / "chroma") as store:
        chunks = [
            _chunk(1, document_id="doc-b"),
            _chunk(1, document_id="doc-a"),
            _chunk(0, document_id="doc-a"),
        ]
        store.upsert_chunks(chunks, [[1.0, 0.0]] * len(chunks))

        restored = store.get_all_chunks()

        assert [chunk.chunk_id for chunk in restored] == [
            "doc-a-chunk-0",
            "doc-a-chunk-1",
            "doc-b-chunk-1",
        ]


def test_collection_uses_cosine_distance(tmp_path: Path) -> None:
    with _store(tmp_path / "chroma") as store:
        assert store._collection.configuration["hnsw"]["space"] == "cosine"


def test_vector_query_returns_nearest_result_and_distance(tmp_path: Path) -> None:
    with _store(tmp_path / "chroma") as store:
        store.upsert_chunks(
            [_chunk(0, text="Dense retrieval"), _chunk(1, text="PDF parser")],
            [[1.0, 0.0], [0.0, 1.0]],
        )

        results = store.query_by_vector([1.0, 0.0], top_k=1)

        assert len(results) == 1
        assert results[0].chunk_id == "doc-1-chunk-0"
        assert results[0].text == "Dense retrieval"
        assert results[0].distance == pytest.approx(0.0)


def test_top_k_limits_query_results(tmp_path: Path) -> None:
    with _store(tmp_path / "chroma") as store:
        store.upsert_chunks(
            [_chunk(0), _chunk(1), _chunk(2)],
            [[1.0, 0.0], [0.8, 0.2], [0.0, 1.0]],
        )

        assert len(store.query_by_vector([1.0, 0.0], top_k=2)) == 2


def test_get_chunks_by_document_id_and_contains_document(tmp_path: Path) -> None:
    with _store(tmp_path / "chroma") as store:
        store.upsert_chunks(
            [_chunk(1), _chunk(0), _chunk(0, document_id="doc-2")],
            [[0.8, 0.2], [1.0, 0.0], [0.0, 1.0]],
        )

        chunks = store.get_chunks_by_document_id("doc-1")

        assert [chunk.chunk_index for chunk in chunks] == [0, 1]
        assert store.contains_document("doc-1") is True
        assert store.contains_document("missing") is False


def test_repeated_upsert_is_idempotent_and_updates_content(tmp_path: Path) -> None:
    with _store(tmp_path / "chroma") as store:
        original = _chunk(0, text="Original")
        updated = original.model_copy(
            update={"text": "Updated", "content_hash": "updated-hash"}
        )

        store.upsert_chunks([original], [[1.0, 0.0]])
        store.upsert_chunks([updated], [[0.9, 0.1]])

        assert store.count() == 1
        restored = store.get_chunks_by_document_id("doc-1")
        assert restored[0].text == "Updated"
        assert restored[0].content_hash == "updated-hash"


def test_metadata_is_serialized_and_restored(tmp_path: Path) -> None:
    with _store(tmp_path / "chroma") as store:
        chunk = _chunk(
            0,
            page=3,
            heading_path=["指南", "安装"],
        )
        store.upsert_chunks([chunk], [[1.0, 0.0]])

        restored = store.get_chunks_by_document_id("doc-1")[0]
        query_result = store.query_by_vector([1.0, 0.0], top_k=1)[0]

        assert restored == chunk
        assert query_result.metadata["heading_path"] == ["指南", "安装"]
        assert query_result.metadata["page"] == 3
        assert query_result.metadata["section"] == "Overview"


def test_new_instance_reads_persisted_data(tmp_path: Path) -> None:
    persist_dir = tmp_path / "persistent-chroma"
    first = _store(persist_dir)
    first.upsert_chunks([_chunk(0)], [[1.0, 0.0]])
    first.close()

    second = _store(persist_dir)
    try:
        assert second.count() == 1
        assert second.contains_document("doc-1") is True
        assert second.get_chunks_by_document_id("doc-1")[0] == _chunk(0)
    finally:
        second.close()


def test_chunk_embedding_count_mismatch_is_rejected(tmp_path: Path) -> None:
    with _store(tmp_path / "chroma") as store:
        with pytest.raises(VectorStoreInputError, match="count"):
            store.upsert_chunks([_chunk(0), _chunk(1)], [[1.0, 0.0]])

        assert store.count() == 0


def test_empty_upsert_and_empty_query_collection_are_safe(tmp_path: Path) -> None:
    with _store(tmp_path / "chroma") as store:
        store.upsert_chunks([], [])

        assert store.count() == 0
        assert store.query_by_vector([1.0, 0.0], top_k=5) == []


@pytest.mark.parametrize("top_k", [0, -1, 1.5, True])
def test_invalid_top_k_is_rejected(tmp_path: Path, top_k: int) -> None:
    with _store(tmp_path / "chroma") as store:
        with pytest.raises(VectorStoreInputError, match="top_k"):
            store.query_by_vector(  # type: ignore[arg-type]
                [1.0, 0.0], top_k=top_k
            )


def test_transport_failure_is_converted_to_safe_vector_store_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "private-provider-response"
    with _store(tmp_path / "chroma") as store:
        def failed_count() -> int:
            raise httpx.ConnectError(secret)

        monkeypatch.setattr(store, "count", failed_count)
        with pytest.raises(VectorStoreUnavailableError) as raised:
            store.query_by_vector([1.0, 0.0], top_k=1)

    assert raised.value.code == "vector_store_unavailable"
    assert raised.value.path == "vector_store"
    assert raised.value.recoverable is True
    assert secret not in raised.value.safe_message
