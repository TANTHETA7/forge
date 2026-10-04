"""Unit tests for Hybrid Retrieval (RAG V2 / Phase 1).

Scope: Validates the three-channel candidate retrieval layer (semantic, lexical,
and exact symbol matching) and Weighted Reciprocal Rank Fusion (RRF).

Tests cover:
  1. Exact symbol query - exact symbol match ranks appropriately at top.
  2. Lexical-only useful result - query with distinctive code text succeeds
     even when semantic similarity is below floor.
  3. Semantic retrieval still works - natural language queries without symbols
     or keywords remain fully functional.
  4. Hybrid deduplication - a chunk surfaced across multiple retrieval channels
     appears only once in retrieved sources.
  5. Repository isolation - candidates from other repositories are never returned.
  6. Empty lexical result - semantic hits still surface and answer.
  7. Empty semantic result - lexical/exact retrieval succeeds when vector scan is empty.
  8. Final top-k remains bounded - candidate pool caps at configured top_k.
  9. Existing citation/source mapping remains correct - real chunk metadata preserved.
  10. Pure retrieval math tests for symbol extraction, lexical terms, and RRF fusion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from forge.application.rag.ask_service import RagAskConfig, RagAskService
from forge.domain.rag.entities import CodeChunk, EmbeddedChunk
from forge.domain.rag.retrieval import (
    extract_lexical_terms,
    find_symbol_candidates,
    fuse_hybrid_candidates,
)
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


def _config(*, top_k: int = 4, min_score: float = 0.35) -> RagAskConfig:
    return RagAskConfig(
        candidate_limit=5000,
        top_k=top_k,
        min_score=min_score,
        graph_seed_limit=2,
        graph_neighbor_limit=4,
        graph_chunk_limit=4,
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
    embedding: tuple[float, ...] = (0.0, 0.0, 0.0),
    chunk_id: UUID | None = None,
    symbol_id: UUID | None = None,
    path: str = "module.py",
    start: int = 1,
    end: int = 10,
    qualified_name: str | None = None,
    kind: str | None = None,
    content: str = "def code(): pass",
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
        token_estimate=len(content) // 4,
    )
    return EmbeddedChunk(chunk=chunk, embedding=embedding, embedding_model="stub-embed")


async def _setup_service(
    repository_id: UUID,
    project_id: UUID,
    chunks: InMemoryChunkRepository,
    *,
    query_vectors: dict[str, tuple[float, ...]] | None = None,
    llm_reply: str = "Grounded response.",
    config: RagAskConfig | None = None,
) -> tuple[RagAskService, ScriptedLlmProvider]:
    repositories = InMemoryRepositoryRepository()
    await repositories.create(_repository(repository_id=repository_id, project_id=project_id))
    embedder = StubEmbeddingProvider(query_vectors or {})
    llm = ScriptedLlmProvider(reply=llm_reply)
    service = RagAskService(
        repositories=repositories,
        chunks=chunks,
        graph=InMemoryGraphRepository(),
        embedder=embedder,
        llm=llm,
        llm_provider_label="scripted",
        config=config or _config(),
    )
    return service, llm


# --- 1. Exact Symbol Query ---------------------------------------------------


async def test_exact_symbol_query_ranks_appropriately() -> None:
    """If the question contains an exact function/class name, that chunk strongly
    prioritizes at the top of retrieved sources over a chunk with generic semantic match.
    """
    project_id, repo_id = uuid4(), uuid4()
    chunks = InMemoryChunkRepository()

    # Chunk A: generic repository helper with higher cosine similarity
    chunk_generic = _embedded(
        repo_id,
        embedding=(1.0, 0.0, 0.0),
        path="helpers/repo_utils.py",
        start=1,
        end=10,
        qualified_name="helpers.repo_utils.common_helper",
        kind="function",
        content="def common_helper(): return 'generic repository utilities'",
    )

    # Chunk B: exact symbol `create_repository` with lower cosine similarity
    chunk_exact_symbol = _embedded(
        repo_id,
        embedding=(0.4, 0.0, 0.0),  # clears floor but lower cosine than generic
        path="services/repository_service.py",
        start=20,
        end=35,
        qualified_name="services.repository_service.create_repository",
        kind="function",
        content="def create_repository(spec): return Repository.create(spec)",
    )

    await chunks.replace_chunks(repo_id, (chunk_generic, chunk_exact_symbol))

    question = "Where is create_repository used?"
    service, _ = await _setup_service(
        repo_id,
        project_id,
        chunks,
        query_vectors={question: (1.0, 0.0, 0.0)},
    )

    answer = await service.ask(project_id, repo_id, question)

    assert answer.has_sufficient_evidence is True
    assert len(answer.sources) >= 1
    # Chunk B (exact symbol) must rank #1 despite lower cosine similarity
    top_source = answer.sources[0]
    assert top_source.path == "services/repository_service.py"
    assert top_source.symbol_qualified_name == "services.repository_service.create_repository"


# --- 2. Lexical-only Useful Result --------------------------------------------


async def test_lexical_only_distinctive_code_text_retrieves_chunk() -> None:
    """A query containing distinctive code text (e.g. a constant or identifier)
    retrieves the chunk even when semantic vector similarity is weak (below floor).
    """
    project_id, repo_id = uuid4(), uuid4()
    chunks = InMemoryChunkRepository()

    # Chunk has distinctive token SENTINEL_VALUE_XYZ but orthogonal embedding (cosine 0.0)
    chunk_distinctive = _embedded(
        repo_id,
        embedding=(0.0, 1.0, 0.0),  # orthogonal to query (1.0, 0.0, 0.0)
        path="tokens/constants.py",
        start=1,
        end=5,
        content="SENTINEL_VALUE_XYZ = 'secret_token_12345'",
    )
    await chunks.replace_chunks(repo_id, (chunk_distinctive,))

    question = "Where is SENTINEL_VALUE_XYZ defined?"
    service, llm = await _setup_service(
        repo_id,
        project_id,
        chunks,
        query_vectors={question: (1.0, 0.0, 0.0)},
        llm_reply="SENTINEL_VALUE_XYZ is defined in tokens/constants.py",
    )

    answer = await service.ask(project_id, repo_id, question)

    assert answer.has_sufficient_evidence is True
    assert len(answer.sources) == 1
    assert answer.sources[0].path == "tokens/constants.py"
    assert answer.sources[0].via == "lexical"
    assert llm.calls == 1


# --- 3. Semantic Retrieval Still Works ----------------------------------------


async def test_semantic_retrieval_still_works() -> None:
    """Natural-language question with no exact symbol name or distinctive keywords
    retrieves candidate purely via vector cosine similarity.
    """
    project_id, repo_id = uuid4(), uuid4()
    chunks = InMemoryChunkRepository()

    chunk_auth = _embedded(
        repo_id,
        embedding=(1.0, 0.0, 0.0),
        path="security/tokens.py",
        content="def verify_credential(principal): return True",
    )
    await chunks.replace_chunks(repo_id, (chunk_auth,))

    question = "How does user credential verification work?"
    service, _ = await _setup_service(
        repo_id,
        project_id,
        chunks,
        query_vectors={question: (1.0, 0.0, 0.0)},
    )

    answer = await service.ask(project_id, repo_id, question)

    assert answer.has_sufficient_evidence is True
    assert len(answer.sources) == 1
    assert answer.sources[0].path == "security/tokens.py"
    assert answer.sources[0].via == "vector"


# --- 4. Hybrid Deduplication --------------------------------------------------


async def test_hybrid_deduplication_chunk_appears_once() -> None:
    """A chunk found by semantic retrieval, lexical search, AND exact symbol match
    must appear only ONCE in the candidate pool and final retrieved citations.
    """
    project_id, repo_id = uuid4(), uuid4()
    chunks = InMemoryChunkRepository()

    chunk_triple_match = _embedded(
        repo_id,
        embedding=(1.0, 0.0, 0.0),  # semantic match
        path="shapes/circle.py",
        start=10,
        end=20,
        qualified_name="shapes.circle.calculate_area",  # symbol match
        kind="function",
        content="def calculate_area(radius): return 3.14 * radius * radius",  # lexical match
    )
    await chunks.replace_chunks(repo_id, (chunk_triple_match,))

    question = "How does calculate_area compute area for circle?"
    service, _ = await _setup_service(
        repo_id,
        project_id,
        chunks,
        query_vectors={question: (1.0, 0.0, 0.0)},
    )

    answer = await service.ask(project_id, repo_id, question)

    assert answer.has_sufficient_evidence is True
    # Must appear exactly once in sources despite matching all 3 branches
    assert len(answer.sources) == 1
    assert answer.sources[0].path == "shapes/circle.py"
    assert answer.sources[0].symbol_qualified_name == "shapes.circle.calculate_area"


# --- 5. Repository Isolation -------------------------------------------------


async def test_repository_isolation_enforced_across_all_retrieval_branches() -> None:
    """A query against repository B must NEVER return candidates from repository A,
    even if repository A has exact symbol and lexical matches.
    """
    project_id = uuid4()
    repo_a, repo_b = uuid4(), uuid4()
    chunks = InMemoryChunkRepository()

    # Repo A has the matching chunk
    await chunks.replace_chunks(
        repo_a,
        (
            _embedded(
                repo_a,
                embedding=(1.0, 0.0, 0.0),
                path="repo_a_secret.py",
                qualified_name="secrets.get_token",
                content="SECRET_KEY_ALPHA = 'confidential'",
            ),
        ),
    )

    # Repo B has unrelated indexed chunk
    await chunks.replace_chunks(
        repo_b,
        (
            _embedded(
                repo_b,
                embedding=(0.0, 1.0, 0.0),
                path="repo_b_normal.py",
                qualified_name="normal.run",
                content="def normal(): return 42",
            ),
        ),
    )

    repositories = InMemoryRepositoryRepository()
    await repositories.create(_repository(repository_id=repo_a, project_id=project_id))
    await repositories.create(_repository(repository_id=repo_b, project_id=project_id))

    question = "Where is get_token or SECRET_KEY_ALPHA?"
    service = RagAskService(
        repositories=repositories,
        chunks=chunks,
        graph=InMemoryGraphRepository(),
        embedder=StubEmbeddingProvider({question: (1.0, 0.0, 0.0)}),
        llm=ScriptedLlmProvider(),
        llm_provider_label="scripted",
        config=_config(),
    )

    # Ask repository B — must NOT see repo A's secret
    answer = await service.ask(project_id, repo_b, question)

    assert all("repo_a_secret.py" not in s.path for s in answer.sources)
    assert all("SECRET_KEY_ALPHA" not in s.path for s in answer.sources)


# --- 6. Empty Lexical Result --------------------------------------------------


async def test_empty_lexical_result_semantic_still_works() -> None:
    """When lexical search returns no matches, semantic retrieval functions normally."""
    project_id, repo_id = uuid4(), uuid4()
    chunks = InMemoryChunkRepository()

    chunk = _embedded(
        repo_id,
        embedding=(1.0, 0.0, 0.0),
        path="core/engine.py",
        content="def execute_pipeline(): return 0",
    )
    await chunks.replace_chunks(repo_id, (chunk,))

    # Question uses synonyms with zero vocabulary overlap with the code
    question = "How is processing orchestration dispatched?"
    service, _ = await _setup_service(
        repo_id,
        project_id,
        chunks,
        query_vectors={question: (1.0, 0.0, 0.0)},
    )

    answer = await service.ask(project_id, repo_id, question)

    assert answer.has_sufficient_evidence is True
    assert len(answer.sources) == 1
    assert answer.sources[0].path == "core/engine.py"


# --- 7. Empty Semantic Result -------------------------------------------------


async def test_empty_semantic_result_lexical_and_exact_can_answer() -> None:
    """When vector similarity produces no hits clearing the floor, lexical and exact
    symbol retrieval provide viable candidates to generate a grounded answer.
    """
    project_id, repo_id = uuid4(), uuid4()
    chunks = InMemoryChunkRepository()

    chunk = _embedded(
        repo_id,
        embedding=(0.0, 0.0, 1.0),  # orthogonal -> cosine 0.0 < 0.35 floor
        path="math/fibonacci.py",
        qualified_name="math.fibonacci.compute_fibonacci",
        content=(
            "def compute_fibonacci(n):\n"
            "    return n if n <= 1 else compute_fibonacci(n-1) + compute_fibonacci(n-2)"
        ),
    )
    await chunks.replace_chunks(repo_id, (chunk,))

    question = "Explain compute_fibonacci"
    service, llm = await _setup_service(
        repo_id,
        project_id,
        chunks,
        query_vectors={question: (1.0, 0.0, 0.0)},  # orthogonal to chunk
        llm_reply="compute_fibonacci recursively calculates fibonacci numbers.",
    )

    answer = await service.ask(project_id, repo_id, question)

    assert answer.has_sufficient_evidence is True
    assert len(answer.sources) == 1
    assert answer.sources[0].path == "math/fibonacci.py"
    assert answer.sources[0].symbol_qualified_name == "math.fibonacci.compute_fibonacci"
    assert llm.calls == 1


# --- 8. Final top-k Remains Bounded -------------------------------------------


async def test_final_top_k_remains_bounded() -> None:
    """When multiple branches surface many candidates, the final result is bounded
    strictly by `top_k`.
    """
    project_id, repo_id = uuid4(), uuid4()
    chunks = InMemoryChunkRepository()

    # Insert 15 matching chunks
    batch = tuple(
        _embedded(
            repo_id,
            embedding=(1.0, 0.0, 0.0),
            path=f"file_{i}.py",
            start=i * 10,
            end=i * 10 + 5,
            content=f"def function_{i}(): return 'distinctive_item_{i}'",
        )
        for i in range(15)
    )
    await chunks.replace_chunks(repo_id, batch)

    question = "What functions exist?"
    service, _ = await _setup_service(
        repo_id,
        project_id,
        chunks,
        query_vectors={question: (1.0, 0.0, 0.0)},
        config=_config(top_k=3),
    )

    answer = await service.ask(project_id, repo_id, question)

    assert answer.has_sufficient_evidence is True
    assert len(answer.sources) == 3


# --- 9. Citation / Source Mapping Correctness ---------------------------------


async def test_citation_mapping_preserves_real_chunk_metadata() -> None:
    """Verifies all attributes of SourceReference are mapped accurately from real chunk."""
    project_id, repo_id = uuid4(), uuid4()
    chunks = InMemoryChunkRepository()

    chunk_id = uuid4()
    sym_id = uuid4()
    chunk = _embedded(
        repo_id,
        chunk_id=chunk_id,
        symbol_id=sym_id,
        embedding=(1.0, 0.0, 0.0),
        path="pkg/parser.py",
        start=42,
        end=88,
        qualified_name="pkg.parser.ASTParser",
        kind="class",
        content="class ASTParser:\n    def parse(self): pass",
    )
    await chunks.replace_chunks(repo_id, (chunk,))

    question = "Explain ASTParser"
    service, _ = await _setup_service(
        repo_id,
        project_id,
        chunks,
        query_vectors={question: (1.0, 0.0, 0.0)},
    )

    answer = await service.ask(project_id, repo_id, question)

    assert answer.has_sufficient_evidence is True
    assert len(answer.sources) == 1
    src = answer.sources[0]
    assert src.path == "pkg/parser.py"
    assert src.start_line == 42
    assert src.end_line == 88
    assert src.symbol_qualified_name == "pkg.parser.ASTParser"
    assert src.symbol_kind == "class"
    assert src.score == pytest.approx(1.0)


# --- 10. Pure Retrieval Math Tests --------------------------------------------


def test_find_symbol_candidates_identifies_programming_constructs() -> None:
    q1 = "Where is create_repository used?"
    assert "create_repository" in find_symbol_candidates(q1)

    q2 = "Explain GraphProjectionService"
    assert "GraphProjectionService" in find_symbol_candidates(q2)

    q3 = "How does `shapes.Circle.calculate_area` compute?"
    syms = find_symbol_candidates(q3)
    assert any("calculate_area" in s for s in syms)


def test_extract_lexical_terms_filters_stop_words() -> None:
    terms = extract_lexical_terms("How does Circle calculate its area with radius in Python?")
    assert "circle" in terms
    assert "calculate" in terms
    assert "area" in terms
    assert "radius" in terms
    assert "python" in terms
    assert "how" not in terms
    assert "does" not in terms
    assert "its" not in terms
    assert "with" not in terms
    assert "in" not in terms


def test_fuse_hybrid_candidates_rrf_scoring_and_determinism() -> None:
    c1, c2, c3 = uuid4(), uuid4(), uuid4()

    # c1 is rank 1 in exact symbol
    # c2 is rank 1 in semantic
    # c3 is rank 1 in lexical
    fused, debug = fuse_hybrid_candidates(
        semantic_ranked=[(c2, 0.9)],
        lexical_chunk_ids=[c3],
        symbol_chunk_ids=[c1],
        top_k=3,
        weight_symbol=2.0,
        weight_semantic=1.0,
        weight_lexical=1.0,
    )

    # c1 (exact symbol, weight 2.0) must beat c2 and c3
    ids = [cid for cid, _, _ in fused]
    assert ids[0] == c1
    assert debug.exact_symbol_count == 1
    assert debug.semantic_count == 1
    assert debug.lexical_count == 1
    assert debug.merged_count == 3
    assert debug.final_count == 3
