"""Unit tests for JavaScriptParser — pure, no I/O, no database."""

from __future__ import annotations

from uuid import uuid4

from forge.domain.parsing.entities import SymbolKind
from forge.infrastructure.parsing.javascript_parser import JavaScriptParser


def _parse(source: str, path: str = "sample.js"):
    return JavaScriptParser().parse(repository_id=uuid4(), file_path=path, source=source.encode())


def test_extracts_top_level_function_with_location() -> None:
    result = _parse("function greet(name) {\n  return name;\n}\n")

    assert len(result.symbols) == 1
    symbol = result.symbols[0]
    assert symbol.kind is SymbolKind.FUNCTION
    assert symbol.name == "greet"
    assert symbol.location.start_line == 1
    assert symbol.location.end_line == 3


def test_extracts_class_and_its_methods_with_parent_link() -> None:
    result = _parse(
        "class Foo extends Base {\n"
        "  methodA(x) { return x; }\n"
        "  static methodB() {}\n"
        "}\n"
    )

    class_symbol = next(s for s in result.symbols if s.kind is SymbolKind.CLASS)
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]

    assert class_symbol.name == "Foo"
    assert {m.name for m in methods} == {"methodA", "methodB"}
    for method in methods:
        assert method.parent_symbol_id == class_symbol.id


def test_arrow_functions_are_not_extracted_as_symbols() -> None:
    result = _parse("const add = (a, b) => a + b;\n")
    assert result.symbols == ()


def test_extracts_parameters_with_default_and_rest() -> None:
    result = _parse("function f(a, b = 1, ...rest) {}\n")
    params = result.symbols[0].parameters
    assert [p.name for p in params] == ["a", "b", "rest"]
    by_name = {p.name: p for p in params}
    assert by_name["b"].default_value == "1"
    assert by_name["rest"].default_value is None


def test_extracts_default_import() -> None:
    result = _parse('import Default from "./mod";\n')
    imp = result.imports[0]
    assert imp.module == "./mod"
    assert imp.alias == "Default"
    assert imp.imported_names == ()


def test_extracts_named_imports_with_alias() -> None:
    result = _parse('import { Named, Other as Alias } from "./mod";\n')
    imp = result.imports[0]
    assert imp.module == "./mod"
    assert imp.imported_names == ("Named", "Other")


def test_extracts_namespace_import() -> None:
    result = _parse('import * as ns from "ns-pkg";\n')
    imp = result.imports[0]
    assert imp.module == "ns-pkg"
    assert imp.alias == "ns"


def test_extracts_side_effect_only_import() -> None:
    result = _parse('import "side-effect-only";\n')
    imp = result.imports[0]
    assert imp.module == "side-effect-only"
    assert imp.alias is None
    assert imp.imported_names == ()


def test_malformed_source_still_extracts_recoverable_symbols() -> None:
    # The syntax error (`const x = ;`) is contained inside `broken`'s body, so it
    # doesn't corrupt brace-matching for the rest of the file — unlike a broken
    # signature, which can cascade into misparsing everything after it (verified
    # empirically while writing this test: a broken `function broken((` swallowed
    # the following class into a recovery ERROR node instead of leaving it clean).
    source = "function broken() {\n  const x = ;\n}\n\nclass Ok {\n  m() {}\n}\n"
    result = _parse(source)

    assert result.has_syntax_errors is True
    assert "Ok" in {s.name for s in result.symbols}


def test_empty_file_produces_no_symbols_or_imports() -> None:
    result = _parse("")
    assert result.symbols == ()
    assert result.imports == ()
    assert result.has_syntax_errors is False
