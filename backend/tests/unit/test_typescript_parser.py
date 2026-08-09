"""Unit tests for TypeScriptParser — pure, no I/O, no database."""

from __future__ import annotations

from uuid import uuid4

from forge.domain.parsing.entities import SymbolKind
from forge.infrastructure.parsing.typescript_parser import TypeScriptParser


def _parse(source: str, path: str = "sample.ts", *, tsx: bool = False):
    return TypeScriptParser(tsx=tsx).parse(
        repository_id=uuid4(), file_path=path, source=source.encode()
    )


def test_extracts_top_level_function_with_location() -> None:
    result = _parse("function greet(name: string): string {\n  return name;\n}\n")

    symbol = result.symbols[0]
    assert symbol.kind is SymbolKind.FUNCTION
    assert symbol.name == "greet"
    assert symbol.location.start_line == 1
    assert symbol.location.end_line == 3


def test_extracts_class_and_its_methods_with_parent_link() -> None:
    result = _parse(
        "class Foo extends Base {\n  methodA(x: number): number {\n    return x;\n  }\n}\n"
    )

    class_symbol = next(s for s in result.symbols if s.kind is SymbolKind.CLASS)
    method = next(s for s in result.symbols if s.kind is SymbolKind.METHOD)

    assert class_symbol.name == "Foo"
    assert method.name == "methodA"
    assert method.parent_symbol_id == class_symbol.id
    assert method.qualified_name == "Foo.methodA"
    assert class_symbol.base_class_names == ("Base",)


def test_extends_and_implements_only_extends_counts_as_inheritance() -> None:
    result = _parse("class Foo extends Base implements Iface, Other {\n}\n")
    class_symbol = next(s for s in result.symbols if s.kind is SymbolKind.CLASS)
    # `implements` is a type constraint, not inheritance — deliberately excluded.
    assert class_symbol.base_class_names == ("Base",)


def test_extracts_bare_call() -> None:
    result = _parse("function f() {\n  helper();\n}\n")
    assert result.symbols[0].calls[0].callee_expression == "helper"


def test_extracts_this_attribute_call() -> None:
    result = _parse("class C {\n  m(): void {\n    this.other();\n  }\n}\n")
    method = next(s for s in result.symbols if s.name == "m")
    assert method.calls[0].callee_expression == "this.other"


def test_extracts_typed_parameters_with_annotations_and_defaults() -> None:
    result = _parse(
        "function f(a: number, b: string = 'x', c?: number, ...rest: number[]) {}\n"
    )
    params = result.symbols[0].parameters
    assert [p.name for p in params] == ["a", "b", "c", "rest"]

    by_name = {p.name: p for p in params}
    assert by_name["a"].annotation == "number"
    assert by_name["a"].default_value is None
    assert by_name["b"].annotation == "string"
    assert by_name["b"].default_value == "'x'"
    assert by_name["c"].annotation == "number"
    assert by_name["rest"].annotation == "number[]"


def test_extracts_named_import() -> None:
    result = _parse('import { Thing } from "./thing";\n')
    imp = result.imports[0]
    assert imp.module == "./thing"
    assert imp.imported_names == ("Thing",)


def test_malformed_source_still_extracts_recoverable_symbols() -> None:
    # Same rationale as test_javascript_parser.py's equivalent test: the error is
    # contained inside `broken`'s body so it doesn't corrupt brace-matching for
    # the rest of the file.
    source = "function broken() {\n  const x = ;\n}\n\nclass Ok {\n  m(): void {}\n}\n"
    result = _parse(source)

    assert result.has_syntax_errors is True
    assert "Ok" in {s.name for s in result.symbols}


def test_empty_file_produces_no_symbols_or_imports() -> None:
    result = _parse("")
    assert result.symbols == ()
    assert result.imports == ()
    assert result.has_syntax_errors is False


def test_tsx_variant_parses_jsx_syntax() -> None:
    source = (
        "function Component(): JSX.Element {\n"
        "  return <div>hello</div>;\n"
        "}\n"
    )
    result = _parse(source, path="sample.tsx", tsx=True)
    assert result.has_syntax_errors is False
    assert result.symbols[0].name == "Component"
