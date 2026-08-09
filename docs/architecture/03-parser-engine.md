# Forge — Phase 3: Code Parser / Code Intelligence Engine

> Status: **Complete**. Takes a Phase 2 `READY` repository's isolated workspace and
> produces a normalized, queryable structural model (files, classes, functions,
> methods, imports, parameters) in PostgreSQL. Neo4j stays untouched — this is the
> input Phase 4 (dependency analysis) and Phase 5 (knowledge graph construction)
> build on, not the graph itself. Nothing in Phase 1 or Phase 2 changed shape to
> support this; two Phase 2 files got a small, behavior-preserving refactor (see
> §9).

## 1. Why tree-sitter, and why not something else

Tree-sitter, uniformly, for Python/JavaScript/TypeScript — evaluated and decided
*before* writing any parser code, not defaulted to because it happened to be
available.

**What was actually checked**, empirically, in this environment, before deciding:

- `tree_sitter_language_pack.get_parser("python"|"javascript"|"typescript")` all
  load correctly. This cost **zero new dependencies** — `tree-sitter` and
  `tree-sitter-language-pack` were declared in `backend/pyproject.toml` back in
  Phase 1 specifically as a forward-looking dependency, installed and sitting
  unused in `.venv` until this phase.
- Probing the actual grammar output for all three languages showed their node
  **field names** (`name`, `parameters`, `body`, `return_type`) are consistent
  even though node *type* names differ per language (Python's
  `function_definition` covers both functions and methods; JS/TS have a
  dedicated `method_definition`). This is what makes one shared extraction
  *pattern* — walk by field name, plus one generic "a function found while
  inside a class is a METHOD" rule — drive three thin per-language adapters
  instead of three unrelated implementations (see §3).
- Tree-sitter's error recovery is real and was verified directly: parsing a
  Python file with a broken `def` followed by a valid `class` produces
  `tree.root_node.has_error == True` while still correctly extracting the valid
  class. This is the mechanism behind requirement 21 (one file's syntax error
  can't destroy the repository's parse) — see §7.
- `tree_sitter_language_pack` already bundles grammars for Java, C, C++, Go, and
  Rust. Adding any of those later is a new thin adapter on the *same*
  dependency and the *same* architecture, not new tooling.

**Rejected alternative**: Python's stdlib `ast` module for Python, plus a
separate JavaScript/TypeScript parsing library. Rejected because it means two
different parsing technologies with two different tree shapes to normalize from
on day one, doesn't extend to Java/C/C++/Go/Rust without a third or fourth
technology, and — the deciding factor — introduces a genuinely *new* dependency
for JS/TS where tree-sitter introduces none. `ast` is not used anywhere in this
codebase.

## 2. Pipeline and layering

```
Repository (Phase 2, already READY)
        │  Repository.workspace_path — never a client-supplied path
        ▼
Workspace                                    domain/repository/entities.py
        │
        ▼
File Discovery                               infrastructure/parsing/file_discovery.py
        │  walk_workspace() (shared with the Phase 2 metadata scanner, §9),
        │  skip binary/oversized files
        ▼
Language Detection                           infrastructure/parsing/language_detection.py
        │  extension -> Language, or None (unsupported — silent skip)
        ▼
Parser Registry                              infrastructure/parsing/registry.py
        │  Language (+ .tsx special case) -> LanguageParser instance
        ▼
Language Parser (tree-sitter)                infrastructure/parsing/{python,javascript,typescript}_parser.py
        │  concrete syntax tree -> Forge's normalized model
        ▼
Normalized Code Model                        domain/parsing/entities.py
        │  ParsedFile, Symbol, Parameter, Import, ParseError, ParseResult
        ▼
PostgreSQL                                   infrastructure/persistence/{parsing_models,parsed_file_repository_impl}.py
        ▼
Read APIs                                    api/parsing.py
```

