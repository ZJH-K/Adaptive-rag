"""Tests for environment-based application configuration."""

from pathlib import Path

from src.config import Settings


def test_settings_use_expected_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.embedding_model == "BAAI/bge-m3"
    assert settings.embedding_dimension == 1024
    assert settings.embedding_api_key is None
    assert settings.chroma_persist_dir == Path("./data/chroma")
    assert settings.chroma_collection == "technical_docs"


def test_environment_variables_override_defaults(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL", "example/custom-embedding")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "768")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "16")
    monkeypatch.setenv("EMBEDDING_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", "./tmp/chroma")
    monkeypatch.setenv("CHROMA_COLLECTION", "test_docs")

    settings = Settings(_env_file=None)

    assert settings.embedding_model == "example/custom-embedding"
    assert settings.embedding_dimension == 768
    assert settings.embedding_batch_size == 16
    assert settings.embedding_timeout_seconds == 12.5
    assert settings.chroma_persist_dir == Path("./tmp/chroma")
    assert settings.chroma_collection == "test_docs"

