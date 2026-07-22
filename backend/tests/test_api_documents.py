"""Offline API tests for document ingestion, batch loading, and statistics."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.config import Settings
from src.rag.embeddings import EmbeddingRequestError
from src.rag.runtime import RetrievalRuntime, build_retrieval_runtime
from src.rag.vectorstore import ChromaVectorStore, VectorStoreResponseError
from tests.fakes import FakeEmbeddingClient


def _pdf_bytes(page_texts: list[str]) -> bytes:
    document = pymupdf.open()
    try:
        for text in page_texts:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        return document.tobytes()
    finally:
        document.close()


@contextmanager
def _client(
    tmp_path: Path,
    *,
    embedder: FakeEmbeddingClient | None = None,
    knowledge_root: Path | None = None,
    upload_max_bytes: int = 1024 * 1024,
) -> Iterator[tuple[TestClient, RetrievalRuntime, ChromaVectorStore, Path]]:
    temp_root = tmp_path / "upload-temp"
    settings = Settings(
        _env_file=None,
        llm_api_key="offline-llm-key",
        embedding_api_key="offline-embedding-key",
        reranker_enabled=False,
        langfuse_enabled=False,
        knowledge_base_id="technical_docs",
        knowledge_root=knowledge_root or tmp_path / "knowledge",
        upload_max_bytes=upload_max_bytes,
        upload_temp_dir=temp_root,
    )
    store = ChromaVectorStore(
        persist_dir=tmp_path / "chroma",
        collection_name="documents_api_tests",
    )
    runtime = build_retrieval_runtime(
        embedder or FakeEmbeddingClient(),
        settings=settings,
        vector_store=store,
    )
    app = create_app(settings, runtime_factory=lambda configured: runtime)
    try:
        with TestClient(app) as client:
            yield client, runtime, store, temp_root
    finally:
        store.close()


def _upload(
    client: TestClient,
    filename: str,
    content: bytes,
    *,
    content_type: str = "application/octet-stream",
    strategy: str = "recursive",
    knowledge_base_id: str = "technical_docs",
):
    return client.post(
        "/api/documents/upload",
        files={"file": (filename, content, content_type)},
        data={
            "knowledge_base_id": knowledge_base_id,
            "chunk_strategy": strategy,
        },
    )


def test_markdown_upload_is_immediately_searchable(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, runtime, store, _):
        response = _upload(
            client,
            "guide.md",
            b"# Retrieval\n\nimmediate_unique_keyword",
            content_type="text/markdown",
            strategy="markdown_heading",
        )
        hits = runtime.retriever.retrieve("immediate_unique_keyword")

        assert response.status_code == 200
        assert response.json()["status"] == "done"
        assert response.json()["chunks_count"] == 1
        assert hits and hits[0].metadata["document_id"] == response.json()["document_id"]
        assert runtime.get_index_status().chunk_count == store.count() == 1


def test_pdf_upload_preserves_page_sources(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _, store, _):
        response = _upload(
            client,
            "manual.pdf",
            _pdf_bytes(["First source page", "Second source page"]),
            content_type="application/pdf",
            strategy="pdf_page_aware",
        )
        chunks = store.get_chunks_by_document_id(response.json()["document_id"])

        assert response.status_code == 200
        assert response.json()["status"] == "done"
        assert [chunk.page for chunk in chunks] == [1, 2]
        assert all(chunk.source == "manual.pdf" for chunk in chunks)


def test_concurrent_uploads_leave_stats_and_indexes_consistent(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as (client, runtime, store, _):
        payloads = [
            ("first.md", b"first_concurrent_term"),
            ("second.md", b"second_concurrent_term"),
        ]
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda item: _upload(client, item[0], item[1]),
                    payloads,
                )
            )
        stats = client.get("/api/documents/stats")

        assert all(response.status_code == 200 for response in responses)
        assert all(response.json()["status"] == "done" for response in responses)
        assert stats.status_code == 200
        assert stats.json()["documents_count"] == 2
        assert stats.json()["chunks_count"] == store.count() == 2
        assert stats.json()["bm25"]["chunk_count"] == 2
        assert runtime.get_index_status().needs_rebuild is False


@pytest.mark.parametrize(
    ("filename", "content", "max_bytes", "status_code", "error_code"),
    [
        ("empty.md", b"", 1024, 400, "empty_file"),
        ("notes.txt", b"text", 1024, 415, "unsupported_file_type"),
        ("large.md", b"12345", 4, 413, "file_too_large"),
    ],
)
def test_upload_validation_errors_are_stable(
    tmp_path: Path,
    filename: str,
    content: bytes,
    max_bytes: int,
    status_code: int,
    error_code: str,
) -> None:
    with _client(tmp_path, upload_max_bytes=max_bytes) as (client, _, _, _):
        response = _upload(client, filename, content)

        assert response.status_code == status_code
        assert response.json()["error"]["code"] == error_code
        assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_pdf_without_text_returns_safe_error(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _, _, _):
        response = _upload(
            client,
            "scanned.pdf",
            _pdf_bytes([""]),
            content_type="application/pdf",
            strategy="pdf_page_aware",
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "document_no_text"
        assert str(tmp_path) not in response.text


def test_filename_is_sanitized_and_temporary_files_are_removed(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as (client, _, store, temp_root):
        response = _upload(client, "../../unsafe.md", b"safe content")
        chunks = store.get_chunks_by_document_id(response.json()["document_id"])

        assert response.status_code == 200
        assert response.json()["filename"] == "unsafe.md"
        assert all(chunk.source == "unsafe.md" for chunk in chunks)
        assert temp_root.is_dir()
        assert list(temp_root.iterdir()) == []


def test_repeated_upload_is_idempotently_skipped(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _, store, _):
        first = _upload(client, "stable.md", b"stable repeated content")
        count_after_first = store.count()
        second = _upload(client, "stable.md", b"stable repeated content")

        assert first.json()["duplicate"] is False
        assert second.status_code == 200
        assert second.json()["status"] == "done"
        assert second.json()["duplicate"] is True
        assert second.json()["document_id"] == first.json()["document_id"]
        assert store.count() == count_after_first


def test_load_default_is_idempotent(tmp_path: Path) -> None:
    knowledge_root = tmp_path / "built-in"
    (knowledge_root / "markdown").mkdir(parents=True)
    (knowledge_root / "pdf").mkdir()
    (knowledge_root / "markdown" / "guide.md").write_text(
        "# Guide\n\nBuilt-in markdown.", encoding="utf-8"
    )
    (knowledge_root / "pdf" / "manual.pdf").write_bytes(
        _pdf_bytes(["Built-in PDF"])
    )

    with _client(tmp_path, knowledge_root=knowledge_root) as (client, _, store, _):
        first = client.post("/api/documents/load-default")
        first_count = store.count()
        second = client.post("/api/documents/load-default")
        stats = client.get("/api/documents/stats")

        assert first.status_code == 200
        assert first.json()["status"] == "done"
        assert first.json()["processed"] == 2
        assert first.json()["skipped"] == 0
        assert second.json()["status"] == "done"
        assert second.json()["processed"] == 0
        assert second.json()["skipped"] == 2
        assert store.count() == first_count
        assert stats.json()["documents_count"] == 2


def test_load_default_reports_partial_failure(tmp_path: Path) -> None:
    knowledge_root = tmp_path / "partial"
    (knowledge_root / "markdown").mkdir(parents=True)
    (knowledge_root / "markdown" / "good.md").write_text(
        "# Good\n\nSearchable.", encoding="utf-8"
    )
    (knowledge_root / "markdown" / "empty.md").write_bytes(b"")

    with _client(tmp_path, knowledge_root=knowledge_root) as (client, _, _, _):
        response = client.post("/api/documents/load-default")

        assert response.status_code == 200
        assert response.json()["status"] == "degraded"
        assert response.json()["processed"] == 1
        assert response.json()["failed"] == 1
        failed = next(item for item in response.json()["items"] if item["status"] == "failed")
        assert failed["filename"] == "empty.md"
        assert failed["error_code"] == "empty_file"


def test_missing_default_directory_is_explicit(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with _client(tmp_path, knowledge_root=missing) as (client, _, _, _):
        response = client.post("/api/documents/load-default")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "knowledge_directory_missing"
        assert str(missing) not in response.text


def test_bm25_publish_failure_returns_degraded_not_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(tmp_path) as (client, runtime, store, _):
        def fail_rebuild(chunks: Any) -> None:
            raise RuntimeError("synthetic BM25 failure")

        monkeypatch.setattr(runtime.bm25_index, "rebuild", fail_rebuild)
        response = _upload(client, "degraded.md", b"persisted dense content")

        assert response.status_code == 200
        assert response.json()["status"] == "degraded"
        assert response.json()["error_code"] == "bm25_rebuild_failed"
        assert store.count() == 1
        assert runtime.get_index_status().needs_rebuild is True


def test_embedding_and_vector_failures_use_safe_error_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedder = FakeEmbeddingClient(
        document_error=EmbeddingRequestError("secret provider response")
    )
    with _client(tmp_path / "embedding", embedder=embedder) as (client, _, _, _):
        embedding = _upload(client, "embedding.md", b"content")
        assert embedding.status_code == 502
        assert embedding.json()["error"]["code"] == "embedding_failed"
        assert "secret provider response" not in embedding.text

    with _client(tmp_path / "vector") as (client, _, store, _):
        def fail_upsert(chunks: Any, embeddings: Any) -> None:
            raise VectorStoreResponseError("secret chroma location")

        monkeypatch.setattr(store, "upsert_chunks", fail_upsert)
        vector = _upload(client, "vector.md", b"content")
        assert vector.status_code == 503
        assert vector.json()["error"]["code"] == "vector_store_failed"
        assert "secret chroma location" not in vector.text


def test_invalid_knowledge_base_and_strategy_are_rejected(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _, _, _):
        knowledge = _upload(
            client,
            "guide.md",
            b"content",
            knowledge_base_id="another-tenant",
        )
        strategy = _upload(
            client,
            "guide.md",
            b"content",
            strategy="pdf_page_aware",
        )

        assert knowledge.status_code == 400
        assert knowledge.json()["error"]["code"] == "invalid_knowledge_base"
        assert strategy.status_code == 400
        assert strategy.json()["error"]["code"] == "incompatible_chunk_strategy"
