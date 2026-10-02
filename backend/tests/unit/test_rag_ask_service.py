"""Unit tests for `RagAskService` (Phase 7).

Scope: the ask orchestration in isolation, with full control over similarity via
a stub embedder (query vector) and directly-stored candidate vectors. These prove
the four guarantees that make an answer trustworthy:

  1. Isolation      — a question against repository B never sees repository A.
  2. Bounded work   — graph expansion makes a constant number of calls (seed
                      limit), never one-per-hit (no N+1).
  3. Explicit
     insufficiency  — not-indexed, below-floor, and model-declared-insufficient
                      all return has_sufficient_evidence=False; the below-floor
                      path never invokes the model at all.
  4. Un-fakeable
     citations      — every source is built from a real retrieved chunk's
                      metadata, including graph-surfaced evidence vector search
                      missed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from forge.application.rag.ask_service import (
    _MODEL_INSUFFICIENT_MESSAGE,
    _NO_RELEVANT_CODE_MESSAGE,
    _NOT_INDEXED_MESSAGE,
    RagAskConfig,
    RagAskService,
)
from forge.domain.errors import NotFoundError, RagProviderError
from forge.domain.graph.entities import (
    GraphNode,
    GraphNodeKind,
    GraphRelationship,
    GraphRelationshipKind,
)
from forge.domain.rag.entities import CodeChunk, EmbeddedChunk
from forge.domain.rag.prompting import INSUFFICIENT_EVIDENCE_MARKER, SYSTEM_PROMPT
from forge.domain.repository.entities import (
    Repository,
    RepositorySourceType,
    RepositoryStatus,
)
from tests.fakes import (
    InMemoryChunkRepository,
    InMemoryGraphRepository,
    InMemoryRepositoryRepository,
    ScriptedLlmProvider,
    StubEmbeddingProvider,
)

_QUESTION = "How does authentication work?"


def _config(
    *, min_score: float = 0.35, top_k: int = 6, graph_seed_limit: int = 3
) -> RagAskConfig:
    return RagAskConfig(
        candidate_limit=5000,
        top_k=top_k,
        min_score=min_score,
        graph_seed_limit=graph_seed_limit,
        graph_neighbor_limit=8,
        graph_chunk_limit=8,
        max_context_chars=9000,
    )


def _repository(*, repository_id: UUID, project_id: UUID) -> Repository:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    return Repository(
        id=repository_id,
        project_id=project_id,
        source_type=RepositorySourceType.ZIP,
        source_ref="upload.zip",
        display_name="repo",
        workspace_path="/workspace/repo",
        status=RepositoryStatus.READY,
        metadata=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def _embedded(
    repository_id: UUID,
    *,
    embedding: tuple[float, ...],
    chunk_id: UUID | None = None,
    symbol_id: UUID | None = None,
    path: str = "module.py",
    start: int = 1,
    end: int = 5,
    qualified_name: str | None = None,
    kind: str | None = None,
    content: str = "def something():\n    return 1",
) -> EmbeddedChunk:
    chunk = CodeChunk(
        id=chunk_id or uuid4(),
        repository_id=repository_id,
        file_id=uuid4(),
        path=path,
        language="python",
        start_line=start,
        end_line=end,
        content=content,
        content_hash=f"hash-{path}-{start}-{end}",
        symbol_id=symbol_id,
        symbol_qualified_name=qualified_name,
        symbol_kind=kind,
        token_estimate=1,
    )
    return EmbeddedChunk(chunk=chunk, embedding=embedding, embedding_model="stub-embed")


async def _repositories_with(repository: Repository) -> InMemoryRepositoryRepository:
    repositories = InMemoryRepositoryRepository()
    await repositories.create(repository)
    return repositories


def _service(
    repositories: InMemoryRepositoryRepository,
    chunks: InMemoryChunkRepository,
    graph: object,
    *,
    embedder: StubEmbeddingProvider,
    llm: ScriptedLlmProvider,
    config: RagAskConfig | None = None,
) -> RagAskService:
    return RagAskService(
        repositories=repositories,
        chunks=chunks,
        graph=graph,  # type: ignore[arg-type]
        embedder=embedder,
        llm=llm,
        llm_provider_label="scripted",
        config=config or _config(),
    )


# --- Explicit insufficiency -------------------------------------------------


async def test_not_indexed_returns_insufficient_without_calling_model() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories = await _repositories_with(
        _repository(repository_id=repository_id, project_id=project_id)
    )
    llm = ScriptedLlmProvider()
    service = _service(
        repositories,
        InMemoryChunkRepository(),  # empty -> no candidates
        InMemoryGraphRepository(),
        embedder=StubEmbeddingProvider(),
        llm=llm,
    )

    answer = await service.ask(project_id, repository_id, _QUESTION)

    assert answer.has_sufficient_evidence is False
    assert answer.answer == _NOT_INDEXED_MESSAGE
    assert answer.sources == ()
    assert llm.calls == 0  # never fabricate against an empty index


async def test_below_similarity_floor_declines_without_calling_model() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories = await _repositories_with(
        _repository(repository_id=repository_id, project_id=project_id)
    )
    chunks = InMemoryChunkRepository()
    # Stored chunk is orthogonal to the query -> cosine 0.0, below the 0.35 floor.
    await chunks.replace_chunks(
        repository_id, (_embedded(repository_id, embedding=(0.0, 1.0, 0.0)),)
    )
    llm = ScriptedLlmProvider()
    service = _service(
        repositories,
        chunks,
        InMemoryGraphRepository(),
        embedder=StubEmbeddingProvider({_QUESTION: (1.0, 0.0, 0.0)}),
        llm=llm,
    )

    answer = await service.ask(project_id, repository_id, _QUESTION)

    assert answer.has_sufficient_evidence is False
    assert answer.answer == _NO_RELEVANT_CODE_MESSAGE
    assert answer.sources == ()
    assert llm.calls == 0  # THE guarantee: no model call below the floor


async def test_model_declared_insufficient_is_surfaced_explicitly() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories = await _repositories_with(
        _repository(repository_id=repository_id, project_id=project_id)
    )
    chunks = InMemoryChunkRepository()
    await chunks.replace_chunks(
        repository_id, (_embedded(repository_id, embedding=(1.0, 0.0, 0.0)),)
    )
    # The model, shown real excerpts, judges them insufficient and emits the marker.
    llm = ScriptedLlmProvider(reply=INSUFFICIENT_EVIDENCE_MARKER)
    service = _service(
        repositories,
        chunks,
        InMemoryGraphRepository(),
        embedder=StubEmbeddingProvider({_QUESTION: (1.0, 0.0, 0.0)}),
        llm=llm,
    )

    answer = await service.ask(project_id, repository_id, _QUESTION)

    assert answer.has_sufficient_evidence is False
    assert answer.answer == _MODEL_INSUFFICIENT_MESSAGE
    assert answer.sources == ()
    assert llm.calls == 1  # the model WAS consulted here, unlike the floor case


# --- Grounded happy path & citations ----------------------------------------


async def test_grounded_answer_cites_real_retrieved_chunk() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories = await _repositories_with(
        _repository(repository_id=repository_id, project_id=project_id)
    )
    chunks = InMemoryChunkRepository()
    await chunks.replace_chunks(
        repository_id,
        (
            _embedded(
                repository_id,
                embedding=(1.0, 0.0, 0.0),
                symbol_id=uuid4(),
                path="auth/login.py",
                start=10,
                end=24,
                qualified_name="auth.login.authenticate",
                kind="function",
                content="def authenticate(user, password):\n    return verify(user, password)",
            ),
        ),
    )
    llm = ScriptedLlmProvider(reply="Authentication is handled by authenticate().")
    service = _service(
        repositories,
        chunks,
        InMemoryGraphRepository(),  # empty graph -> no expansion
        embedder=StubEmbeddingProvider({_QUESTION: (1.0, 0.0, 0.0)}),
        llm=llm,
    )

    answer = await service.ask(project_id, repository_id, _QUESTION)

    assert answer.has_sufficient_evidence is True
    assert answer.answer == "Authentication is handled by authenticate()."
    assert answer.llm_provider == "scripted"
    assert answer.embedding_model == "stub-embed"
    assert len(answer.sources) == 1
    source = answer.sources[0]
    # Citation is the chunk's REAL metadata, not anything the model produced.
    assert source.path == "auth/login.py"
    assert source.start_line == 10
    assert source.end_line == 24
    assert source.symbol_qualified_name == "auth.login.authenticate"
    assert source.symbol_kind == "function"
    assert source.via == "vector"
    assert source.score == pytest.approx(1.0)


async def test_prompt_is_grounded_in_retrieved_content() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories = await _repositories_with(
        _repository(repository_id=repository_id, project_id=project_id)
    )
    chunks = InMemoryChunkRepository()
    marker_content = "def unique_marker_fn():\n    return 'SENTINEL_VALUE_XYZ'"
    await chunks.replace_chunks(
        repository_id,
        (_embedded(repository_id, embedding=(1.0, 0.0, 0.0), content=marker_content),),
    )
    llm = ScriptedLlmProvider()
    service = _service(
        repositories,
        chunks,
        InMemoryGraphRepository(),
        embedder=StubEmbeddingProvider({_QUESTION: (1.0, 0.0, 0.0)}),
        llm=llm,
    )

    await service.ask(project_id, repository_id, _QUESTION)

    assert llm.last_system == SYSTEM_PROMPT
    assert llm.last_prompt is not None
    assert "SENTINEL_VALUE_XYZ" in llm.last_prompt  # the real code reached the model
    assert _QUESTION in llm.last_prompt


# --- Bounded, graph-aware retrieval -----------------------------------------


async def test_graph_expansion_surfaces_chunk_vector_search_missed() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories = await _repositories_with(
        _repository(repository_id=repository_id, project_id=project_id)
    )
    seed_symbol, neighbor_symbol = uuid4(), uuid4()
    chunks = InMemoryChunkRepository()
    await chunks.replace_chunks(
        repository_id,
        (
            # Vector hit (on-axis), owns the seed symbol.
            _embedded(
                repository_id,
                embedding=(1.0, 0.0, 0.0),
                symbol_id=seed_symbol,
                path="a.py",
                qualified_name="pkg.a",
                kind="function",
            ),
            # Off-axis -> vector search misses it, but it's a graph neighbor.
            _embedded(
                repository_id,
                embedding=(0.0, 1.0, 0.0),
                symbol_id=neighbor_symbol,
                path="b.py",
                qualified_name="pkg.b",
                kind="function",
            ),
        ),
    )
    graph = InMemoryGraphRepository()
    await graph.project_repository(
        repository_id,
        (
            GraphNode(
                id=seed_symbol,
                kind=GraphNodeKind.SYMBOL,
                repository_id=repository_id,
                properties={"qualified_name": "pkg.a", "kind": "function"},
            ),
            GraphNode(
                id=neighbor_symbol,
                kind=GraphNodeKind.SYMBOL,
                repository_id=repository_id,
                properties={"qualified_name": "pkg.b", "kind": "function"},
            ),
        ),
        (
            GraphRelationship(
                source_id=seed_symbol,
                target_id=neighbor_symbol,
                kind=GraphRelationshipKind.CALLS,
                repository_id=repository_id,
                dependency_edge_id=None,
                properties={},
            ),
        ),
    )
    service = _service(
        repositories,
        chunks,
        graph,
        embedder=StubEmbeddingProvider({_QUESTION: (1.0, 0.0, 0.0)}),
        llm=ScriptedLlmProvider(),
    )

    answer = await service.ask(project_id, repository_id, _QUESTION)

    assert answer.has_sufficient_evidence is True
    vias = {source.via for source in answer.sources}
    assert vias == {"vector", "graph"}  # both kinds of evidence present
    graph_source = next(s for s in answer.sources if s.via == "graph")
    assert graph_source.path == "b.py"  # the neighbor vector search missed
    assert graph_source.symbol_qualified_name == "pkg.b"
    # Structural context records the relationship, direction, and related symbol.
    assert len(answer.graph_context) == 1
    context = answer.graph_context[0]
    assert context.qualified_name == "pkg.b"
    assert context.relationship == "calls"
    assert context.direction == "outgoing"


async def test_graph_calls_are_bounded_by_seed_limit_not_hit_count() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories = await _repositories_with(
        _repository(repository_id=repository_id, project_id=project_id)
    )
    chunks = InMemoryChunkRepository()
    # Five on-axis vector hits, each owning a distinct symbol -> five potential seeds.
    await chunks.replace_chunks(
        repository_id,
        tuple(
            _embedded(
                repository_id,
                embedding=(1.0, 0.0, 0.0),
                symbol_id=uuid4(),
                path=f"file_{i}.py",
                start=i * 10 + 1,
                end=i * 10 + 5,
                qualified_name=f"pkg.fn_{i}",
                kind="function",
            )
            for i in range(5)
        ),
    )

    class _CountingGraph:
        def __init__(self, inner: InMemoryGraphRepository) -> None:
            self._inner = inner
            self.neighbor_calls = 0

        async def get_neighbors(self, *args: object, **kwargs: object) -> object:
            self.neighbor_calls += 1
            return await self._inner.get_neighbors(*args, **kwargs)  # type: ignore[arg-type]

    graph = _CountingGraph(InMemoryGraphRepository())
    service = _service(
        repositories,
        chunks,
        graph,
        embedder=StubEmbeddingProvider({_QUESTION: (1.0, 0.0, 0.0)}),
        llm=ScriptedLlmProvider(),
        config=_config(graph_seed_limit=2),  # cap expansion at 2 seeds
    )

    await service.ask(project_id, repository_id, _QUESTION)

    # 5 vector hits but only 2 graph calls — expansion is a constant, not N+1.
    assert graph.neighbor_calls == 2


# --- Isolation & ownership --------------------------------------------------


async def test_question_against_other_repository_sees_nothing() -> None:
    project_a, repo_a = uuid4(), uuid4()
    project_b, repo_b = uuid4(), uuid4()
    repositories = InMemoryRepositoryRepository()
    await repositories.create(_repository(repository_id=repo_a, project_id=project_a))
    await repositories.create(_repository(repository_id=repo_b, project_id=project_b))
    chunks = InMemoryChunkRepository()
    # Only repository A is indexed, with a highly-relevant chunk.
    await chunks.replace_chunks(
        repository_id=repo_a,
        chunks=(
            _embedded(
                repo_a,
                embedding=(1.0, 0.0, 0.0),
                content="SECRET_FROM_REPO_A",
            ),
        ),
    )
    llm = ScriptedLlmProvider()
    service = _service(
        repositories,
        chunks,
        InMemoryGraphRepository(),
        embedder=StubEmbeddingProvider({_QUESTION: (1.0, 0.0, 0.0)}),
        llm=llm,
    )

    # Asking repository B (owned, but empty) must NOT retrieve A's content.
    answer = await service.ask(project_b, repo_b, _QUESTION)

    assert answer.has_sufficient_evidence is False
    assert answer.answer == _NOT_INDEXED_MESSAGE
    assert answer.sources == ()
    assert llm.calls == 0
    assert "SECRET_FROM_REPO_A" not in answer.answer


async def test_ask_wrong_project_raises_not_found() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories = await _repositories_with(
        _repository(repository_id=repository_id, project_id=project_id)
    )
    service = _service(
        repositories,
        InMemoryChunkRepository(),
        InMemoryGraphRepository(),
        embedder=StubEmbeddingProvider(),
        llm=ScriptedLlmProvider(),
    )

    with pytest.raises(NotFoundError):
        await service.ask(uuid4(), repository_id, _QUESTION)  # a different project


async def test_embedding_provider_failure_propagates() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories = await _repositories_with(
        _repository(repository_id=repository_id, project_id=project_id)
    )
    service = _service(
        repositories,
        InMemoryChunkRepository(),
        InMemoryGraphRepository(),
        embedder=StubEmbeddingProvider(fail=True),
        llm=ScriptedLlmProvider(),
    )

    with pytest.raises(RagProviderError):
        await service.ask(project_id, repository_id, _QUESTION)
