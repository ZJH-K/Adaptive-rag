"""Deterministic tokenization for Chinese and technical document text."""

from __future__ import annotations

import re
from typing import Protocol

import jieba


_TEXT_SEGMENT_PATTERN = re.compile(
    r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*|[\u3400-\u4dbf\u4e00-\u9fff]+"
)
_TECHNICAL_TOKEN_PATTERN = re.compile(
    r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*\Z"
)


class Tokenizer(Protocol):
    """Tokenization capability shared by BM25 indexing and querying."""

    def tokenize(self, text: str) -> list[str]:
        """Return normalized, non-empty tokens in source order."""
        ...


class JiebaTokenizer:
    """Segment Chinese with jieba while preserving common technical tokens."""

    def __init__(self, engine: jieba.Tokenizer | None = None) -> None:
        """Use an isolated jieba engine unless one is explicitly injected."""
        self._engine = engine or jieba.Tokenizer()

    def tokenize(self, text: str) -> list[str]:
        """Lowercase text and discard whitespace and punctuation-only tokens."""
        if not isinstance(text, str):
            raise TypeError("Tokenizer input must be a string")
        if not text.strip():
            return []

        tokens: list[str] = []
        for match in _TEXT_SEGMENT_PATTERN.finditer(text):
            segment = match.group(0)
            if _TECHNICAL_TOKEN_PATTERN.fullmatch(segment):
                tokens.append(segment.casefold())
                continue
            tokens.extend(
                token.casefold()
                for token in self._engine.cut(segment, cut_all=False)
                if token.strip()
            )
        return tokens
