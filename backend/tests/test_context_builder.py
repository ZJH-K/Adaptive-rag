"""Tests for bounded context construction and citation formatting."""

import pytest

from src.rag.context_builder import (
    ContextBuilder,
    ContextBuilderConfigurationError,
)
from src.rag.schemas import SearchHit


def _hit(
    chunk_id: str,
    text: str,
    *,
    source: str = "guide.md",
    source_type: str = "markdown",
    content_hash: str | None = None,
    page: int | None = None,
    section: str | None = None,
    heading_path: list[str] | None = None,
) -> SearchHit:
    metadata: dict[str, object] = {
        "source": source,
        "source_type": source_type,
    }
    if content_hash is not None:
        metadata["content_hash"] = content_hash
    if page is not None:
        metadata["page"] = page
    if section is not None:
        metadata["section"] = section
    if heading_path is not None:
        metadata["heading_path"] = heading_path
    return SearchHit(chunk_id=chunk_id, text=text, metadata=metadata)


def test_multiple_hits_become_numbered_context_in_retrieval_order() -> None:
    result = ContextBuilder(max_chars=500).build(
        [
            _hit("chunk-2", "Second-ranked identifier, first input."),
            _hit("chunk-1", "First identifier, second input."),
        ]
    )

    assert result.context.startswith("[S1] guide.md")
    assert "[S2] guide.md" in result.context
    assert result.context.index("Second-ranked") < result.context.index(
        "First identifier"
    )
    assert result.used_chunk_ids == ["chunk-2", "chunk-1"]


def test_pdf_source_contains_page_and_chunk_id() -> None:
    result = ContextBuilder().build(
        [
            _hit(
                "pdf-chunk",
                "Checkpoint details.",
                source="manual.pdf",
                source_type="pdf",
                page=7,
            )
        ]
    )

    source = result.sources[0]
    assert source.chunk_id == "pdf-chunk"
    assert source.source == "manual.pdf"
    assert source.source_type == "pdf"
    assert source.page == 7
    assert source.citation == "manual.pdf | page 7"
    assert "[S1] manual.pdf | page 7" in result.context


def test_markdown_source_contains_section_and_heading_path() -> None:
    result = ContextBuilder().build(
        [
            _hit(
                "markdown-chunk",
                "Python version details.",
                section="Python Version",
                heading_path=["Install", "Environment", "Python Version"],
            )
        ]
    )

    source = result.sources[0]
    assert source.section == "Python Version"
    assert source.heading_path == ["Install", "Environment", "Python Version"]
    assert source.citation == "guide.md | section Python Version"


def test_heading_path_is_used_when_markdown_section_is_missing() -> None:
    result = ContextBuilder().build(
        [_hit("chunk-1", "Body.", heading_path=["Install", "Verify"])]
    )

    assert result.sources[0].citation == "guide.md | section Install > Verify"


def test_duplicate_chunk_ids_and_content_hashes_are_removed() -> None:
    result = ContextBuilder().build(
        [
            _hit("chunk-1", "Original.", content_hash="same-content"),
            _hit("chunk-1", "Repeated ID.", content_hash="other-content"),
            _hit("chunk-2", "Repeated content.", content_hash="same-content"),
            _hit("chunk-3", "Unique.", content_hash="unique-content"),
        ]
    )

    assert result.used_chunk_ids == ["chunk-1", "chunk-3"]
    assert "Repeated ID" not in result.context
    assert "Repeated content" not in result.context
    assert [source.citation_id for source in result.sources] == ["S1", "S2"]
    assert [source.chunk_id for source in result.sources] == [
        "chunk-1",
        "chunk-3",
    ]
    assert "[S2]" in result.context
    assert "Unique." in result.context


def test_budget_truncates_in_order_and_never_exceeds_limit() -> None:
    hits = [
        _hit("chunk-1", "A" * 20),
        _hit("chunk-2", "B" * 100),
        _hit("chunk-3", "C" * 20),
    ]

    result = ContextBuilder(max_chars=75).build(hits)

    assert len(result.context) <= 75
    assert result.used_chunk_ids == ["chunk-1", "chunk-2"]
    assert [source.chunk_id for source in result.sources] == [
        "chunk-1",
        "chunk-2",
    ]
    assert "A" * 20 in result.context
    assert "B" in result.context
    assert "C" not in result.context


def test_single_oversized_chunk_is_partially_retained() -> None:
    result = ContextBuilder(max_chars=40).build(
        [_hit("long", "0123456789" * 10)]
    )

    assert len(result.context) == 40
    assert result.used_chunk_ids == ["long"]
    assert result.context.startswith("[S1] guide.md\n0123")


def test_missing_location_metadata_degrades_to_source_only() -> None:
    result = ContextBuilder().build(
        [SearchHit(chunk_id="minimal", text="Minimal body.", metadata={})]
    )

    source = result.sources[0]
    assert source.source == "unknown_source"
    assert source.source_type is None
    assert source.page is None
    assert source.section is None
    assert source.heading_path == []
    assert source.citation == "unknown_source"


def test_empty_hits_return_stable_empty_result() -> None:
    result = ContextBuilder().build([])

    assert result.context == ""
    assert result.sources == []
    assert result.used_chunk_ids == []


def test_sources_and_used_ids_stay_aligned() -> None:
    result = ContextBuilder().build(
        [_hit("a", "Alpha."), _hit("b", "Beta."), _hit("c", "Gamma.")]
    )

    assert [source.chunk_id for source in result.sources] == result.used_chunk_ids
    assert [source.citation_id for source in result.sources] == [
        "S1",
        "S2",
        "S3",
    ]


def test_context_result_serializes_the_complete_citation_mapping() -> None:
    result = ContextBuilder().build(
        [
            _hit(
                "pdf-7",
                "Serialized source.",
                source="manual.pdf",
                source_type="pdf",
                page=7,
            )
        ]
    )

    payload = result.model_dump(mode="json")

    assert payload == {
        "context": "[S1] manual.pdf | page 7\nSerialized source.",
        "sources": [
            {
                "citation_id": "S1",
                "citation": "manual.pdf | page 7",
                "chunk_id": "pdf-7",
                "source": "manual.pdf",
                "source_type": "pdf",
                "page": 7,
                "section": None,
                "heading_path": [],
            }
        ],
        "used_chunk_ids": ["pdf-7"],
    }


@pytest.mark.parametrize("max_chars", [0, -1, 1.5, True])
def test_invalid_context_budget_is_rejected(max_chars: int) -> None:
    with pytest.raises(ContextBuilderConfigurationError, match="max_chars"):
        ContextBuilder(max_chars=max_chars)  # type: ignore[arg-type]