Layer boundary, same rule Phase 2 already established: `api → application →
domain ← infrastructure`. `application/parsing/service.py` (`ParsingService`)
never imports tree-sitter, `pathlib` filesystem operations, or SQLAlchemy
directly — it depends only on the four ports `domain/parsing/ports.py` defines:

| Port | Implemented by | Purpose |
|---|---|---|
| `LanguageParser` | `PythonParser`, `JavaScriptParser`, `TypeScriptParser` | Parse one file's bytes into a `ParsedFile`. |
| `ParserRegistry` | `DefaultParserRegistry` | File path -> the right `LanguageParser`, or `None`. |
| `FileDiscovery` | `FilesystemFileDiscovery` | Walk a workspace, yielding file content or why a file was excluded. |
| `ParsedFileRepository` | `SqlAlchemyParsedFileRepository` | Persist/query a repository's parse results. |

`api/parsing.py` is the one place that constructs the concrete
`FilesystemFileDiscovery`/`DefaultParserRegistry`/parser instances — the exact
same pattern `api/repositories.py` already uses for `ZipRepositorySource`/
`GitRepositorySource`.

## 3. The parser abstraction and language adapters

Each `LanguageParser` is a small class: a `language: Language` attribute the
registry matches on, and a `parse(*, repository_id, file_path, source: bytes) ->
ParsedFile` method. No tree-sitter type (`Node`, `Tree`, `Parser`) crosses out of
`infrastructure/parsing/` — every consumer, including tests, works with
`domain/parsing/entities.py`'s plain dataclasses.

Shared plumbing lives in two places, split by how broadly it's shared:

- **`treesitter_support.py`** — language-agnostic: 0-based-`Point`-to-1-based-
  `SourceLocation` conversion, source-text extraction, deterministic id
  generation (`uuid5`), and `extract_symbols` — the generic walker that owns
  recursion and class-nesting tracking. Each `LanguageParser` supplies a small
  `SymbolExtractionSpec` (a node-type -> `SymbolKind` map, and a parameter
  extractor); `extract_symbols` does the rest, including the "a function found
  while inside a class body becomes a METHOD" rule that makes Python's single
  `function_definition` node type come out right without any Python-specific
  code in the shared walker.
- **`ecmascript_shared.py`** — shared between JavaScript and TypeScript
  specifically (their grammars agree on symbol node types and import-statement
  shape; TypeScript's is a superset), not general enough for
  `treesitter_support.py`: the `SYMBOL_NODE_TYPES` map, `extract_ecmascript_imports`,
  and `pattern_name` (extracting a bound name off a parameter pattern node,
  reused by both JS's plain parameters and TS's wrapped `required_parameter`/
  `optional_parameter` nodes).

Each language's own file (`python_parser.py`, `javascript_parser.py`,
`typescript_parser.py`) is left with only what's genuinely language-specific:
Python's two import-statement node types (`import_statement` /
`import_from_statement`, with their own alias/relative/wildcard handling) versus
JS/TS's single `import_statement`; Python's six parameter node shapes
(`identifier`, `typed_parameter`, `default_parameter`,
`typed_default_parameter`, `list_splat_pattern`, `dictionary_splat_pattern`)
versus JS's plain patterns and TS's typed wrapper nodes.

