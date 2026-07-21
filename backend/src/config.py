"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings for embedding and vector storage services."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_api_key: str | None = None
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = Field(default=1024, gt=0)
    embedding_batch_size: int = Field(default=32, gt=0)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0)

    chroma_persist_dir: Path = Path("./data/chroma")
    chroma_collection: str = "technical_docs"

