"""Acceptance checks for the small built-in Day 2 knowledge corpus."""

from __future__ import annotations

import json
from pathlib import Path

from src.rag.chunking import ChunkerFactory
from src.rag.parsers import ParserFactory


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"


def _documents() -> list[Path]:
    return sorted((KNOWLEDGE_ROOT / "markdown").glob("*.md")) + sorted(
        (KNOWLEDGE_ROOT / "pdf").glob("*.pdf")
    )


def test_builtin_corpus_contains_exactly_five_parseable_documents() -> None:
    documents = _documents()

    assert len(documents) == 5
    assert len(list((KNOWLEDGE_ROOT / "markdown").glob("*.md"))) == 3
    assert len(list((KNOWLEDGE_ROOT / "pdf").glob("*.pdf"))) == 2
    assert all(ParserFactory.get_parser(path).parse(path).pages for path in documents)


def test_builtin_pdfs_are_multi_page_and_retain_page_numbers() -> None:
    for path in sorted((KNOWLEDGE_ROOT / "pdf").glob("*.pdf")):
        document = ParserFactory.get_parser(path).parse(path)

        assert document.metadata["total_pages"] >= 2
        assert len(document.pages) >= 2
        assert [page.page_number for page in document.pages] == list(
            range(1, len(document.pages) + 1)
        )


def test_each_document_has_two_well_formed_acceptance_questions() -> None:
    question_path = KNOWLEDGE_ROOT / "day2_questions.jsonl"
    questions = [
        json.loads(line)
        for line in question_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    document_names = {path.name for path in _documents()}

    assert len(questions) == 10
    assert {item["document"] for item in questions} == document_names
    for document_name in document_names:
        assert sum(item["document"] == document_name for item in questions) == 2
    assert all(item["question"].strip() for item in questions)
    assert all(item["expected_terms"] for item in questions)
    assert all(item["expected_location"].strip() for item in questions)


def test_optimized_chunks_expose_locations_for_every_document() -> None:
    for path in _documents():
        document = ParserFactory.get_parser(path).parse(path)
        strategy = (
            "markdown_heading" if document.source_type == "markdown"
            else "pdf_page_aware"
        )
        chunks = ChunkerFactory.create(
            strategy,
            source_type=document.source_type,
            chunk_size=350,
            chunk_overlap=40,
        ).chunk(document)

        assert chunks
        if document.source_type == "markdown":
            assert all(chunk.section and chunk.heading_path for chunk in chunks)
        else:
            assert all(chunk.page is not None for chunk in chunks)
