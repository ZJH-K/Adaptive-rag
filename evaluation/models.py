"""Pydantic contracts for source annotations and resolved evaluation rows."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


EvaluationCategory = Literal[
    "fact",
    "procedure",
    "identifier",
    "comparison",
    "multi_chunk",
    "citation",
]


class EvidenceReference(BaseModel):
    """A human-selected passage and its location in one knowledge document."""

    source: str = Field(min_length=1)
    quote: str = Field(min_length=8)
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    heading_path: list[str] = Field(default_factory=list)

    @field_validator("source", "quote", "section")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("text fields must not be blank")
        return stripped

    @field_validator("heading_path")
    @classmethod
    def _validate_heading_path(cls, value: list[str]) -> list[str]:
        cleaned = [heading.strip() for heading in value]
        if any(not heading for heading in cleaned):
            raise ValueError("heading_path entries must not be blank")
        return cleaned

    @model_validator(mode="after")
    def _require_source_location(self) -> "EvidenceReference":
        suffix = self.source.lower().rsplit(".", maxsplit=1)[-1]
        if suffix == "pdf" and self.page is None:
            raise ValueError("PDF evidence requires a one-based page")
        if suffix in {"md", "markdown"} and not self.heading_path:
            raise ValueError("Markdown evidence requires heading_path")
        if suffix in {"md", "markdown"} and self.section is None:
            raise ValueError("Markdown evidence requires section")
        return self


class EvaluationAnnotation(BaseModel):
    """Human-authored question, answer cues, and evidence rationale."""

    id: str = Field(pattern=r"^q\d{3}$")
    question: str = Field(min_length=5)
    expected_answer_keywords: list[str] = Field(min_length=1)
    source: str = Field(min_length=1)
    category: EvaluationCategory
    evidence: list[EvidenceReference] = Field(min_length=1)
    annotation_rationale: str = Field(min_length=12)
    tests_structured_chunking: bool = False

    @field_validator("question", "source", "annotation_rationale")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text fields must not be blank")
        return stripped

    @field_validator("expected_answer_keywords")
    @classmethod
    def _validate_keywords(cls, value: list[str]) -> list[str]:
        cleaned = [keyword.strip() for keyword in value]
        if any(not keyword for keyword in cleaned):
            raise ValueError("expected_answer_keywords must not contain blanks")
        normalized = [keyword.casefold() for keyword in cleaned]
        if len(normalized) != len(set(normalized)):
            raise ValueError("expected_answer_keywords must be unique")
        return cleaned

    @model_validator(mode="after")
    def _require_consistent_sources(self) -> "EvaluationAnnotation":
        mismatches = [item.source for item in self.evidence if item.source != self.source]
        if mismatches:
            raise ValueError("all evidence sources must equal the sample source")
        return self


class ResolvedEvaluationSample(EvaluationAnnotation):
    """Evaluation annotation with deterministic chunk IDs for each strategy."""

    relevant_chunk_ids: list[str] = Field(min_length=1)
    relevant_chunk_ids_by_strategy: dict[str, list[str]] = Field(min_length=2)

    @field_validator("relevant_chunk_ids")
    @classmethod
    def _validate_chunk_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("relevant_chunk_ids must be unique")
        return value

    @field_validator("relevant_chunk_ids_by_strategy")
    @classmethod
    def _validate_strategy_ids(
        cls, value: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        for strategy, chunk_ids in value.items():
            if not strategy.strip() or not chunk_ids:
                raise ValueError("each strategy requires at least one chunk ID")
            if len(chunk_ids) != len(set(chunk_ids)):
                raise ValueError(f"chunk IDs for strategy '{strategy}' must be unique")
        return value