`.tsx` shares `Language.TYPESCRIPT` (there's no separate "TSX" language from any
consumer's point of view) but needs the distinct `tsx` tree-sitter grammar, not
`typescript` — `TypeScriptParser(tsx=True)` selects it, and `registry.py`'s
`DefaultParserRegistry` routes by file extension (via
`language_detection.is_tsx`), not just by `Language`, to pick the right
instance.

## 4. Normalized code model

One `Symbol` entity with a `kind` discriminator (`FUNCTION | CLASS | METHOD`)
instead of separate `Function`/`Class`/`Method` classes — the three share every
field (name, qualified name, location, parameters) and differ only by `kind` and
by whether `parent_symbol_id` is set. A `METHOD`'s `parent_symbol_id` pointing at
its containing `CLASS` symbol *is* the nesting relationship the brief's own
Phase 4/5 sketch calls for (`File --CONTAINS--> Symbol`, and eventually `Class
--CONTAINS--> Method`) — captured now, with no graph traversal logic built on
top of it yet.

```
ParseResult
  ├── repository_id, parsed_at
  ├── files: tuple[ParsedFile, ...]
  │     ├── id, repository_id, path (workspace-relative), language
  │     ├── has_syntax_errors: bool   — see §7
  │     ├── symbols: tuple[Symbol, ...]
  │     │     ├── id, kind, name, qualified_name
  │     │     ├── location: SourceLocation (1-based start/end line, 0-based columns)
  │     │     ├── parameters: tuple[Parameter, ...]
  │     │     └── parent_symbol_id: UUID | None   — METHOD -> containing CLASS
  │     └── imports: tuple[Import, ...]
  │           ├── id, module, imported_names, alias, location
  └── errors: tuple[ParseError, ...]
        └── file_path, stage ("read" | "detect" | "parse"), message
```

**Stable identifiers**: every `id` is a deterministic `uuid5` derived from
`(repository_id, file_path, ...)` — a `ParsedFile.id` from `(repository_id,
path)`, a `Symbol.id` from `(repository_id, file_path, qualified_name, kind)`.
Re-parsing unchanged source produces the same ids. `Parameter` and `ParseError`
have no `id` of their own — neither is independently referenced by anything;
both are always reached through their owning `Symbol`/`ParseResult` (their ORM
rows still need a primary key for Postgres, minted at insert time — see §5).

**Deliberately not modeled**: docstrings, resolved types, call graphs, cross-file
symbol references. None are in the "extract at minimum" scope, and adding them
now would be exactly the premature-feature risk the brief warns against.
`qualified_name` and `parent_symbol_id` are the only forward-looking fields, and
both are required by the brief's own relationship sketch, not speculative
additions.

## 5. Persistence model

Five new tables, on the *existing* `Base`/`create_all` mechanism from Phase 2 —
no Alembic, consistent with `infrastructure/persistence/models.py`'s
already-documented deferral:

```sql
parsed_files(id, repository_id FK, path, language, has_syntax_errors, parsed_at,
             UNIQUE(repository_id, path))
symbols(id, file_id FK->parsed_files ON DELETE CASCADE, repository_id FK,
        parent_symbol_id FK->symbols NULL, kind, name, qualified_name,
        start_line, end_line, start_column NULL, end_column NULL)
parameters(id, symbol_id FK->symbols ON DELETE CASCADE, name, position,
           annotation NULL, default_value NULL)
imports(id, file_id FK->parsed_files ON DELETE CASCADE, repository_id FK,
        module, imported_names JSON, alias NULL, start_line, end_line)
parse_errors(id, repository_id FK, file_path, stage, message, occurred_at)
```

`repository_id` is denormalized onto `symbols`/`imports` (also reachable via
`file_id`) so the common read-API case — "every symbol for this repository" —
doesn't require a join.

Every datetime column picks up `TIMESTAMP WITH TIME ZONE` automatically from
`Base.type_annotation_map` (added while fixing an earlier tz-naive-column bug) —
no repeat of that bug was possible here by construction, and
`tests/unit/test_persistence_models.py` asserts this structurally for every
table, current and future.

**Re-parsing is replace, not merge.** `SqlAlchemyParsedFileRepository.
save_parse_result` deletes a repository's `parse_errors` and `parsed_files` rows
first — the latter cascades (`ON DELETE CASCADE`) through `symbols` down to
`parameters`, and through to `imports` — then inserts the new result. There is
no Phase 3 requirement for incremental/partial persistence; a real incremental
re-parse (only re-parsing files whose content changed) is a natural future
enhancement building on Phase 2's existing per-file `FileHash` mechanism, not
built now.

Inserts happen in explicit staged flushes (files, then symbols, then
parameters+imports) rather than one flush — these ORM rows use plain `ForeignKey`
columns with no `relationship()` declared, so nothing guarantees SQLAlchemy's
automatic insert ordering sequences parent-before-child correctly within a single
flush; each stage is flushed before the next one is added, verified against real
Postgres in `tests/integration/test_postgres_parsing_persistence.py`.

## 6. API

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/projects/{project_id}/repositories/{repository_id}/parse` | Synchronous, mirrors Phase 2's import endpoints. `409` if the repository isn't `READY`. Idempotent — replaces any previous result. |
| `GET` | `.../repositories/{repository_id}/files` | Per-file summary (symbol/import *counts*, not the full lists). |
| `GET` | `.../repositories/{repository_id}/symbols?kind=&file_id=&limit=&offset=` | Paginated — a real repository can have thousands of symbols. |
| `GET` | `.../repositories/{repository_id}/symbols/{symbol_id}` | Full detail: parameters, `parent_symbol_id`. |
| `GET` | `.../repositories/{repository_id}/parse-errors` | Inspectable after the fact, not only in the `POST` response. |

**Trigger decision**: parsing is a separate, explicit `POST .../parse` call, not
auto-chained onto Phase 2's `RepositoryImportService.import_repository()`. This
was a deliberate choice (confirmed before implementation): it keeps Phase 2's
already-tested orchestration completely untouched, keeps import fast, and makes
parsing independently re-runnable later (e.g. after a new language is added)
without re-importing.

**Deliberately not added**: a dedicated imports-listing endpoint. Imports are
persisted (Phase 4/5 need them) but no concrete Phase 3 use case calls for
browsing them independently yet — matches "only implement endpoints justified by
actual use cases."

## 7. Error handling

Three distinct outcomes for a file, corresponding to three distinct pieces of
data — not conflated into one:

1. **Silent skip, no record** — unsupported language (`ParserRegistry.
   parser_for` returns `None`), or `FileDiscovery`'s own policy skips (binary-
   looking, over `max_parse_file_bytes`). These are expected, routine outcomes,
   not failures.
2. **Recoverable syntax error, still a usable file** — tree-sitter's error
   recovery means a syntax error rarely prevents extracting *something*. The
   file still gets a normal `ParsedFile` with whatever symbols/imports survived
   extraction, flagged via `ParsedFile.has_syntax_errors = True`. Verified
   directly: a Python file with a broken `def` followed by a valid `class`
   still yields that class as an extracted symbol.
3. **Real failure, recorded as a `ParseError`** — couldn't read the file
   (`stage="read"`), or the language parser raised `ParseFailure` or any other
   exception (`stage="parse"`, message wrapped, not the raw traceback). One
   file's failure is caught in `ParsingService._parse_one` and the loop
   continues — verified in
   `tests/unit/test_parsing_service.py::test_one_bad_file_does_not_abort_the_rest_of_the_repository`
   by monkeypatching `PythonParser.parse` to always raise and confirming a
   second, good file in the same repository still parses successfully.

Only two things abort the whole run: the `Repository` not existing
(`NotFoundError`, 404), or it not being `READY` (`UnsupportedRepositoryStateError`,
409) — both are checked before any file is touched, since there's no
materialized workspace to walk otherwise.

## 8. Security considerations

- **Never a client-supplied path.** `FileDiscovery.discover(workspace)` takes
  whatever `Path` its caller passes; it never resolves anything from client
  input itself. The one legitimate caller, `ParsingService.parse_repository`,
  always passes `Repository.workspace_path` — set exactly once, by Phase 2's
  `WorkspaceProvider`, from server-generated UUIDs, never from a project or
  repository name.
- **Symlinks are never followed.** Phase 2's ZIP importer already rejects
  symlink entries at extraction time, but `git clone` does not go through that
  hardening — a cloned repository can legitimately contain a symlink pointing
  outside the workspace. `infrastructure/filesystem/workspace_walker.py`'s
  shared walk (used by both the Phase 2 metadata scanner and Phase 3's file
  discovery, see §9) refuses to follow or yield any symlink, closing this gap
  for both.
- **No code execution.** Tree-sitter parses a grammar; it never executes
  anything in the source it's given. This holds even for a `.py` file that
  itself contains `import os; os.system(...)` — Forge never runs the file, only
  walks its syntax tree.
- **Bounded memory.** `max_parse_file_bytes` (default 5 MiB, `core/config.py`)
  causes a single oversized file to be skipped rather than fully read into
  memory. No repository-wide cap is added in Phase 3 beyond what Phase 2
  already enforces at import time (archive size/file-count limits).

## 9. Two small, behavior-preserving Phase 2 touches

Both were extractions of existing logic into a shared location, not new
behavior — each has full pre-existing test coverage that passed unchanged
afterward, with zero edits to the test files themselves.

- **`infrastructure/scanner/metadata_scanner.py`** — its private `_walk`/
  `_IGNORED_DIR_NAMES` moved to the new shared
  `infrastructure/filesystem/workspace_walker.py` (used by both the scanner and
  Phase 3's `FileDiscovery`), gaining the symlink-skip behavior from §8 as a
  side effect. `tests/unit/test_metadata_scanner.py` — 7/7 unchanged, passing.
- **`infrastructure/persistence/dependencies.py`** — one new provider function,
  `get_parsed_file_repository`, added alongside the existing
  `get_project_repository`/`get_repository_repository`, same pattern.

Phase 2's `RepositoryImportService`, its API routes, and every Phase 1 file were
not touched.

## 10. Extension strategy for new languages

Adding Java, Go, C, C++, or Rust (all already bundled in
`tree_sitter_language_pack`) means, in order:

1. A new `Language` enum member (`domain/parsing/entities.py`).
2. A new thin `LanguageParser` in `infrastructure/parsing/`, following
   `python_parser.py`'s shape: a `SymbolExtractionSpec` (node-type map + a
   parameter extractor) passed to the shared `extract_symbols`, plus that
   language's own import-statement handling.
3. One new extension-map entry in `language_detection.py`.
4. One new constructor parameter + map entry in `DefaultParserRegistry`
   (`registry.py`), and one new line wherever the registry is constructed
   (`api/parsing.py::get_parsing_service`).

No change to `domain/parsing/ports.py`, `application/parsing/service.py`,
`api/parsing.py`'s route handlers, or the persistence layer — every layer above
"which grammar recognizes which node types" is already language-agnostic.

## 11. Testing

Same discipline as Phase 2: fast, pure unit tests for parsers/registry/discovery
(zero I/O beyond literal source strings or `tmp_path`), fakes-backed application
and API tests (`tests/fakes.py::InMemoryParsedFileRepository`, mirroring the
existing `InMemoryProjectRepository`/`InMemoryRepositoryRepository`), and real
PostgreSQL integration tests (`tests/integration/test_postgres_parsing_persistence.py`)
using the shared `postgres_schema` fixture — extracted into
`tests/integration/conftest.py` from Phase 2's `test_postgres_persistence.py` so
Phase 3's two new Postgres-backed test files don't each carry their own copy.

`tests/integration/test_real_repository_parsing.py` is the single test that
proves the whole pipeline for real, nothing mocked: builds a fixture ZIP with
nested directories, mixed Python/JavaScript/TypeScript files, three functions
all named `helper` across different files and languages, a binary file, and an
unsupported file type; imports it through the real (unmodified) Phase 2 ZIP-import
flow; calls the real `POST .../parse`; asserts against real Postgres rows —
including that the three `helper` symbols get three distinct stable ids, and
that the `.png` and `.md` files are silently absent rather than errored.
