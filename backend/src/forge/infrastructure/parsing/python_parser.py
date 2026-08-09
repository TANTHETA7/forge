"""Python `LanguageParser`.

Purpose:       Extract classes, functions, methods, parameters, and imports from
                Python source using tree-sitter's `python` grammar.
Responsibility: Map Python-specific tree-sitter node types onto the shared
                `extract_symbols` walker (treesitter_support.py) and implement
                Python's own import-statement shapes, which differ enough from
                JS/TS's single `import_statement` node to not share code with
                javascript_parser.py/typescript_parser.py beyond the common
                plumbing both already use.
Depends on:    tree_sitter, tree_sitter_language_pack, domain/parsing/entities.py,
                domain/errors.py, infrastructure/parsing/treesitter_support.py.
Depended on by: infrastructure/parsing/registry.py.

Python's grammar uses one node type, `function_definition`, for both top-level
functions and methods — a method is only distinguishable by being nested inside a
`class_definition`'s body, which `extract_symbols`'s "function found while inside a
class" rule already handles generically. `self`/`cls` are kept as ordinary
parameters (not special-cased/dropped) — omitting them would be a judgment call
Phase 3 doesn't need to make; a consumer can filter by position/name if it wants
to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from tree_sitter_language_pack import get_parser

from forge.domain.errors import ParseFailure
from forge.domain.parsing.entities import Import, Language, Parameter, ParsedFile, SymbolKind
from forge.infrastructure.parsing.treesitter_support import (
    deterministic_id,
    extract_symbols,
    find_all,
    location_of,
    text_of,
)

if TYPE_CHECKING:
    from tree_sitter import Node

_SYMBOL_NODE_TYPES: dict[str, SymbolKind] = {
    "function_definition": SymbolKind.FUNCTION,
    "class_definition": SymbolKind.CLASS,
}

_IMPORT_NODE_TYPES = frozenset({"import_statement", "import_from_statement"})

_PARAMETER_NODE_TYPES = frozenset(
    {
        "identifier",
        "typed_parameter",
        "default_parameter",
        "typed_default_parameter",
        "list_splat_pattern",
        "dictionary_splat_pattern",
    }
)


class _PythonSymbolSpec:
    """The language-specific hooks `extract_symbols` needs for Python."""

    def symbol_kind_for(self, node_type: str) -> SymbolKind | None:
        return _SYMBOL_NODE_TYPES.get(node_type)

    def extract_parameters(self, node: Node) -> tuple[Parameter, ...]:
        params_node = node.child_by_field_name("parameters")
        if params_node is None:
            return ()
        result: list[Parameter] = []
        for child in params_node.children:
            if child.type not in _PARAMETER_NODE_TYPES:
                continue
            parameter = _extract_parameter(child, len(result))
            if parameter is not None:
                result.append(parameter)
        return tuple(result)


def _extract_parameter(node: Node, position: int) -> Parameter | None:
    if node.type == "identifier":
        return Parameter(
            name=text_of(node), position=position, annotation=None, default_value=None
        )

    if node.type == "typed_parameter":
        # Grammar puts the bound identifier first, with no field name of its own —
        # only the `type` child is field-tagged.
        name_node = next((c for c in node.children if c.type == "identifier"), None)
        type_node = node.child_by_field_name("type")
        if name_node is None:
            return None
        return Parameter(
            name=text_of(name_node),
            position=position,
            annotation=text_of(type_node) if type_node is not None else None,
            default_value=None,
        )

    if node.type == "default_parameter":
        name_node = node.child_by_field_name("name")
        value_node = node.child_by_field_name("value")
        if name_node is None:
            return None
        return Parameter(
            name=text_of(name_node),
            position=position,
            annotation=None,
            default_value=text_of(value_node) if value_node is not None else None,
        )

    if node.type == "typed_default_parameter":
        name_node = node.child_by_field_name("name")
        type_node = node.child_by_field_name("type")
        value_node = node.child_by_field_name("value")
        if name_node is None:
            return None
        return Parameter(
            name=text_of(name_node),
            position=position,
            annotation=text_of(type_node) if type_node is not None else None,
            default_value=text_of(value_node) if value_node is not None else None,
        )

    if node.type in ("list_splat_pattern", "dictionary_splat_pattern"):
        # *args / **kwargs — bound name only, marker excluded (see Parameter.name's
        # documented contract in domain/parsing/entities.py).
        inner = next((c for c in node.children if c.type == "identifier"), None)
        if inner is None:
            return None
        return Parameter(
            name=text_of(inner), position=position, annotation=None, default_value=None
        )

    return None


def _name_children(node: Node) -> list[Node]:
    """Every child of `node` field-tagged `"name"` — `child_by_field_name` only
    returns the first match, but Python's grammar reuses the `"name"` field for
    every target in a multi-import (`import a, b`; `from x import a, b as c`)."""
    return [
        node.children[i]
        for i in range(len(node.children))
        if node.field_name_for_child(i) == "name"
    ]


def _make_import(
    node: Node,
    *,
    repository_id: UUID,
    file_path: str,
    module: str,
    imported_names: tuple[str, ...],
    alias: str | None,
) -> Import:
    location = location_of(node)
    return Import(
        id=deterministic_id(str(repository_id), file_path, module, str(location.start_line)),
        module=module,
        imported_names=imported_names,
        alias=alias,
        location=location,
    )


def _bare_imports(node: Node, *, repository_id: UUID, file_path: str) -> list[Import]:
    """`import a`, `import a.b as c`, `import a, b` — each target is a distinct
    module reference, so each produces its own `Import`."""
    result: list[Import] = []
    for name_node in _name_children(node):
        if name_node.type == "aliased_import":
            module_node = name_node.child_by_field_name("name")
            alias_node = name_node.child_by_field_name("alias")
            module = text_of(module_node) if module_node is not None else text_of(name_node)
            alias = text_of(alias_node) if alias_node is not None else None
        else:
            module = text_of(name_node)
            alias = None
        result.append(
            _make_import(
                node,
                repository_id=repository_id,
                file_path=file_path,
                module=module,
                imported_names=(),
                alias=alias,
            )
        )
    return result


def _from_import(node: Node, *, repository_id: UUID, file_path: str) -> Import | None:
    """`from a import b, c as d` / `from . import x` / `from a import *` — one
    module reference (`a`, or the relative-import text), with all pulled names
    bundled into `imported_names`. Per-name aliases within one `from` statement are
    not individually tracked (see domain/parsing/entities.py::Import.alias's
    documented scope) — Phase 4/5's `File --IMPORTS--> Module` edge cares which
    module was imported, not each local binding name."""
    module_node = node.child_by_field_name("module_name")
    if module_node is None:
        return None
    module = text_of(module_node)

    names: list[str] = []
    for name_node in _name_children(node):
        if name_node.type == "aliased_import":
            inner = name_node.child_by_field_name("name")
            if inner is not None:
                names.append(text_of(inner))
        else:
            names.append(text_of(name_node))
    # `wildcard_import` (the `*` in `from x import *`) isn't field-tagged `"name"`
    # in this grammar, unlike every other imported-name form — checked separately.
    if any(child.type == "wildcard_import" for child in node.children):
        names.append("*")

    return _make_import(
        node,
        repository_id=repository_id,
        file_path=file_path,
        module=module,
        imported_names=tuple(names),
        alias=None,
    )


def _extract_imports(node: Node, *, repository_id: UUID, file_path: str) -> tuple[Import, ...]:
    imports: list[Import] = []
    for import_node in find_all(node, _IMPORT_NODE_TYPES):
        if import_node.type == "import_statement":
            imports.extend(
                _bare_imports(import_node, repository_id=repository_id, file_path=file_path)
            )
        else:
            parsed = _from_import(import_node, repository_id=repository_id, file_path=file_path)
            if parsed is not None:
                imports.append(parsed)
    return tuple(imports)


class PythonParser:
    """`LanguageParser` for `.py` source."""

    language = Language.PYTHON

    def __init__(self) -> None:
        self._parser = get_parser("python")
        self._spec = _PythonSymbolSpec()

    def parse(self, *, repository_id: UUID, file_path: str, source: bytes) -> ParsedFile:
        try:
            tree = self._parser.parse(source)
        except Exception as exc:  # tree-sitter internal failure — rare, but a real
            # parser exception (not a syntax error, which it recovers from) is
            # exactly what ParseFailure exists for.
            raise ParseFailure(f"tree-sitter failed to parse {file_path!r}: {exc}") from exc

        root = tree.root_node
        symbols = extract_symbols(
            root, repository_id=repository_id, file_path=file_path, spec=self._spec
        )
        imports = _extract_imports(root, repository_id=repository_id, file_path=file_path)

        return ParsedFile(
            id=deterministic_id(str(repository_id), file_path),
            repository_id=repository_id,
            path=file_path,
            language=Language.PYTHON,
            symbols=symbols,
            imports=imports,
            has_syntax_errors=root.has_error,
        )
