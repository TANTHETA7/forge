"""Unit tests for PythonModuleResolver — pure, no I/O, no database."""

from __future__ import annotations

from uuid import uuid4

from forge.domain.dependency_analysis.entities import ResolutionStatus
from forge.domain.parsing.entities import Import, Language, ParsedFile, SourceLocation
from forge.infrastructure.dependency_analysis.python_module_resolver import PythonModuleResolver

_LOCATION = SourceLocation(start_line=1, end_line=1, start_column=0, end_column=None)


def _file(path: str) -> ParsedFile:
    return ParsedFile(
        id=uuid4(),
        repository_id=uuid4(),
        path=path,
        language=Language.PYTHON,
        symbols=(),
        imports=(),
        has_syntax_errors=False,
    )


def _import(module: str, imported_names: tuple[str, ...] = ()) -> Import:
    return Import(
        id=uuid4(), module=module, imported_names=imported_names, alias=None, location=_LOCATION
    )


def _resolve(module_str, imported_names, source_path, files):
    source = next(f for f in files if f.path == source_path)
    resolver = PythonModuleResolver()
    return resolver.resolve_import(_import(module_str, imported_names), source, files)


def test_resolves_absolute_dotted_import() -> None:
    files = [_file("main.py"), _file("pkg/utils.py")]
    result = _resolve("pkg.utils", (), "main.py", files)
    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_file_id == files[1].id


def test_resolves_absolute_import_to_package_init() -> None:
    files = [_file("main.py"), _file("pkg/__init__.py")]
    result = _resolve("pkg", (), "main.py", files)
    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_file_id == files[1].id


def test_bare_name_without_a_leading_dot_is_treated_as_absolute() -> None:
    # "models" (no dot) resolved against the repo root, not the source file's
    # own directory — it does not match a sibling src/lib/deep/models.py.
    files = [_file("src/lib/deep/component.py"), _file("src/lib/deep/models.py")]
    result = _resolve("models", (), "src/lib/deep/component.py", files)
    assert result.status is ResolutionStatus.UNRESOLVED


def test_resolves_single_dot_relative_import() -> None:
    files = [_file("src/lib/a.py"), _file("src/lib/models.py")]
    result = _resolve(".models", (), "src/lib/a.py", files)
    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_file_id == files[1].id


def test_resolves_double_dot_relative_import() -> None:
    # From src/lib/deep/a.py (package src.lib.deep), ".." is the *parent*
    # package (src.lib) — one level up from the package itself, not from its
    # grandparent — so "..models" resolves to src/lib/models.py.
    files = [_file("src/lib/deep/a.py"), _file("src/lib/models.py")]
    result = _resolve("..models", (), "src/lib/deep/a.py", files)
    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_file_id == files[1].id


def test_resolves_bare_dot_single_name_import() -> None:
    # from . import utils
    files = [_file("pkg/a.py"), _file("pkg/utils.py")]
    result = _resolve(".", ("utils",), "pkg/a.py", files)
    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_file_id == files[1].id


def test_bare_dot_multi_name_import_is_ambiguous() -> None:
    # from . import a, b — two distinct real targets, cannot pick one
    files = [_file("pkg/main.py"), _file("pkg/a.py"), _file("pkg/b.py")]
    result = _resolve(".", ("a", "b"), "pkg/main.py", files)
    assert result.status is ResolutionStatus.AMBIGUOUS
    assert result.target_file_id is None


def test_unresolved_when_no_matching_file() -> None:
    files = [_file("main.py")]
    result = _resolve("some.external.package", (), "main.py", files)
    assert result.status is ResolutionStatus.UNRESOLVED
    assert result.target_file_id is None
    assert "external" in (result.detail or "") or "no matching file" in (result.detail or "")


def test_root_level_relative_import() -> None:
    files = [_file("main.py"), _file("utils.py")]
    result = _resolve(".utils", (), "main.py", files)
    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_file_id == files[1].id


def test_non_python_files_are_never_candidates() -> None:
    py_file = _file("main.py")
    js_file = ParsedFile(
        id=uuid4(),
        repository_id=py_file.repository_id,
        path="utils.py",
        language=Language.JAVASCRIPT,  # same path text, wrong language — must not match
        symbols=(),
        imports=(),
        has_syntax_errors=False,
    )
    resolver = PythonModuleResolver()
    result = resolver.resolve_import(_import(".utils"), py_file, [py_file, js_file])
    assert result.status is ResolutionStatus.UNRESOLVED
