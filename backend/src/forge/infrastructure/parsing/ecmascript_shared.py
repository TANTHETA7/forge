"""Shared plumbing between JavaScript and TypeScript — both grammars agree on
symbol node types and import-statement shape (TS's grammar is a superset of JS's
for these constructs, confirmed by probing both during planning), so this is
where that overlap lives rather than duplicating it in
javascript_parser.py/typescript_parser.py. Parameter *wrapper* shapes differ
(plain `identifier`/`assignment_pattern`/`rest_pattern` in JS vs.
`required_parameter`/`optional_parameter` wrapping a `pattern` field in TS) —
`pattern_name` below is the piece that IS shared between them (extracting a bound
name off a pattern node), used directly by JS and by TS's unwrapping logic.

Depends on:    tree_sitter, domain/parsing/entities.py,
                infrastructure/parsing/treesitter_support.py.
Depended on by: infrastructure/parsing/{javascript,typescript}_parser.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from forge.domain.parsing.entities import Import, SymbolKind
from forge.infrastructure.parsing.treesitter_support import (
    deterministic_id,
    find_all,
    location_of,
    text_of,
)

if TYPE_CHECKING:
    from tree_sitter import Node

SYMBOL_NODE_TYPES: dict[str, SymbolKind] = {
    "function_declaration": SymbolKind.FUNCTION,
    "class_declaration": SymbolKind.CLASS,
    "method_definition": SymbolKind.METHOD,
}

_IMPORT_NODE_TYPES = frozenset({"import_statement"})


def pattern_name(node: Node) -> str | None:
    """The bound name a parameter pattern introduces.

    `identifier` -> itself. `rest_pattern` (`...name`) -> the inner name, marker
    excluded (matching Parameter.name's documented contract). `object_pattern`/
    `array_pattern` (destructuring, e.g. `{a, b}`) -> the pattern's own source
    text verbatim, as a single synthetic name — Phase 3 doesn't expand a
    destructured parameter into one `Parameter` per bound name (out of the
    "extract at minimum" scope); the raw pattern is still visible rather than
    silently dropped.
    """
    if node.type == "identifier":
        return text_of(node)
    if node.type == "rest_pattern":
        inner = next((c for c in node.children if c.type == "identifier"), None)
        return text_of(inner) if inner is not None else None
    if node.type in ("object_pattern", "array_pattern"):
        return text_of(node)
    return None


def strip_type_annotation(node: Node | None) -> str | None:
    """TS's `type_annotation` node's text includes the leading `: ` (e.g.
    `": number"`) — stripped here so `Parameter.annotation` matches Python's
    style (`"int"`, not `": int"`)."""
    if node is None:
        return None
    text = text_of(node)
    return text.removeprefix(":").strip() or None


def extract_ecmascript_imports(
    root: Node, *, repository_id: UUID, file_path: str
) -> tuple[Import, ...]:
    """`import X from "m"`, `import { a, b as c } from "m"`, `import * as ns from
    "m"`, `import "m"` (side-effect only) — one `Import` per `import_statement`,
    combining any default/namespace bound name into `alias` and every named
    import's original (pre-alias) name into `imported_names`, mirroring the
    from-import treatment in python_parser.py: Phase 4/5's `File --IMPORTS-->
    Module` edge cares which module was imported, not each local binding name.
    """
    imports: list[Import] = []
    for node in find_all(root, _IMPORT_NODE_TYPES):
        source_node = node.child_by_field_name("source")
        if source_node is None:
            continue
        module = text_of(source_node).strip("\"'")

        alias: str | None = None
        imported_names: list[str] = []

        clause = next((c for c in node.children if c.type == "import_clause"), None)
        if clause is not None:
            for child in clause.children:
                if child.type == "identifier":
                    alias = text_of(child)
                elif child.type == "namespace_import":
                    inner = next(
                        (c for c in child.children if c.type == "identifier"), None
                    )
                    if inner is not None:
                        alias = text_of(inner)
                elif child.type == "named_imports":
                    for specifier in child.children:
                        if specifier.type != "import_specifier":
                            continue
                        name_node = specifier.child_by_field_name("name")
                        if name_node is not None:
                            imported_names.append(text_of(name_node))

        location = location_of(node)
        imports.append(
            Import(
                id=deterministic_id(
                    str(repository_id), file_path, module, str(location.start_line)
                ),
                module=module,
                imported_names=tuple(imported_names),
                alias=alias,
                location=location,
            )
        )
    return tuple(imports)
