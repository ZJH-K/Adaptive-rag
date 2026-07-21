"""Exceptions raised by document parsers."""


class DocumentParseError(ValueError):
    """Raised when a supported document cannot be parsed into text."""


class UnsupportedDocumentTypeError(DocumentParseError):
    """Raised when no parser is registered for a file extension."""

