"""RAG API router (Phase 7).

Purpose:       Expose the code-intelligence RAG flow over HTTP — index a
                repository, check its index status, and ask grounded questions.
Responsibility: Translate between HTTP and `application/rag/*` only. No chunking,
                embedding, retrieval, or generation logic here (that is the
                application/domain/infrastructure layers'); this router builds the
                services from injected ports, calls one method, and maps the
                domain result to a wire model. Citations on the wire are exactly
                the domain `SourceReference`s — real retrieved-chunk metadata,
                never anything the model emitted.
Depends on:    application/rag/*, infrastructure/rag/dependencies.py,
                infrastructure/persistence/dependencies.py,
                infrastructure/graph/dependencies.py, core/config.py.
Depended on by: core/app_factory.py (registers this router, guarded by
                api/ownership.py's `verify_repository_ownership`).

Repository isolation is enforced twice, deliberately: the router is mounted with
the ownership dependency in app_factory, and every service method independently
re-verifies ownership before any repository-scoped read.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from forge.application.rag import RagAskConfig, RagAskService, RagIndexingService
from forge.core.config import Settings, get_settings
from forge.domain.graph.ports import GraphRepository
from forge.domain.parsing.ports import ParsedFileRepository
from forge.domain.rag.chunking import ChunkingConfig
from forge.domain.rag.entities import (
    GraphContextItem,
    IndexingResult,
    IndexStatus,
    RagAnswer,
    SourceReference,
)
from forge.domain.rag.ports import ChunkRepository, EmbeddingProvider, LlmProvider, SourceReader
from forge.domain.repository.ports import RepositoryRepository
from forge.infrastructure.graph.dependencies import get_graph_repository
from forge.infrastructure.persistence.dependencies import (
    get_parsed_file_repository,
    get_repository_repository,
)
from forge.infrastructure.rag.dependencies import (
    get_chunk_repository,
    get_embedding_provider,
    get_llm_provider,
    get_source_reader,
)

router = APIRouter(
    prefix="/projects/{project_id}/repositories/{repository_id}", tags=["rag"]
)


# --- Wire models -------------------------------------------------------------


class AskRequest(BaseModel):
    """Wire format for `POST /rag/ask`."""

    question: str = Field(..., min_length=1, max_length=2000)


class IndexingResponse(BaseModel):
    """Wire format for `POST /rag/index` — a re-index run's bookkeeping."""

    repository_id: UUID
    chunk_count: int
    embedded_count: int
    reused_count: int
    files_indexed: int
    skipped_files: int
    embedding_model: str
    indexed_at: datetime


class IndexStatusResponse(BaseModel):
    """Wire format for `GET /rag/status`."""

    repository_id: UUID
    indexed: bool
    chunk_count: int
    embedding_model: str | None
    last_indexed_at: datetime | None


class SourceReferenceResponse(BaseModel):
    """A citation — the real metadata of a chunk Forge retrieved, never model
    output (see domain/rag/entities.py)."""

    path: str
    start_line: int
    end_line: int
    score: float
    via: str
    symbol_qualified_name: str | None
    symbol_kind: str | None
    snippet: str = ""


class GraphContextItemResponse(BaseModel):
    """A related symbol surfaced by bounded graph expansion."""

    qualified_name: str
    kind: str
    relationship: str
    direction: str


class AskResponse(BaseModel):
    """Wire format for `POST /rag/ask`."""

    question: str
    answer: str
    has_sufficient_evidence: bool
    sources: list[SourceReferenceResponse]
    graph_context: list[GraphContextItemResponse]
    llm_provider: str
    llm_model: str
    embedding_model: str


# --- Service providers -------------------------------------------------------


def get_rag_indexing_service(
    repositories: RepositoryRepository = Depends(get_repository_repository),
    parsed_files: ParsedFileRepository = Depends(get_parsed_file_repository),
    chunks: ChunkRepository = Depends(get_chunk_repository),
    source_reader: SourceReader = Depends(get_source_reader),
    embedder: EmbeddingProvider = Depends(get_embedding_provider),
    settings: Settings = Depends(get_settings),
) -> RagIndexingService:
    return RagIndexingService(
        repositories=repositories,
        parsed_files=parsed_files,
        chunks=chunks,
        source_reader=source_reader,
        embedder=embedder,
        chunking_config=ChunkingConfig(
            max_lines=settings.rag_chunk_max_lines,
            max_chars=settings.rag_chunk_max_chars,
            min_chars=settings.rag_chunk_min_chars,
        ),
    )


