"""Unit tests for PythonParser — pure, no I/O, no database."""

from __future__ import annotations

from uuid import uuid4

from forge.domain.parsing.entities import SymbolKind
from forge.infrastructure.parsing.python_parser import PythonParser


def _parse(source: str, path: str = "sample.py"):
    return PythonParser().parse(repository_id=uuid4(), file_path=path, source=source.encode())


def test_extracts_top_level_function_with_location() -> None:
    result = _parse("def greet(name):\n    return name\n")

    assert len(result.symbols) == 1
    symbol = result.symbols[0]
    assert symbol.kind is SymbolKind.FUNCTION
    assert symbol.name == "greet"
    assert symbol.qualified_name == "greet"
    assert symbol.parent_symbol_id is None
    assert symbol.location.start_line == 1
    assert symbol.location.end_line == 2


def test_extracts_class_and_its_methods_with_parent_link() -> None:
    result = _parse(
        "class Foo:\n"
        "    def method_a(self):\n"
        "        pass\n"
        "    def method_b(self):\n"
        "        pass\n"
    )

    class_symbol = next(s for s in result.symbols if s.kind is SymbolKind.CLASS)
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]

    assert class_symbol.name == "Foo"
    assert len(methods) == 2
    for method in methods:
        assert method.parent_symbol_id == class_symbol.id
        assert method.qualified_name.startswith("Foo.")
    assert {m.name for m in methods} == {"method_a", "method_b"}


def test_extracts_parameters_with_annotations_and_defaults() -> None:
    result = _parse(
        "def f(a, b: int, c=1, d: str = 'x', *args, **kwargs):\n    pass\n"
    )

    params = result.symbols[0].parameters
    assert [p.name for p in params] == ["a", "b", "c", "d", "args", "kwargs"]
    assert [p.position for p in params] == [0, 1, 2, 3, 4, 5]

    by_name = {p.name: p for p in params}
    assert by_name["a"].annotation is None and by_name["a"].default_value is None
    assert by_name["b"].annotation == "int" and by_name["b"].default_value is None
    assert by_name["c"].annotation is None and by_name["c"].default_value == "1"
    assert by_name["d"].annotation == "str" and by_name["d"].default_value == "'x'"
    assert by_name["args"].annotation is None
    assert by_name["kwargs"].annotation is None


def test_class_symbol_has_no_parameters() -> None:
    result = _parse("class Foo:\n    pass\n")
    assert result.symbols[0].kind is SymbolKind.CLASS
    assert result.symbols[0].parameters == ()


def test_extracts_bare_import() -> None:
    result = _parse("import os\n")
    assert len(result.imports) == 1
    assert result.imports[0].module == "os"
    assert result.imports[0].imported_names == ()
    assert result.imports[0].alias is None


def test_extracts_aliased_bare_import() -> None:
    result = _parse("import os.path as op\n")
    imp = result.imports[0]
    assert imp.module == "os.path"
    assert imp.alias == "op"


def test_extracts_multi_target_bare_import_as_separate_imports() -> None:
    result = _parse("import a, b\n")
    modules = {imp.module for imp in result.imports}
    assert modules == {"a", "b"}


def test_extracts_from_import_with_multiple_names() -> None:
    result = _parse("from typing import List, Dict\n")
    assert len(result.imports) == 1
    imp = result.imports[0]
    assert imp.module == "typing"
    assert imp.imported_names == ("List", "Dict")


def test_extracts_relative_from_import() -> None:
    result = _parse("from .models import User\n")
    assert result.imports[0].module == ".models"
    assert result.imports[0].imported_names == ("User",)


def test_extracts_wildcard_import() -> None:
    result = _parse("from os import *\n")
    assert result.imports[0].imported_names == ("*",)


def test_malformed_source_still_extracts_recoverable_symbols() -> None:
    source = "def broken(:\n    pass\n\nclass Ok:\n    def m(self):\n        pass\n"
    result = _parse(source)

    assert result.has_syntax_errors is True
    names = {s.name for s in result.symbols}
    assert "Ok" in names
    assert "m" in names


