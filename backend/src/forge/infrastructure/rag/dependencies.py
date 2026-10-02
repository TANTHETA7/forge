"""FastAPI dependency providers for RAG (Phase 7).

Purpose:       Wire the RAG infrastructure — chunk persistence, the filesystem
                source reader, and the embedding/LLM providers — into FastAPI's
                dependency-injection system, mirroring
                `infrastructure/persistence/dependencies.py` and
                `infrastructure/graph/dependencies.py`.
Responsibility: Construction/lifecycle and the provider switch only — no business
                logic. This is the one place that reads `rag_embedding_provider` /
                `rag_llm_provider` and decides whether a request runs against real
                Ollama or the deterministic offline doubles; every consumer above
                only ever sees the `EmbeddingProvider` / `LlmProvider` port.
Depends on:    infrastructure/rag/*, infrastructure/persistence/dependencies.py,
                core/config.py.
Depended on by: api/rag.py.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import Settings, get_settings
from forge.domain.rag.ports import ChunkRepository, EmbeddingProvider, LlmProvider, SourceReader
from forge.infrastructure.persistence.dependencies import get_session
from forge.infrastructure.rag.chunk_repository_impl import SqlAlchemyChunkRepository
from forge.infrastructure.rag.embeddings.hashing import HashingEmbeddingProvider
from forge.infrastructure.rag.embeddings.ollama import OllamaEmbeddingProvider
from forge.infrastructure.rag.llm.extractive import ExtractiveLlmProvider
from forge.infrastructure.rag.llm.ollama import OllamaLlmProvider
from forge.infrastructure.rag.ollama_client import OllamaClient
from forge.infrastructure.rag.source_reader import FilesystemSourceReader


def get_chunk_repository(session: AsyncSession = Depends(get_session)) -> ChunkRepository:
    return SqlAlchemyChunkRepository(session)


def get_source_reader(settings: Settings = Depends(get_settings)) -> SourceReader:
    # A file that was small enough to parse is small enough to read back for
    # chunking, so reuse parsing's own per-file ceiling.
    return FilesystemSourceReader(max_bytes=settings.max_parse_file_bytes)


def get_ollama_client(settings: Settings = Depends(get_settings)) -> OllamaClient:
    return OllamaClient(
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.rag_ollama_timeout_seconds,
    )


def get_embedding_provider(
    settings: Settings = Depends(get_settings),
    client: OllamaClient = Depends(get_ollama_client),
) -> EmbeddingProvider:
    """The configured embedding provider — real Ollama by default, or the
    deterministic hashing double when `rag_embedding_provider="hashing"`."""
    if settings.rag_embedding_provider == "hashing":
        return HashingEmbeddingProvider(dimensions=settings.rag_embedding_dimensions)
    return OllamaEmbeddingProvider(
        client=client,
        model=settings.rag_embedding_model,
        dimensions=settings.rag_embedding_dimensions,
        batch_size=settings.rag_embedding_batch_size,
    )


def get_llm_provider(
    settings: Settings = Depends(get_settings),
    client: OllamaClient = Depends(get_ollama_client),
) -> LlmProvider:
    """The configured generation provider — real Ollama by default, or the
    deterministic extractive double when `rag_llm_provider="extractive"`."""
    if settings.rag_llm_provider == "extractive":
        return ExtractiveLlmProvider()
    return OllamaLlmProvider(
        client=client,
        model=settings.rag_llm_model,
        temperature=settings.rag_llm_temperature,
        num_ctx=settings.rag_llm_num_ctx,
    )