def get_rag_ask_service(
    repositories: RepositoryRepository = Depends(get_repository_repository),
    chunks: ChunkRepository = Depends(get_chunk_repository),
    graph: GraphRepository = Depends(get_graph_repository),
    embedder: EmbeddingProvider = Depends(get_embedding_provider),
    llm: LlmProvider = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings),
) -> RagAskService:
    return RagAskService(
        repositories=repositories,
        chunks=chunks,
        graph=graph,
        embedder=embedder,
        llm=llm,
        llm_provider_label=settings.rag_llm_provider,
        config=RagAskConfig(
            candidate_limit=settings.rag_retrieval_candidate_limit,
            top_k=settings.rag_retrieval_top_k,
            min_score=settings.rag_retrieval_min_score,
            graph_seed_limit=settings.rag_graph_seed_limit,
            graph_neighbor_limit=settings.rag_graph_neighbor_limit,
            # Cap graph-surfaced code at top_k too, so graph evidence never
            # outweighs the primary vector hits in the prompt.
            graph_chunk_limit=settings.rag_retrieval_top_k,
            max_context_chars=settings.rag_max_context_chars,
        ),
    )


# --- Routes ------------------------------------------------------------------


@router.post("/rag/index", response_model=IndexingResponse)
async def index_repository(
    project_id: UUID,
    repository_id: UUID,
    service: RagIndexingService = Depends(get_rag_indexing_service),
) -> IndexingResponse:
    """(Re)build this repository's chunk+embedding index from its parsed source.

    409 if the repository isn't `READY` or hasn't been parsed; 404 if it isn't in
    this project; 503 if the embedding provider is unreachable."""
    result = await service.index_repository(project_id, repository_id)
    return _to_indexing_response(result)


@router.get("/rag/status", response_model=IndexStatusResponse)
async def get_index_status(
    project_id: UUID,
    repository_id: UUID,
    service: RagIndexingService = Depends(get_rag_indexing_service),
) -> IndexStatusResponse:
    """Whether this repository is indexed, with how many chunks and which model.
    Never an error for an unindexed repository — `indexed` is simply `false`."""
    status = await service.get_index_status(project_id, repository_id)
    return _to_status_response(status)


@router.post("/rag/ask", response_model=AskResponse)
async def ask_question(
    project_id: UUID,
    repository_id: UUID,
    body: AskRequest,
    service: RagAskService = Depends(get_rag_ask_service),
) -> AskResponse:
    """Answer `question` grounded only in this repository's indexed code.

    Always 200 with a body: when the index can't answer, `has_sufficient_evidence`
    is `false` and `answer` says so explicitly (no fabricated answer, no sources).
    404 if the repository isn't in this project; 503 if a provider is unreachable."""
    answer = await service.ask(project_id, repository_id, body.question)
    return _to_ask_response(answer)


# --- Mapping -----------------------------------------------------------------


def _to_indexing_response(result: IndexingResult) -> IndexingResponse:
    return IndexingResponse(
        repository_id=result.repository_id,
        chunk_count=result.chunk_count,
        embedded_count=result.embedded_count,
        reused_count=result.reused_count,
        files_indexed=result.files_indexed,
        skipped_files=result.skipped_files,
        embedding_model=result.embedding_model,
        indexed_at=result.indexed_at,
    )


def _to_status_response(status: IndexStatus) -> IndexStatusResponse:
    return IndexStatusResponse(
        repository_id=status.repository_id,
        indexed=status.indexed,
        chunk_count=status.chunk_count,
        embedding_model=status.embedding_model,
        last_indexed_at=status.last_indexed_at,
    )


def _to_source_response(source: SourceReference) -> SourceReferenceResponse:
    return SourceReferenceResponse(
        path=source.path,
        start_line=source.start_line,
        end_line=source.end_line,
        score=source.score,
        via=source.via,
        symbol_qualified_name=source.symbol_qualified_name,
        symbol_kind=source.symbol_kind,
        snippet=getattr(source, "snippet", ""),
    )


def _to_graph_context_response(item: GraphContextItem) -> GraphContextItemResponse:
    return GraphContextItemResponse(
        qualified_name=item.qualified_name,
        kind=item.kind,
        relationship=item.relationship,
        direction=item.direction,
    )


def _to_ask_response(answer: RagAnswer) -> AskResponse:
    return AskResponse(
        question=answer.question,
        answer=answer.answer,
        has_sufficient_evidence=answer.has_sufficient_evidence,
        sources=[_to_source_response(s) for s in answer.sources],
        graph_context=[_to_graph_context_response(g) for g in answer.graph_context],
        llm_provider=answer.llm_provider,
        llm_model=answer.llm_model,
        embedding_model=answer.embedding_model,
    )
