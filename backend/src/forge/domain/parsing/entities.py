"""Normalized code-structure domain model — Phase 3 (extended in Phase 4).

Purpose:       Define what a "parsed file" is, independent of tree-sitter, any other
                parsing library, or persistence. This is the contract every
                `LanguageParser` implementation (infrastructure/parsing/*.py) must
                produce and every consumer (application/parsing/service.py, the
                persistence layer, the read API) works with — no tree-sitter `Node`
                object, or any other parser-library type, ever crosses out of
                infrastructure.
Responsibility: `ParsedFile`, `Symbol`, `Parameter`, `CallReference`, `Import`,
                `ParseError`, `ParseResult` — the full result of parsing one
                repository.

Why one `Symbol` entity instead of separate `Function`/`Class`/`Method` classes:
    the three share every field (name, qualified name, location, parameters) and
    differ only by `kind` and by whether `parent_symbol_id` is set — three near-
    identical classes would be duplication with no behavioral difference to justify
    it. A `Symbol` with `kind=METHOD` and `parent_symbol_id` pointing at its
    containing class *is* the nesting relationship later phases need (the brief's
    `File --CONTAINS--> Symbol` / future `Class --CONTAINS--> Method` sketch) —
    captured now, without building any graph traversal on top of it yet.

`Symbol.base_class_names` and `Symbol.calls` were added in Phase 4 (docs/
architecture/04-dependency-analysis.md) — Phase 3 originally recorded neither;
once dependency analysis needed to resolve CALLS/INHERITS relationships, these
were the minimum additional facts required, captured in the *same* tree-sitter
walk rather than a second parsing pass (see infrastructure/parsing/
treesitter_support.py). Both fields default to `()`, so no code that constructs
a `Symbol` without them breaks. Still deliberately NOT modeled: docstrings,
resolved types, or the *resolution* of a call/base-class name to a specific
target — that resolution is application/dependency_analysis's job, not the
parser's; `Symbol` only records the raw, unresolved facts it observed.

Depends on:    stdlib only.
Depended on by: domain/parsing/ports.py, infrastructure/parsing/*.py,
                application/parsing/service.py, infrastructure/persistence/
                parsed_file_repository_impl.py, api/parsing.py,
                domain/dependency_analysis/*.py (consumes `calls`/
                `base_class_names`, produces no changes here).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Language(StrEnum):
    """A language Forge can parse. Adding a new one (Java, Go, ...) means adding a
    value here, a new `LanguageParser` implementation, and a registry entry — no
    other domain or application code changes (see docs/architecture/03-parser-engine.md,
    "Extension strategy")."""

    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"


class SymbolKind(StrEnum):
    """What kind of definition a `Symbol` represents."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Where a symbol or import sits in its source file.

    Attributes:
        start_line: 1-based, inclusive.
        end_line: 1-based, inclusive.
        start_column: 0-based, when the parser reports it; `None` otherwise.
        end_column: 0-based, when the parser reports it; `None` otherwise.
    """

    start_line: int
    end_line: int
    start_column: int | None
    end_column: int | None


@dataclass(frozen=True, slots=True)
class Parameter:
    """One parameter of a `Symbol` whose kind is `FUNCTION` or `METHOD`.

    Attributes:
        name: Parameter name. For `*args`/`**kwargs`-style parameters this is the
            bound name (`args`, `kwargs`), not including the `*`/`**` marker.
        position: 0-based ordinal position in the parameter list.
        annotation: The type annotation's source text, verbatim, if the language
            and this parameter have one (e.g. `"int"`, `"string"`). No type
            resolution happens in Phase 3 — this is display/reference text only.
        default_value: The default expression's source text, verbatim, if present.
    """

    name: str
    position: int
    annotation: str | None
    default_value: str | None


@dataclass(frozen=True, slots=True)
class CallReference:
    """One call expression found inside a `FUNCTION`/`METHOD` symbol's body —
    added in Phase 4 (docs/architecture/04-dependency-analysis.md) to give
    dependency analysis a CALLS relationship to resolve, without a second
    parsing pass: captured in the same tree-sitter walk Phase 3 already does.

    Attributes:
        callee_expression: The call's raw target text, verbatim — `"helper"`,
            `"self.method_b"`, `"obj.attr.method"`, `"module.func"`. Not
            resolved here; resolving it to a specific `Symbol` (or determining
            it can't be, e.g. an arbitrary object attribute chain) is
            application/dependency_analysis's job, not the parser's.
        location: Where this call expression sits in its file.
    """

    callee_expression: str
    location: SourceLocation


@dataclass(frozen=True, slots=True)
class Symbol:
    """One function, class, or method definition found in a parsed file.

    Attributes:
        id: Deterministic — `uuid5` of `(repository_id, file_path, qualified_name,
            kind)`. Stable across re-parses of unchanged source, which is what lets
            later phases reference a symbol consistently and lets persistence
            treat re-parsing as idempotent.
        kind: FUNCTION, CLASS, or METHOD.
        name: The symbol's own name (e.g. `"method_a"`), not dotted.
        qualified_name: A dotted, file-scoped path (e.g. `"Foo.method_a"`) — human-
            readable context, not a global identifier on its own. Two files can
            each have a symbol with the same `qualified_name`; global uniqueness
            comes from `id`, which folds in `file_path` too.
        location: Where this definition sits in its file.
        parameters: Empty for `CLASS`; the parameter list for `FUNCTION`/`METHOD`.
        parent_symbol_id: For a `METHOD`, the `id` of its containing `CLASS`
            symbol. `None` for top-level functions and for classes themselves.
        base_class_names: Populated only for `CLASS` — the raw text of each
            base-class expression (`"Base"`, `"pkg.Base"`), verbatim, in source
            order. Empty for `FUNCTION`/`METHOD`. Not resolved to a specific
            `Symbol` here — see `CallReference.callee_expression`'s note; the
            same division of labor applies (Phase 4 resolves, Phase 3 records
            the raw fact).
        calls: Populated only for `FUNCTION`/`METHOD` — every call expression
            found in this symbol's body. Empty for `CLASS`.
    """

    id: UUID
    kind: SymbolKind
    name: str
    qualified_name: str
    location: SourceLocation
    parameters: tuple[Parameter, ...]
    parent_symbol_id: UUID | None
    base_class_names: tuple[str, ...] = ()
    calls: tuple[CallReference, ...] = ()


@dataclass(frozen=True, slots=True)
class Import:
    """One import statement found in a parsed file.

    Attributes:
        id: Deterministic — `uuid5` of `(repository_id, file_path, module,
            start_line)`. Imports have no natural unique name, so the location
            disambiguates repeated imports of the same module in one file.
        module: The raw imported-from text, verbatim — e.g. `"os.path"`,
            `"./utils"`, `"react"`. Not resolved to a file or package in Phase 3.
        imported_names: Names pulled from the module, e.g. `("path",)` for
            `from os import path`, or `("useState",)` for
            `import { useState } from "react"`. Empty for a bare `import os` /
            `import Default from "./x"` (the bound name for a default/namespace
            import is `alias`, not `imported_names`).
        alias: The local bound name, when the import introduces exactly one name
            directly (`import os as o` -> `"o"`; `import Default from "./x"` ->
            `"Default"`). `None` for multi-name imports.
        location: Where this import statement sits in its file.
    """

    id: UUID
    module: str
    imported_names: tuple[str, ...]
    alias: str | None
    location: SourceLocation


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """The structural extraction result for one source file.

    Attributes:
        id: Deterministic — `uuid5` of `(repository_id, path)`.
        repository_id: The owning `Repository`'s id (domain/repository/entities.py).
        path: Workspace-relative, forward-slash-normalized — never an absolute
            filesystem path (see infrastructure/parsing/file_discovery.py for why).
        language: The language this file was parsed as.
        symbols: Every function/class/method found, in source order.
        imports: Every import statement found, in source order.
        has_syntax_errors: `True` if the source had a syntax error tree-sitter
            recovered from — `symbols`/`imports` still reflect whatever *could*
            be extracted around the error (tree-sitter's error recovery keeps
            parsing the rest of the file), this just flags the result as
            best-effort rather than a clean parse. Distinct from a `ParseError`:
            a syntax error still produces a usable `ParsedFile`, so it's a
            property of the file, not a separate failure record.
    """

    id: UUID
    repository_id: UUID
    path: str
    language: Language
    symbols: tuple[Symbol, ...]
    imports: tuple[Import, ...]
    has_syntax_errors: bool


@dataclass(frozen=True, slots=True)
class ParsedFileSummary:
    """The file-level projection used by ``GET .../files``.

    This deliberately contains counts rather than child entities.  Listing files
    must not construct every symbol, parameter, call site, and import merely to
    calculate the two counts exposed by the endpoint.
    """

    id: UUID
    repository_id: UUID
    path: str
    language: Language
    has_syntax_errors: bool
    symbol_count: int
    import_count: int


@dataclass(frozen=True, slots=True)
class ParseError:
    """One file that could not be (fully) parsed, recorded rather than raised —
    see domain/errors.py::ParseFailure for the exception this is built from.

    Attributes:
        file_path: Workspace-relative path of the file that failed.
        stage: Which pipeline stage the failure happened at — `"read"` (couldn't
            read the file), `"detect"` (language detection produced nothing
            usable), `"parse"` (the language parser raised `ParseFailure`).
        message: Human-readable detail, safe to display — never a raw exception
            traceback or a filesystem path outside the workspace.
    """

    file_path: str
    stage: str
    message: str


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    """One candidate file found while walking a workspace, read and ready to hand
    to a `LanguageParser` — produced by a `FileDiscovery` port implementation
    (infrastructure/parsing/file_discovery.py)."""

    relative_path: str
    content: bytes


@dataclass(frozen=True, slots=True)
class SkippedFile:
    """One file a `FileDiscovery` did not hand off, and why.

    Attributes:
        relative_path: Workspace-relative path of the excluded file.
        reason: Human-readable detail.
        stage: `None` for a deliberate policy skip (binary, oversized) — not a
            failure, nothing to record. Set to `"read"` when the exclusion was
            an actual I/O failure (couldn't stat or read the file) — the caller
            should record this as a `ParseError`.
    """

    relative_path: str
    reason: str
    stage: str | None = None


@dataclass(frozen=True, slots=True)
class ParseResult:
    """The complete outcome of parsing one repository's workspace.

    Attributes:
        repository_id: The `Repository` that was parsed.
        files: Every file that parsed successfully (even partially — a file with
            recoverable syntax errors still contributes whatever tree-sitter could
            extract, alongside a `ParseError` entry for the same file).
        errors: Every file that failed at any stage, or partially failed.
        parsed_at: When this parse run completed (UTC).
    """

    repository_id: UUID
    files: tuple[ParsedFile, ...]
    errors: tuple[ParseError, ...]
    parsed_at: datetime
