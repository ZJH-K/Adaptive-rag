"""Public document retrieval interface."""

from src.rag.retrieval.bm25 import (
    BM25RetrievalConfigurationError,
    BM25RetrievalInputError,
    BM25Retriever,
)
from src.rag.retrieval.bm25_index import BM25Index, DuplicateChunkIDError
from src.rag.retrieval.dense import (
    DenseRetrievalConfigurationError,
    DenseRetrievalInputError,
    DenseRetriever,
    QueryEmbedder,
)
from src.rag.retrieval.fusion import (
    RRFFusionConfigurationError,
    RRFFusionConflictError,
    RRFFusionDuplicateError,
    reciprocal_rank_fusion,
)
from src.rag.retrieval.tokenizer import JiebaTokenizer, Tokenizer
from src.rag.retrieval.pipeline import (
    HybridRetrievalPipeline,
    RankedRetriever,
    RetrievalDiagnostics,
    RetrievalPipelineConfigurationError,
    RetrievalPipelineInputError,
)

__all__ = [
    "BM25Index",
    "BM25RetrievalConfigurationError",
    "BM25RetrievalInputError",
    "BM25Retriever",
    "DenseRetrievalConfigurationError",
    "DenseRetrievalInputError",
    "DenseRetriever",
    "DuplicateChunkIDError",
    "JiebaTokenizer",
    "HybridRetrievalPipeline",
    "QueryEmbedder",
    "RankedRetriever",
    "RetrievalDiagnostics",
    "RetrievalPipelineConfigurationError",
    "RetrievalPipelineInputError",
    "RRFFusionConfigurationError",
    "RRFFusionConflictError",
    "RRFFusionDuplicateError",
    "Tokenizer",
    "reciprocal_rank_fusion",
]
