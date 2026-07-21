"""Shared data contracts for the Adaptive RAG pipeline."""

from typing import Any, Literal

from pydantic import BaseModel, Field


SourceType = Literal["pdf", "markdown"]


class ParsedPage(BaseModel):
    """A logical page or section extracted from a source document."""

    text: str
    page_number: int | None = None
    headings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    """A parsed source document with its structured text units."""

    document_id: str
    filename: str
    source_type: SourceType
    pages: list[ParsedPage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    """A retrievable text unit produced from a parsed document."""

    chunk_id: str
    document_id: str
    text: str
    chunk_index: int
    source: str
    source_type: SourceType
    page: int | None = None
    section: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    chunk_strategy: str
    content_hash: str


class SearchHit(BaseModel):
    """A retrieval result with scores reserved for each ranking stage."""

    chunk_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    dense_score: float | None = None
    bm25_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None

