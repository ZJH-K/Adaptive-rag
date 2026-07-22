"""Build bounded LLM context and structured citations from retrieval hits."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.rag.schemas import SearchHit, SourceType


class ContextBuilderConfigurationError(ValueError):
    """Raised when context construction parameters are invalid."""


class ContextSource(BaseModel):
    """A minimal source descriptor aligned with one numbered context block."""

    citation_id: str
    citation: str
    chunk_id: str
    source: str
    source_type: SourceType | None = None
    page: int | None = None
    section: str | None = None
    heading_path: list[str] = Field(default_factory=list)


class ContextBuildResult(BaseModel):
    """Bounded context plus citations in matching retrieval order."""

    context: str
    sources: list[ContextSource] = Field(default_factory=list)
    used_chunk_ids: list[str] = Field(default_factory=list)


class ContextBuilder:
    """Deduplicate ranked hits and format them within a character budget."""

    def __init__(self, max_chars: int = 6000) -> None:
        """Configure the maximum length of the final formatted context."""
        if (
            not isinstance(max_chars, int)
            or isinstance(max_chars, bool)
            or max_chars <= 0
        ):
            raise ContextBuilderConfigurationError(
                "max_chars must be a positive integer"
            )
        self.max_chars = max_chars

    def build(self, hits: list[SearchHit]) -> ContextBuildResult:
        """Build numbered context blocks while preserving retrieval order."""
        blocks: list[str] = []
        sources: list[ContextSource] = []
        used_chunk_ids: list[str] = []
        seen_chunk_ids: set[str] = set()
        seen_content_hashes: set[str] = set()
        current_length = 0

        for hit in hits:
            text = hit.text.strip()
            if not text or self._is_duplicate(
                hit, seen_chunk_ids, seen_content_hashes
            ):
                continue

            citation_id = f"S{len(sources) + 1}"
            source = self._create_source(hit, citation_id)
            header = f"[{citation_id}] {source.citation}\n"
            separator = "\n\n" if blocks else ""
            available = self.max_chars - current_length - len(separator)
            available_text = available - len(header)
            if available_text <= 0:
                break

            selected_text = text[:available_text].rstrip()
            if not selected_text:
                break

            block = f"{header}{selected_text}"
            blocks.append(block)
            sources.append(source)
            used_chunk_ids.append(hit.chunk_id)
            self._mark_seen(hit, seen_chunk_ids, seen_content_hashes)
            current_length += len(separator) + len(block)

            if len(selected_text) < len(text):
                break

        return ContextBuildResult(
            context="\n\n".join(blocks),
            sources=sources,
            used_chunk_ids=used_chunk_ids,
        )

    @staticmethod
    def _is_duplicate(
        hit: SearchHit,
        seen_chunk_ids: set[str],
        seen_content_hashes: set[str],
    ) -> bool:
        """Return whether a hit repeats an included ID or content hash."""
        content_hash = hit.metadata.get("content_hash")
        return hit.chunk_id in seen_chunk_ids or (
            isinstance(content_hash, str)
            and bool(content_hash)
            and content_hash in seen_content_hashes
        )

    @staticmethod
    def _mark_seen(
        hit: SearchHit,
        seen_chunk_ids: set[str],
        seen_content_hashes: set[str],
    ) -> None:
        """Record the stable identifiers of an included retrieval hit."""
        seen_chunk_ids.add(hit.chunk_id)
        content_hash = hit.metadata.get("content_hash")
        if isinstance(content_hash, str) and content_hash:
            seen_content_hashes.add(content_hash)

    def _create_source(self, hit: SearchHit, citation_id: str) -> ContextSource:
        """Extract only citation-relevant fields from retrieval metadata."""
        metadata = hit.metadata
        source_value = metadata.get("source")
        source = (
            source_value.strip()
            if isinstance(source_value, str) and source_value.strip()
            else "unknown_source"
        )
        source_type = self._source_type(metadata.get("source_type"))
        page_value = metadata.get("page")
        page = (
            page_value
            if isinstance(page_value, int) and not isinstance(page_value, bool)
            else None
        )
        section_value = metadata.get("section")
        section = (
            section_value.strip()
            if isinstance(section_value, str) and section_value.strip()
            else None
        )
        heading_path_value = metadata.get("heading_path")
        heading_path = (
            list(heading_path_value)
            if isinstance(heading_path_value, list)
            and all(isinstance(item, str) for item in heading_path_value)
            else []
        )

        location: str | None = None
        if page is not None:
            location = f"page {page}"
        elif section is not None:
            location = f"section {section}"
        elif heading_path:
            location = f"section {' > '.join(heading_path)}"
        citation = source if location is None else f"{source} | {location}"

        return ContextSource(
            citation_id=citation_id,
            citation=citation,
            chunk_id=hit.chunk_id,
            source=source,
            source_type=source_type,
            page=page,
            section=section,
            heading_path=heading_path,
        )

    @staticmethod
    def _source_type(value: object) -> SourceType | None:
        """Return a supported source type without trusting arbitrary metadata."""
        if value == "pdf":
            return "pdf"
        if value == "markdown":
            return "markdown"
        return None
