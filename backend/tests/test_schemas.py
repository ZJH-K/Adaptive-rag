"""Tests for shared RAG data contracts."""

import pytest
from pydantic import ValidationError

from src.rag.schemas import Chunk, ParsedDocument, ParsedPage, SearchHit


def test_schema_models_can_be_created() -> None:
    page = ParsedPage(text="Introduction", page_number=1)
    document = ParsedDocument(
        document_id="doc-1",
        filename="guide.pdf",
        source_type="pdf",
        pages=[page],
    )
    chunk = Chunk(
        chunk_id="chunk-1",
        document_id=document.document_id,
        text=page.text,
        chunk_index=0,
        source=document.filename,
        source_type=document.source_type,
        page=page.page_number,
        chunk_strategy="recursive",
        content_hash="hash-1",
    )
    hit = SearchHit(chunk_id=chunk.chunk_id, text=chunk.text)

    assert document.pages == [page]
    assert chunk.page == 1
    assert chunk.heading_path == []
    assert hit.dense_score is None


def test_mutable_defaults_are_not_shared() -> None:
    first_page = ParsedPage(text="first")
    second_page = ParsedPage(text="second")
    first_page.headings.append("Heading")
    first_page.metadata["language"] = "en"

    first_document = ParsedDocument(
        document_id="doc-1", filename="one.md", source_type="markdown"
    )
    second_document = ParsedDocument(
        document_id="doc-2", filename="two.md", source_type="markdown"
    )
    first_document.pages.append(first_page)
    first_document.metadata["owner"] = "team"

    first_hit = SearchHit(chunk_id="chunk-1", text="first")
    second_hit = SearchHit(chunk_id="chunk-2", text="second")
    first_hit.metadata["rank"] = 1

    assert second_page.headings == []
    assert second_page.metadata == {}
    assert second_document.pages == []
    assert second_document.metadata == {}
    assert second_hit.metadata == {}


def test_source_type_rejects_unsupported_values() -> None:
    with pytest.raises(ValidationError):
        ParsedDocument(
            document_id="doc-1",
            filename="notes.txt",
            source_type="text",  # type: ignore[arg-type]
        )

