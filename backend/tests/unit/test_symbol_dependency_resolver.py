"""Unit tests for SymbolDependencyResolver — pure, no I/O, no database.

Uses the real `PythonModuleResolver` as the injected `ModuleResolver` (not a
fake) — cheap, deterministic, and it's exactly how the resolver is actually
wired in application/dependency_analysis/service.py, so these tests exercise
the real import-following path a `module.func()`/`pkg.Base` resolution needs.
"""

from __future__ import annotations

from uuid import uuid4

from forge.domain.dependency_analysis.entities import ResolutionStatus
from forge.domain.parsing.entities import (
    CallReference,
    Import,
    Language,
    ParsedFile,
    SourceLocation,
    Symbol,
    SymbolKind,
)
from forge.infrastructure.dependency_analysis.python_module_resolver import PythonModuleResolver
from forge.infrastructure.dependency_analysis.symbol_dependency_resolver import (
    SymbolDependencyResolver,
)

_LOCATION = SourceLocation(start_line=1, end_line=1, start_column=0, end_column=None)


def _symbol(
    name: str,
    kind: SymbolKind,
    *,
    parent_symbol_id=None,
    calls: tuple[CallReference, ...] = (),
    base_class_names: tuple[str, ...] = (),
) -> Symbol:
    return Symbol(
        id=uuid4(),
        kind=kind,
        name=name,
        qualified_name=name,
        location=_LOCATION,
        parameters=(),
        parent_symbol_id=parent_symbol_id,
        base_class_names=base_class_names,
        calls=calls,
    )


def _file(
    path: str, symbols: tuple[Symbol, ...] = (), imports: tuple[Import, ...] = ()
) -> ParsedFile:
    return ParsedFile(
        id=uuid4(),
        repository_id=uuid4(),
        path=path,
        language=Language.PYTHON,
        symbols=symbols,
        imports=imports,
        has_syntax_errors=False,
    )


def _import(module: str, imported_names: tuple[str, ...] = (), alias: str | None = None) -> Import:
    return Import(
        id=uuid4(), module=module, imported_names=imported_names, alias=alias, location=_LOCATION
    )


def _resolver() -> SymbolDependencyResolver:
    return SymbolDependencyResolver(PythonModuleResolver())


# --- calls: bare name -------------------------------------------------------


def test_resolves_bare_call_to_same_file_function() -> None:
    target = _symbol("helper", SymbolKind.FUNCTION)
    caller = _symbol("main", SymbolKind.FUNCTION, calls=(CallReference("helper", _LOCATION),))
    file = _file("main.py", symbols=(caller, target))

    result = _resolver().resolve_call(caller.calls[0], caller, file, [file])

    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_symbol_id == target.id


def test_bare_call_does_not_match_a_method_of_the_same_name() -> None:
    # A bare `helper()` call can't reach a method — only a top-level function.
    cls = _symbol("Foo", SymbolKind.CLASS)
    method = _symbol("helper", SymbolKind.METHOD, parent_symbol_id=cls.id)
    caller = _symbol("main", SymbolKind.FUNCTION, calls=(CallReference("helper", _LOCATION),))
    file = _file("main.py", symbols=(cls, method, caller))

    result = _resolver().resolve_call(caller.calls[0], caller, file, [file])

    assert result.status is ResolutionStatus.UNRESOLVED


def test_resolves_bare_call_to_imported_function() -> None:
    target = _symbol("helper", SymbolKind.FUNCTION)
    utils_file = _file("utils.py", symbols=(target,))
    caller = _symbol("main", SymbolKind.FUNCTION, calls=(CallReference("helper", _LOCATION),))
    main_file = _file("main.py", symbols=(caller,), imports=(_import(".utils", ("helper",)),))

    result = _resolver().resolve_call(caller.calls[0], caller, main_file, [main_file, utils_file])

    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_symbol_id == target.id
    assert result.target_file_id == utils_file.id


def test_unresolved_when_no_definition_or_import_matches() -> None:
    caller = _symbol("main", SymbolKind.FUNCTION, calls=(CallReference("mystery", _LOCATION),))
    file = _file("main.py", symbols=(caller,))

    result = _resolver().resolve_call(caller.calls[0], caller, file, [file])

    assert result.status is ResolutionStatus.UNRESOLVED
    assert result.detail is not None


def test_ambiguous_when_two_wildcard_imports_both_define_the_same_name() -> None:
    a_symbol = _symbol("helper", SymbolKind.FUNCTION)
    b_symbol = _symbol("helper", SymbolKind.FUNCTION)
    a_file = _file("a.py", symbols=(a_symbol,))
    b_file = _file("b.py", symbols=(b_symbol,))
    caller = _symbol("main", SymbolKind.FUNCTION, calls=(CallReference("helper", _LOCATION),))
    main_file = _file(
        "main.py",
        symbols=(caller,),
        imports=(_import(".a", ("*",)), _import(".b", ("*",))),
    )

    result = _resolver().resolve_call(
        caller.calls[0], caller, main_file, [main_file, a_file, b_file]
    )

    assert result.status is ResolutionStatus.AMBIGUOUS


