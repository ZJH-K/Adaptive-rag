"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings for model and vector storage services."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_api_key: str | None = None
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = Field(default=1024, gt=0)
    embedding_batch_size: int = Field(default=32, gt=0)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0)

    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str | None = None
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    llm_json_mode_enabled: bool = True

    reranker_enabled: bool = True
    reranker_base_url: str = "https://api.siliconflow.cn/v1"
    reranker_api_key: str | None = None
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_timeout_seconds: float = Field(default=30.0, gt=0)
    rerank_top_k: int = Field(
        default=5,
        gt=0,
        validation_alias=AliasChoices("RERANK_TOP_K", "RERANKER_TOP_N"),
    )

    hybrid_retrieval_enabled: bool = True
    dense_top_n: int = Field(default=20, gt=0)
    bm25_top_n: int = Field(default=20, gt=0)
    retrieve_top_n: int = Field(
        default=20,
        gt=0,
        validation_alias=AliasChoices("RETRIEVE_TOP_N", "FUSION_TOP_N"),
    )
    rrf_k: int = Field(default=60, gt=0)

    langfuse_enabled: bool = False
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_environment: str = "development"
    langfuse_capture_question: bool = False
    langfuse_capture_answer: bool = False
    langfuse_max_text_chars: int = Field(default=200, gt=0, le=4000)

    chroma_persist_dir: Path = Path("./data/chroma")
    chroma_collection: str = "technical_docs"
