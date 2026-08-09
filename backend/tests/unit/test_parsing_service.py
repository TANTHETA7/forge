"""Orchestration tests for ParsingService.

Exercises the full workflow — repository lookup, discovery, language detection,
parsing, persistence — against real infrastructure (a real filesystem workspace,
the real file discovery walk, the real tree-sitter parsers) but in-memory fakes
for persistence (see tests/fakes.py), mirroring
test_repository_import_service.py's established approach: real everything except
the database, so this proves actual wiring without needing Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from forge.application.parsing.service import ParsingService
from forge.domain.errors import NotFoundError, ParseFailure, UnsupportedRepositoryStateError
from forge.domain.parsing.entities import Language, ParsedFile, SymbolKind
from forge.domain.repository.entities import (
    Repository,
    RepositorySourceType,
    RepositoryStatus,
)
from forge.infrastructure.parsing.file_discovery import FilesystemFileDiscovery
from forge.infrastructure.parsing.javascript_parser import JavaScriptParser
from forge.infrastructure.parsing.python_parser import PythonParser
from forge.infrastructure.parsing.registry import DefaultParserRegistry
from forge.infrastructure.parsing.typescript_parser import TypeScriptParser
from tests.fakes import InMemoryParsedFileRepository, InMemoryRepositoryRepository


def _registry() -> DefaultParserRegistry:
    return DefaultParserRegistry(
        python=PythonParser(),
        javascript=JavaScriptParser(),
        typescript=TypeScriptParser(),
        tsx=TypeScriptParser(tsx=True),
    )


def _service(
    max_file_bytes: int = 1024 * 1024,
) -> tuple[ParsingService, InMemoryRepositoryRepository, InMemoryParsedFileRepository]:
    repositories = InMemoryRepositoryRepository()
    parsed_files = InMemoryParsedFileRepository()
    service = ParsingService(
        repositories=repositories,
        parsed_files=parsed_files,
        discovery=FilesystemFileDiscovery(max_file_bytes=max_file_bytes),
        registry=_registry(),
    )
    return service, repositories, parsed_files


async def _seed_ready_repository(
    repositories: InMemoryRepositoryRepository,
    workspace: Path,
    *,
    status: RepositoryStatus = RepositoryStatus.READY,
) -> Repository:
    now = datetime.now(UTC)
    repository = Repository(
        id=uuid4(),
        project_id=uuid4(),
        source_type=RepositorySourceType.ZIP,
        source_ref="upload.zip",
        display_name="upload",
        workspace_path=str(workspace),
        status=status,
        metadata=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    await repositories.create(repository)
    return repository


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


async def test_parses_mixed_language_repository_and_persists_result(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write(workspace / "src" / "app.py", "class Foo:\n    def bar(self):\n        pass\n")
    _write(workspace / "src" / "app.js", "function greet() {}\n")
    _write(workspace / "README.md", "# hello")  # unsupported — silently skipped

    service, repositories, parsed_files = _service()
    repository = await _seed_ready_repository(repositories, workspace)

    result = await service.parse_repository(repository.id)

    assert {f.language for f in result.files} == {Language.PYTHON, Language.JAVASCRIPT}
    assert result.errors == ()
    # Persisted, not just returned:
    persisted = await parsed_files.get_files(repository.id)
    assert len(persisted) == 2


async def test_unsupported_files_are_not_recorded_as_errors(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write(workspace / "README.md", "# hello")
    _write(workspace / "styles.css", "body {}")

    service, repositories, _ = _service()
    repository = await _seed_ready_repository(repositories, workspace)

    result = await service.parse_repository(repository.id)

    assert result.files == ()
    assert result.errors == ()


async def test_nested_directories_are_all_discovered(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write(workspace / "a.py", "def top(): pass\n")
    _write(workspace / "src" / "b.py", "def mid(): pass\n")
    _write(workspace / "src" / "lib" / "c.py", "def deep(): pass\n")

    service, repositories, _ = _service()
    repository = await _seed_ready_repository(repositories, workspace)

    result = await service.parse_repository(repository.id)

    assert {f.path for f in result.files} == {"a.py", "src/b.py", "src/lib/c.py"}


async def test_duplicate_symbol_names_in_different_files_get_distinct_ids(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    _write(workspace / "a.py", "def helper(): pass\n")
    _write(workspace / "b.py", "def helper(): pass\n")

    service, repositories, _ = _service()
    repository = await _seed_ready_repository(repositories, workspace)

    result = await service.parse_repository(repository.id)

    all_symbols = [s for f in result.files for s in f.symbols]
    assert len(all_symbols) == 2
    assert {s.name for s in all_symbols} == {"helper"}
    assert all_symbols[0].id != all_symbols[1].id


async def test_one_bad_file_does_not_abort_the_rest_of_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    _write(workspace / "broken.py", "this triggers the fake failure\n")
    _write(workspace / "good.py", "def ok(): pass\n")

    def _always_fails(self: object, **kwargs: object) -> ParsedFile:
        raise ParseFailure("simulated parser bug")

    monkeypatch.setattr(PythonParser, "parse", _always_fails)

    service, repositories, _ = _service()
    repository = await _seed_ready_repository(repositories, workspace)

    result = await service.parse_repository(repository.id)

    assert result.files == ()
    assert len(result.errors) == 2
    assert {e.file_path for e in result.errors} == {"broken.py", "good.py"}
    assert all(e.stage == "parse" for e in result.errors)


async def test_oversized_file_is_recorded_as_skip_not_error(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write(workspace / "big.py", "x = 1\n" * 100)

    service, repositories, _ = _service(max_file_bytes=10)
    repository = await _seed_ready_repository(repositories, workspace)

    result = await service.parse_repository(repository.id)

    assert result.files == ()
    assert result.errors == ()  # oversized is a silent policy skip, not an error


async def test_parsing_unknown_repository_raises_not_found() -> None:
    service, _repositories, _ = _service()
    with pytest.raises(NotFoundError):
        await service.parse_repository(uuid4())


async def test_parsing_non_ready_repository_is_rejected(tmp_path: Path) -> None:
    service, repositories, _ = _service()
    repository = await _seed_ready_repository(
        repositories, tmp_path / "workspace", status=RepositoryStatus.IMPORTING
    )

    with pytest.raises(UnsupportedRepositoryStateError):
        await service.parse_repository(repository.id)


async def test_get_symbols_filters_by_kind_after_parsing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write(workspace / "app.py", "class Foo:\n    def bar(self):\n        pass\n")

    service, repositories, _ = _service()
    repository = await _seed_ready_repository(repositories, workspace)
    await service.parse_repository(repository.id)

    classes = await service.get_symbols(repository.id, kind=SymbolKind.CLASS)
    assert len(classes) == 1
    assert classes[0].kind is SymbolKind.CLASS


async def test_get_symbol_by_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write(workspace / "app.py", "def greet(): pass\n")

    service, repositories, _ = _service()
    repository = await _seed_ready_repository(repositories, workspace)
    result = await service.parse_repository(repository.id)

    symbol_id = result.files[0].symbols[0].id
    fetched = await service.get_symbol(symbol_id)
    assert fetched.name == "greet"


async def test_get_symbol_unknown_id_raises_not_found() -> None:
    service, _repositories, _ = _service()
    with pytest.raises(NotFoundError):
        await service.get_symbol(UUID(int=0))


async def test_get_files_for_unknown_repository_raises_not_found() -> None:
    service, _repositories, _ = _service()
    with pytest.raises(NotFoundError):
        await service.get_files(uuid4())