# --- calls: self./this. -------------------------------------------------


def test_resolves_self_call_to_method_on_same_class() -> None:
    cls = _symbol("Foo", SymbolKind.CLASS)
    other = _symbol("other", SymbolKind.METHOD, parent_symbol_id=cls.id)
    caller = _symbol(
        "m",
        SymbolKind.METHOD,
        parent_symbol_id=cls.id,
        calls=(CallReference("self.other", _LOCATION),),
    )
    file = _file("foo.py", symbols=(cls, other, caller))

    result = _resolver().resolve_call(caller.calls[0], caller, file, [file])

    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_symbol_id == other.id


def test_this_call_resolves_the_same_way_as_self() -> None:
    cls = _symbol("Foo", SymbolKind.CLASS)
    other = _symbol("other", SymbolKind.METHOD, parent_symbol_id=cls.id)
    caller = _symbol(
        "m",
        SymbolKind.METHOD,
        parent_symbol_id=cls.id,
        calls=(CallReference("this.other", _LOCATION),),
    )
    file = _file("foo.js", symbols=(cls, other, caller))

    result = _resolver().resolve_call(caller.calls[0], caller, file, [file])

    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_symbol_id == other.id


def test_self_call_to_undefined_method_is_unresolved_not_guessed() -> None:
    cls = _symbol("Foo", SymbolKind.CLASS)
    caller = _symbol(
        "m",
        SymbolKind.METHOD,
        parent_symbol_id=cls.id,
        calls=(CallReference("self.inherited_method", _LOCATION),),
    )
    file = _file("foo.py", symbols=(cls, caller))

    result = _resolver().resolve_call(caller.calls[0], caller, file, [file])

    # Deliberately not walked up the inheritance chain — see the module's own
    # docstring for why guessing here would be worse than UNRESOLVED.
    assert result.status is ResolutionStatus.UNRESOLVED


def test_self_call_from_a_top_level_function_is_unresolved() -> None:
    caller = _symbol(
        "f", SymbolKind.FUNCTION, calls=(CallReference("self.other", _LOCATION),)
    )
    file = _file("f.py", symbols=(caller,))

    result = _resolver().resolve_call(caller.calls[0], caller, file, [file])

    assert result.status is ResolutionStatus.UNRESOLVED


# --- calls: qualified / unresolvable chains ---------------------------------


def test_resolves_module_qualified_call() -> None:
    # `from . import utils` binds the name "utils" (via imported_names, not
    # alias) — matching what the real PythonParser actually produces for this
    # form (there is no bare `import .utils` syntax in Python).
    target = _symbol("func", SymbolKind.FUNCTION)
    utils_file = _file("utils.py", symbols=(target,))
    caller = _symbol("main", SymbolKind.FUNCTION, calls=(CallReference("utils.func", _LOCATION),))
    main_file = _file(
        "main.py", symbols=(caller,), imports=(_import(".", imported_names=("utils",)),)
    )

    result = _resolver().resolve_call(caller.calls[0], caller, main_file, [main_file, utils_file])

    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_symbol_id == target.id


def test_arbitrary_object_chain_is_always_unresolved() -> None:
    caller = _symbol(
        "main", SymbolKind.FUNCTION, calls=(CallReference("obj.attr.method", _LOCATION),)
    )
    file = _file("main.py", symbols=(caller,))

    result = _resolver().resolve_call(caller.calls[0], caller, file, [file])

    assert result.status is ResolutionStatus.UNRESOLVED
    assert "not statically known" in (result.detail or "")


# --- inheritance -------------------------------------------------------------


def test_resolves_same_file_inheritance() -> None:
    base = _symbol("Base", SymbolKind.CLASS)
    file = _file("f.py", symbols=(base,))

    result = _resolver().resolve_inheritance("Base", file, [file])

    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_symbol_id == base.id


def test_resolves_imported_inheritance() -> None:
    base = _symbol("Base", SymbolKind.CLASS)
    base_file = _file("base.py", symbols=(base,))
    sub_file = _file("sub.py", imports=(_import(".base", ("Base",)),))

    result = _resolver().resolve_inheritance("Base", sub_file, [sub_file, base_file])

    assert result.status is ResolutionStatus.RESOLVED
    assert result.target_symbol_id == base.id


def test_builtin_or_external_base_class_is_unresolved() -> None:
    file = _file("f.py")
    result = _resolver().resolve_inheritance("Exception", file, [file])
    assert result.status is ResolutionStatus.UNRESOLVED


def test_dotted_external_base_class_is_unresolved() -> None:
    file = _file("f.py")
    result = _resolver().resolve_inheritance("react.Component", file, [file])
    assert result.status is ResolutionStatus.UNRESOLVED