def test_empty_file_produces_no_symbols_or_imports() -> None:
    result = _parse("")
    assert result.symbols == ()
    assert result.imports == ()
    assert result.has_syntax_errors is False


def test_stable_id_across_repeated_parses_of_identical_source() -> None:
    repo_id = uuid4()
    source = "def f():\n    pass\n"
    first = PythonParser().parse(repository_id=repo_id, file_path="a.py", source=source.encode())
    second = PythonParser().parse(repository_id=repo_id, file_path="a.py", source=source.encode())

    assert first.id == second.id
    assert first.symbols[0].id == second.symbols[0].id


def test_extracts_single_base_class() -> None:
    result = _parse("class Foo(Base):\n    pass\n")
    assert result.symbols[0].base_class_names == ("Base",)


def test_extracts_multiple_base_classes_and_excludes_keyword_arguments() -> None:
    result = _parse("class Foo(Base, Mixin, metaclass=Meta):\n    pass\n")
    assert result.symbols[0].base_class_names == ("Base", "Mixin")


def test_extracts_dotted_base_class() -> None:
    result = _parse("class Foo(pkg.Base):\n    pass\n")
    assert result.symbols[0].base_class_names == ("pkg.Base",)


def test_class_with_no_bases_has_empty_base_class_names() -> None:
    result = _parse("class Foo:\n    pass\n")
    assert result.symbols[0].base_class_names == ()


def test_function_and_method_have_no_base_class_names() -> None:
    result = _parse("def f():\n    pass\n\nclass C:\n    def m(self):\n        pass\n")
    assert all(s.base_class_names == () for s in result.symbols)


def test_extracts_bare_call() -> None:
    result = _parse("def f():\n    helper()\n")
    calls = result.symbols[0].calls
    assert len(calls) == 1
    assert calls[0].callee_expression == "helper"


def test_extracts_self_attribute_call() -> None:
    result = _parse("class C:\n    def m(self):\n        self.other()\n")
    method = next(s for s in result.symbols if s.name == "m")
    assert method.calls[0].callee_expression == "self.other"


def test_extracts_dotted_module_call() -> None:
    result = _parse("def f():\n    module.attr.func()\n")
    assert result.symbols[0].calls[0].callee_expression == "module.attr.func"


def test_class_has_no_calls() -> None:
    result = _parse("class C:\n    pass\n")
    assert result.symbols[0].calls == ()


def test_nested_function_calls_are_not_double_counted() -> None:
    source = (
        "def outer():\n"
        "    outer_call()\n"
        "    def inner():\n"
        "        inner_call()\n"
        "    return inner\n"
    )
    result = _parse(source)
    outer = next(s for s in result.symbols if s.name == "outer")
    inner = next(s for s in result.symbols if s.name == "inner")

    assert [c.callee_expression for c in outer.calls] == ["outer_call"]
    assert [c.callee_expression for c in inner.calls] == ["inner_call"]


def test_calls_inside_a_nested_class_belong_to_that_class_not_the_enclosing_function() -> None:
    source = (
        "def outer():\n"
        "    outer_call()\n"
        "    class Inner:\n"
        "        def m(self):\n"
        "            inner_call()\n"
    )
    result = _parse(source)
    outer = next(s for s in result.symbols if s.name == "outer")
    method = next(s for s in result.symbols if s.name == "m")

    assert [c.callee_expression for c in outer.calls] == ["outer_call"]
    assert [c.callee_expression for c in method.calls] == ["inner_call"]


def test_duplicate_function_name_in_different_files_gets_different_ids() -> None:
    repo_id = uuid4()
    source = "def helper():\n    pass\n"
    a = PythonParser().parse(repository_id=repo_id, file_path="a.py", source=source.encode())
    b = PythonParser().parse(repository_id=repo_id, file_path="b.py", source=source.encode())

    assert a.symbols[0].name == b.symbols[0].name == "helper"
    assert a.symbols[0].id != b.symbols[0].id
    assert a.id != b.id
