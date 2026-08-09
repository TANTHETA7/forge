"""Unit tests for EcmaScriptModuleResolver — pure, no I/O, no database."""

from __future__ import annotations

from uuid import uuid4

from forge.domain.dependency_analysis.entities import ResolutionStatus
from forge.domain.parsing.entities import Import, Language, ParsedFile, SourceLocation
from forge.infrastructure.dependency_analysis.ecmascript_module_resolver import (
    EcmaScriptModuleResolver,
)

_LOCATION = SourceLocation(start_line=1, end_line=1, start_column=0, end_column=None)


def _file(path: str, language: Language = Language.TYPESCRIPT) -> ParsedFile:
    return ParsedFile(
        id=uuid4(),
        repository_id=uuid4(),
        path=path,
        language=language,
        symbols=(),
        imports=(),
        has_syntax_errors=False,
    )


def _import(module: str) -> Import:
    return Import(id=uuid4(), module=module, imported_names=(), alias=None, location=_LOCATION)


def _resolve(module_str: str, source_path: str, files: list[ParsedFile]):
    source = next(f for f in files if f.path == source_path)
    return EcmaScriptModuleResolver().resolve_import(_import(module_str), source, files)


def test_resolves_same_directory_relative_import() -> None:
    files = [_file("src/main.ts"), _file("src/utils.ts")]
    result = _resolve("./utils", "src/main.ts", files)
    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_file_id == files[1].id


def test_resolves_parent_directory_relative_import() -> None:
    files = [_file("src/lib/deep/a.ts"), _file("src/lib/utils.ts")]
    result = _resolve("../utils", "src/lib/deep/a.ts", files)
    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_file_id == files[1].id


def test_resolves_grandparent_directory_relative_import() -> None:
    files = [_file("src/lib/deep/a.ts"), _file("src/utils.ts")]
    result = _resolve("../../utils", "src/lib/deep/a.ts", files)
    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_file_id == files[1].id


def test_resolves_index_file_in_a_directory() -> None:
    files = [_file("src/main.ts"), _file("src/widgets/index.ts")]
    result = _resolve("./widgets", "src/main.ts", files)
    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_file_id == files[1].id


def test_resolves_jsx_extension() -> None:
    files = [_file("src/main.js", Language.JAVASCRIPT), _file("src/App.jsx", Language.JAVASCRIPT)]
    result = _resolve("./App", "src/main.js", files)
    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_file_id == files[1].id


def test_bare_package_specifier_is_always_unresolved() -> None:
    files = [_file("src/main.ts")]
    result = _resolve("react", "src/main.ts", files)
    assert result.status is ResolutionStatus.UNRESOLVED
    assert "external" in (result.detail or "") or "package" in (result.detail or "")


def test_unresolved_when_no_matching_file() -> None:
    files = [_file("src/main.ts")]
    result = _resolve("./does-not-exist", "src/main.ts", files)
    assert result.status is ResolutionStatus.UNRESOLVED
    assert result.target_file_id is None


def test_non_ecmascript_files_are_never_candidates() -> None:
    ts_file = _file("src/main.ts")
    py_file = ParsedFile(
        id=uuid4(),
        repository_id=ts_file.repository_id,
        path="src/utils.ts",
        language=Language.PYTHON,  # same path text, wrong language — must not match
        symbols=(),
        imports=(),
        has_syntax_errors=False,
    )
    result = EcmaScriptModuleResolver().resolve_import(
        _import("./utils"), ts_file, [ts_file, py_file]
    )
    assert result.status is ResolutionStatus.UNRESOLVED
