"""Unit tests for `RagIndexingService` (Phase 7).

Scope: the indexing orchestration in isolation — real domain chunker, but fake
repository/parsed-file/chunk stores, a mapping source reader, and a stub
embedder. These prove the sequencing guarantees the service owns: ownership is
enforced before any work, only READY+parsed repositories index, an unreadable
file is skipped rather than fatal, embeddings are reused for unchanged content
across re-indexes, and every count returned is accurate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from forge.application.rag.indexing_service import RagIndexingService
from forge.domain.errors import NotFoundError, UnsupportedRepositoryStateError
from forge.domain.parsing.entities import (
    Language,
    ParsedFile,
    ParseResult,
    SourceLocation,
    Symbol,
    SymbolKind,
)
from forge.domain.rag.chunking import ChunkingConfig
from forge.domain.repository.entities import (
    Repository,
    RepositorySourceType,
    RepositoryStatus,
)
from tests.fakes import (
    InMemoryChunkRepository,
    InMemoryParsedFileRepository,
    InMemoryRepositoryRepository,
    MappingSourceReader,
    StubEmbeddingProvider,
)

_CONFIG = ChunkingConfig(max_lines=160, max_chars=6000, min_chars=24)
_WORKSPACE = "/workspace/repo"


def _repository(
    *, repository_id: UUID, project_id: UUID, status: RepositoryStatus = RepositoryStatus.READY
) -> Repository:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    return Repository(
        id=repository_id,
        project_id=project_id,
        source_type=RepositorySourceType.ZIP,
        source_ref="upload.zip",
        display_name="repo",
        workspace_path=_WORKSPACE,
        status=status,
        metadata=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def _function(name: str, start: int, end: int) -> Symbol:
    return Symbol(
        id=uuid4(),
        kind=SymbolKind.FUNCTION,
        name=name,
        qualified_name=name,
        location=SourceLocation(start_line=start, end_line=end, start_column=0, end_column=None),
        parameters=(),
        parent_symbol_id=None,
    )


def _parsed_file(*, repository_id: UUID, path: str, symbols: tuple[Symbol, ...]) -> ParsedFile:
    return ParsedFile(
        id=uuid4(),
        repository_id=repository_id,
        path=path,
        language=Language.PYTHON,
        symbols=symbols,
        imports=(),
        has_syntax_errors=False,
    )


async def _seed(
    *,
    repository: Repository,
    files: tuple[ParsedFile, ...],
) -> tuple[InMemoryRepositoryRepository, InMemoryParsedFileRepository]:
    repositories = InMemoryRepositoryRepository()
    await repositories.create(repository)
    parsed_files = InMemoryParsedFileRepository()
    await parsed_files.save_parse_result(
        ParseResult(
            repository_id=repository.id,
            files=files,
            errors=(),
            parsed_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
    )
    return repositories, parsed_files


def _service(
    repositories: InMemoryRepositoryRepository,
    parsed_files: InMemoryParsedFileRepository,
    chunks: InMemoryChunkRepository,
    reader: MappingSourceReader,
    embedder: StubEmbeddingProvider,
) -> RagIndexingService:
    return RagIndexingService(
        repositories=repositories,
        parsed_files=parsed_files,
        chunks=chunks,
        source_reader=reader,
        embedder=embedder,
        chunking_config=_CONFIG,
    )


_GREET_SOURCE = "def greet(name):\n    return f'Hello, {name}!'\n"


async def test_index_happy_path_counts_and_persists() -> None:
    project_id, repository_id = uuid4(), uuid4()
    parsed = _parsed_file(
        repository_id=repository_id, path="greet.py", symbols=(_function("greet", 1, 2),)
    )
    repositories, parsed_files = await _seed(
        repository=_repository(repository_id=repository_id, project_id=project_id),
        files=(parsed,),
    )
    chunks = InMemoryChunkRepository()
    embedder = StubEmbeddingProvider()
    service = _service(
        repositories,
        parsed_files,
        chunks,
        MappingSourceReader({"greet.py": _GREET_SOURCE}),
        embedder,
    )

    result = await service.index_repository(project_id, repository_id)

    assert result.chunk_count >= 1
    assert result.embedded_count == result.chunk_count  # nothing to reuse on a first index
    assert result.reused_count == 0
    assert result.files_indexed == 1
    assert result.skipped_files == 0
    assert result.embedding_model == "stub-embed"
    # Persisted and visible via status.
    status = await chunks.get_status(repository_id)
    assert status.indexed is True
    assert status.chunk_count == result.chunk_count


async def test_reindex_reuses_embeddings_for_unchanged_content() -> None:
    project_id, repository_id = uuid4(), uuid4()
    parsed = _parsed_file(
        repository_id=repository_id, path="greet.py", symbols=(_function("greet", 1, 2),)
    )
    repositories, parsed_files = await _seed(
        repository=_repository(repository_id=repository_id, project_id=project_id),
        files=(parsed,),
    )
    chunks = InMemoryChunkRepository()
    embedder = StubEmbeddingProvider()
    service = _service(
        repositories,
        parsed_files,
        chunks,
        MappingSourceReader({"greet.py": _GREET_SOURCE}),
        embedder,
    )

    first = await service.index_repository(project_id, repository_id)
    embedder.document_calls.clear()
    second = await service.index_repository(project_id, repository_id)

    assert second.chunk_count == first.chunk_count
    assert second.reused_count == first.chunk_count  # every vector reused
    assert second.embedded_count == 0
    assert embedder.document_calls == []  # the model was not re-invoked at all


async def test_unreadable_file_is_skipped_not_fatal() -> None:
    project_id, repository_id = uuid4(), uuid4()
    good = _parsed_file(
        repository_id=repository_id, path="greet.py", symbols=(_function("greet", 1, 2),)
    )
    missing = _parsed_file(
        repository_id=repository_id, path="gone.py", symbols=(_function("gone", 1, 2),)
    )
    repositories, parsed_files = await _seed(
        repository=_repository(repository_id=repository_id, project_id=project_id),
        files=(good, missing),
    )
    chunks = InMemoryChunkRepository()
    # Only greet.py is readable; gone.py is absent from the map -> reads as None.
    reader = MappingSourceReader({"greet.py": _GREET_SOURCE})
    service = _service(repositories, parsed_files, chunks, reader, StubEmbeddingProvider())

    result = await service.index_repository(project_id, repository_id)

    assert result.skipped_files == 1
    assert result.files_indexed == 1
    assert result.chunk_count >= 1


async def test_index_wrong_project_raises_not_found() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories, parsed_files = await _seed(
        repository=_repository(repository_id=repository_id, project_id=project_id),
        files=(_parsed_file(
            repository_id=repository_id, path="greet.py", symbols=(_function("greet", 1, 2),)
        ),),
    )
    service = _service(
        repositories,
        parsed_files,
        InMemoryChunkRepository(),
        MappingSourceReader({"greet.py": _GREET_SOURCE}),
        StubEmbeddingProvider(),
    )

    with pytest.raises(NotFoundError):
        await service.index_repository(uuid4(), repository_id)  # a different project


async def test_index_non_ready_repository_raises_unsupported_state() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories, parsed_files = await _seed(
        repository=_repository(
            repository_id=repository_id,
            project_id=project_id,
            status=RepositoryStatus.IMPORTING,
        ),
        files=(_parsed_file(
            repository_id=repository_id, path="greet.py", symbols=(_function("greet", 1, 2),)
        ),),
    )
    service = _service(
        repositories,
        parsed_files,
        InMemoryChunkRepository(),
        MappingSourceReader({"greet.py": _GREET_SOURCE}),
        StubEmbeddingProvider(),
    )

    with pytest.raises(UnsupportedRepositoryStateError):
        await service.index_repository(project_id, repository_id)


async def test_index_with_no_parsed_files_raises_unsupported_state() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories, parsed_files = await _seed(
        repository=_repository(repository_id=repository_id, project_id=project_id),
        files=(),  # READY, but never parsed
    )
    service = _service(
        repositories,
        parsed_files,
        InMemoryChunkRepository(),
        MappingSourceReader({}),
        StubEmbeddingProvider(),
    )

    with pytest.raises(UnsupportedRepositoryStateError):
        await service.index_repository(project_id, repository_id)


async def test_get_index_status_before_indexing_reports_not_indexed() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories, parsed_files = await _seed(
        repository=_repository(repository_id=repository_id, project_id=project_id),
        files=(),
    )
    service = _service(
        repositories,
        parsed_files,
        InMemoryChunkRepository(),
        MappingSourceReader({}),
        StubEmbeddingProvider(),
    )

    status = await service.get_index_status(project_id, repository_id)

    assert status.indexed is False
    assert status.chunk_count == 0


async def test_get_index_status_wrong_project_raises_not_found() -> None:
    project_id, repository_id = uuid4(), uuid4()
    repositories, parsed_files = await _seed(
        repository=_repository(repository_id=repository_id, project_id=project_id),
        files=(),
    )
    service = _service(
        repositories,
        parsed_files,
        InMemoryChunkRepository(),
        MappingSourceReader({}),
        StubEmbeddingProvider(),
    )

    with pytest.raises(NotFoundError):
        await service.get_index_status(uuid4(), repository_id)
