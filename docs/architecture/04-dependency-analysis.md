# Phase 4 — Dependency Analysis Engine

This document describes the Phase 4 implementation as it actually exists in
the codebase. It does not describe aspirational or future behavior; where a
capability is deliberately not implemented, it is called out under "Known
limitations" rather than implied elsewhere.

## 1. Purpose and scope

Phase 3 (`infrastructure/parsing/*`) turns source files into a normalized,
unconnected model: `ParsedFile`, `Symbol`, `Parameter`, `Import`. It records
*what exists* in a repository but not *how the pieces relate to each other*.

Phase 4 turns that normalized data into explicit, queryable relationships —
`DependencyEdge` rows — for a fixed, deliberately bounded set of relationship
kinds:

- **File → File**, via imports (`DependencyKind.IMPORTS`)
- **Function/Method → Function/Method**, via calls (`DependencyKind.CALLS`)
- **Class → Class**, via inheritance (`DependencyKind.INHERITS`)

A fourth kind, `DependencyKind.REFERENCES`, is declared in the domain model
for forward extensibility but **no resolver produces it in this phase** — see
§12.

Every relationship Phase 4 finds is recorded with one of three explicit
resolution outcomes — `RESOLVED`, `AMBIGUOUS`, or `UNRESOLVED` — never
silently guessed and never silently dropped. This three-state model is the
central design decision of this phase (§5).

Language scope: **Python, JavaScript, TypeScript** — the same three languages
Phase 3 parses. The resolver architecture (§3) is structured to admit more
languages later without redesign, but no additional language is implemented
now.

## 2. Relationship to Phase 3

Phase 4 is a strictly downstream consumer of Phase 3's data:

- It reuses Phase 3's `ParsedFileRepository` to load already-parsed
  `ParsedFile`/`Symbol`/`Import` rows from PostgreSQL. It does not read
  repository source files from disk, and it does not invoke tree-sitter or
  any `LanguageParser` — all of that happened once, during `/parse`.
- It requires a repository to be `READY` **and already parsed** (i.e.
  `POST .../parse` must have run and produced at least one `ParsedFile`)
  before `POST .../analyze-dependencies` can run. Calling analysis on a
  `READY` but unparsed repository is rejected with `409 Conflict`.

**The one Phase 3 change this phase required**: Phase 3's original `Symbol`
model captured function/class/method *definitions* but not their *bodies'*
call expressions or a class's base-class expressions — there was nothing for
CALLS/INHERITS to resolve. Rather than add a second parsing pass, Phase 3's
existing tree-sitter walk (`infrastructure/parsing/treesitter_support.py`'s
`extract_symbols`) was extended with two additional, per-symbol extraction
hooks:

- `Symbol.base_class_names: tuple[str, ...]` — populated only for `CLASS`
  symbols; the raw text of each base-class expression, verbatim, in source
  order (e.g. `"Base"`, `"pkg.Base"`).
- `Symbol.calls: tuple[CallReference, ...]` — populated only for
  `FUNCTION`/`METHOD` symbols; every call expression found in that symbol's
  body, as a `CallReference(callee_expression, location)` (e.g.
  `"helper"`, `"self.method_b"`, `"obj.attr.method"`, `"module.func"`).

Both fields default to `()`, so every previously-existing `Symbol(...)`
call site (tests, persistence, API mapping) continues to work unchanged.
Phase 3's parser is responsible only for capturing this raw text — it does
not resolve `callee_expression` or a base-class name to a specific `Symbol`;
that resolution is entirely Phase 4's job (§4).

No other Phase 1–3 behavior was changed. `IMPORTS` resolution needed no
Phase 3 change at all — `Import.module`/`imported_names`/`alias`/`location`
were already fully captured.

## 3. Dependency analysis pipeline

```
POST /parse   (Phase 3, prerequisite — not re-run by Phase 4)
      │
      ▼
PostgreSQL: parsed_files, symbols, parameters, call_sites
      │
      ▼
POST /analyze-dependencies
      │
      ▼
application/dependency_analysis/service.py :: DependencyAnalysisService
      │  1. load the Repository, verify READY
      │  2. load all ParsedFiles (+ Symbols, Imports) via ParsedFileRepository
      │  3. for each file's imports        -> resolve via ModuleResolver
      │     for each class's base classes  -> resolve via SymbolDependencyResolver
      │     for each function/method's calls -> resolve via SymbolDependencyResolver
      │  4. build a DependencyEdge per relationship (deterministic id, §9)
      │  5. persist the full edge set (replace-on-rerun, §10)
      ▼
PostgreSQL: dependency_edges
      │
      ▼
GET /dependencies, GET /dependencies/{id}
```

`DependencyAnalysisService` is pure orchestration and in-memory computation
plus async database calls — it performs no filesystem I/O, no subprocess
calls, and no tree-sitter parsing.

### Layering

```
api/dependencies.py
      │  thin HTTP translation only
      ▼
application/dependency_analysis/service.py     DependencyAnalysisService
      │  orchestration; depends on ports only
      ▼
domain/dependency_analysis/{entities,ports,ids}.py
      │  DependencyEdge, DependencyKind, ResolutionStatus, SymbolResolution
      │  ModuleResolver (port), DependencyEdgeRepository (port)
      ▼
infrastructure/dependency_analysis/*.py        PythonModuleResolver,
      │                                         EcmaScriptModuleResolver,
      │                                         CompositeModuleResolver,
      │                                         SymbolDependencyResolver
      ▼
infrastructure/persistence/{dependency_models,dependency_edge_repository_impl}.py
```

Two different abstraction shapes are used deliberately:

- **`ModuleResolver` is a `Protocol` (domain port) with one implementation
  per language** (`PythonModuleResolver`, `EcmaScriptModuleResolver`,
  dispatched by `CompositeModuleResolver` based on `ParsedFile.language`) —
  resolving an `Import.module` string to a file is genuinely
  language-specific: Python's dotted-absolute/leading-dot-relative syntax
  differs from JS/TS's relative-path-with-extension-trial syntax.
- **`SymbolDependencyResolver` (CALLS + INHERITS) is a single concrete
  class, not a port with per-language implementations.** Once Phase 3 has
  normalized a call site or base class down to raw text, resolving it is the
  *same* algorithm regardless of source language — same-file lookup,
  import-binding lookup, an instance-prefixed (`self.`/`this.`) lookup
  against the enclosing class. The one place a genuinely language-specific
  decision still matters — how `module.func()`'s `module` segment resolves —
  is delegated to the injected `ModuleResolver` rather than duplicated.
  `self.` and `this.` prefixes are both checked unconditionally regardless
  of source language, which is harmless (a Python file will never contain a
  `this.`-prefixed call) and keeps the class language-agnostic.

## 4. Import resolution

Implemented by `PythonModuleResolver` and `EcmaScriptModuleResolver`
(`infrastructure/dependency_analysis/`), both matching purely against the
repository's already-parsed file paths — no filesystem access.

**Python** (`PythonModuleResolver`):
- A leading-dot module (`from .models import User`, `from ..pkg.mod import
  X`) is resolved relative to the importing file's own directory: one `.`
  means "this package," each additional `.` steps one directory further up.
- An absolute dotted module (`import a.b.c`) is resolved by converting dots
  to path segments and matching against the repository's parsed Python
  files.
- Either form matches against `<path>.py` or `<path>/__init__.py`.
- A **bare-dot import with no further dotted path** (`from . import x`)
  treats each name in `imported_names` as a candidate sibling submodule
  file. If exactly one name is imported this resolves normally; if more than
  one name is imported (`from . import a, b`), the single `Import` record
  cannot represent two distinct target files, so this resolves
  **AMBIGUOUS** — a stated scope limitation, not a silent guess.
- Zero matching files → **UNRESOLVED** (`detail` explains it's likely an
  external or standard-library module — the common, expected case, not a
  defect). More than one matching file (e.g. both `a/b.py` and
  `a/b/__init__.py` present) → **AMBIGUOUS**.

**JavaScript/TypeScript** (`EcmaScriptModuleResolver`, shared by both
languages — they use identical ESM relative-import syntax):
- Only specifiers starting with `.` are resolved against repository files.
  A bare/package specifier (`"react"`, `"lodash"`) is **always UNRESOLVED**
  — under ESM convention a non-relative specifier always resolves through
  `node_modules`, never to a sibling source file, so it is never even
  attempted against the file set. A bundler/tsconfig path alias
  (`"@app/utils"`) is not modeled — Forge has no config-file parsing to
  learn such a mapping from, so it correctly comes out UNRESOLVED rather
  than a guessed match.
- Relative specifiers are resolved against the importing file's directory
  (via `posixpath.normpath`, which does real `../`/`./` collapsing —
  verified not to happen automatically with `pathlib.PurePosixPath`'s `/`
  operator), trying each of `.ts`, `.tsx`, `.js`, `.jsx` as a direct file,
  and each as a `/index.<ext>` directory-module file.
- Zero matches → UNRESOLVED. More than one match → AMBIGUOUS.

**Circular imports need no special handling.** Resolving file A's import of
file B is a single path-match lookup against B's own known path — it never
recursively walks B's own imports. A circular pair (A imports B, B imports
A) simply produces two independent, correctly RESOLVED edges. This was
verified directly by the real end-to-end test (§14).

## 5. Resolved / Ambiguous / Unresolved

`ResolutionStatus` (`domain/dependency_analysis/entities.py`) is the outcome
recorded on every `DependencyEdge`, for every kind:

- **`RESOLVED`** — exactly one plausible target was found.
- **`AMBIGUOUS`** — more than one equally-plausible target was found (e.g.
  two different wildcard imports both defining a same-named symbol; a bare
  relative import naming multiple submodules at once). Never collapsed down
  to a single guessed answer.
- **`UNRESOLVED`** — no target was found in the repository. This is the
  normal, expected outcome for a great many real edges (external package
  imports, standard-library imports, calls whose receiver type isn't
  statically known) — not a failure state.

Every `DependencyEdge` always carries `raw_target_expression` (the original
module path / callee text / base-class text) regardless of status, and a
human-readable `detail` string is populated for AMBIGUOUS and UNRESOLVED
edges explaining why. There is no separate "resolution error" or
"unresolved dependency" table — an AMBIGUOUS/UNRESOLVED `DependencyEdge`
already records everything such a table would.

**A resolver bug does not abort analysis of the rest of the repository.**
`DependencyAnalysisService` wraps each individual import/call/inheritance
resolution in a `try`/`except`; an unexpected exception from a resolver
degrades that one relationship to an UNRESOLVED edge (with the exception
message in `detail`) rather than failing the whole `analyze_repository`
call. This is verified directly by
`tests/unit/test_dependency_analysis_service.py::test_resolver_exception_degrades_to_unresolved_and_does_not_abort`.

## 6. Symbol resolution

"Symbol resolution" refers to CALLS and INHERITS resolution, both performed
by the single `SymbolDependencyResolver` class (§3, §7, §8). It operates
only on data already loaded into memory (`ParsedFile.symbols`,
`ParsedFile.imports`) — no additional database queries per symbol, no
filesystem access.

## 7. Function/method call resolution

For each `FUNCTION`/`METHOD` symbol's `calls` (each a `CallReference` with
raw `callee_expression` text), `SymbolDependencyResolver.resolve_call`
applies, in order:

1. **`self.`/`this.`-prefixed** (`self.method_b()`, `this.render()`): looked
   up as a `METHOD` on the *calling symbol's own immediate enclosing class*
   only (via `parent_symbol_id`) — see §9 for the one-level-only limitation.
   A call with no enclosing class (a bare function using `self.`/`this.`,
   which shouldn't normally occur but is handled) is UNRESOLVED.
2. **Any other expression containing a dot** (`module.func()`,
   `obj.attr.method()`): only attempted when the expression has **exactly
   one dot**. The segment before the dot is looked up as a name bound by
   one of the file's imports (`Import.alias` or `Import.imported_names`);
   if found, the bound import is resolved via the injected `ModuleResolver`
   and the segment after the dot is looked up as a top-level `FUNCTION` in
   the target file. An expression with two or more dots
   (`obj.attr.method()`) has no statically-known receiver type and is
   **always UNRESOLVED** — no type inference is attempted.
3. **A bare name** (`helper()`): first checked as a **top-level `FUNCTION`
   in the same file** (never a `METHOD` — a bare, unqualified call has no
   receiver, so it can never reach a method). If not found there, every
   import that binds that name (by alias or explicit imported name) is
   resolved and checked for a matching top-level function; every wildcard
   import (`from x import *`) is checked the same way. If exactly one
   distinct match is found across all of these → RESOLVED. If more than one
   distinct import-resolved candidate is found (most commonly: two
   different wildcard imports each defining a same-named function) →
   AMBIGUOUS. Otherwise → UNRESOLVED.

A **bare-name call to something that is a `CLASS`, not a `FUNCTION`** (e.g.
`Dog()`, a constructor call) is correctly **UNRESOLVED** — bare-name call
resolution only ever matches `SymbolKind.FUNCTION`, by design (see §12).

## 8. Class inheritance resolution

For each `CLASS` symbol's `base_class_names`,
`SymbolDependencyResolver.resolve_inheritance` applies the same precedence
as bare/qualified call resolution (§7 steps 2–3), but matching against
`SymbolKind.CLASS` instead of `SymbolKind.FUNCTION`:

- A base-class name with exactly one dot (`pkg.Base`) is resolved through
  an import binding, exactly like a qualified call.
- A bare base-class name (`Animal`) is resolved same-file first, then
  through imports (including wildcards), with the same
  RESOLVED/AMBIGUOUS/UNRESOLVED rules.
- `class Foo(Exception)` or a built-in/external base class correctly
  resolves to UNRESOLVED — it is never matched to an unrelated symbol.

## 9. The one-level `self.`/`this.` limitation

`self.method_b()` / `this.render()` calls are resolved **only against the
calling symbol's own immediate enclosing class** — Forge does not walk the
inheritance chain to look for the method on a base class, even when that
base class is itself resolvable.

Concretely: if `Dog(Animal)` defines `bark`, which calls `self.speak()`, and
`speak` is defined on `Animal` (not `Dog`), that call resolves to
**UNRESOLVED**, with `detail` explicitly stating the method wasn't found on
the immediate class and that inherited methods are not resolved. This is a
deliberate, stated scope limitation, not an oversight: correctly walking an
inheritance chain would require reliably resolving every base class first
(itself not always possible — see §8, §12) and picking the correct override
in the presence of multiple inheritance or shadowing, which risks exactly
the kind of guessed/incorrect edge the resolution model is designed to
avoid. This behavior is directly exercised by both the Python and
TypeScript real end-to-end test fixtures (§14).

## 10. Deterministic dependency IDs

Every `DependencyEdge.id` is a `uuid5` (`domain/dependency_analysis/ids.py
:: deterministic_id`) derived from the fields that identify the edge:
`repository_id`, `kind`, the source symbol or file id, the raw target
expression, and the location's start line. The same inputs always produce
the same id.

This uses its own fixed namespace UUID
(`2f7b6a3e-8c1d-4b5a-9e2f-6a1d3c8b7e4f`), deliberately separate from Phase
3's own `uuid5` namespace in `infrastructure/parsing/treesitter_support.py`
— the two are not shared, so a `Symbol` id and a `DependencyEdge` id can
never collide even if their input parts happened to match, and Phase 4 does
not need to import from Phase 3's parsing-internals module for this.

## 11. Idempotent re-analysis

`SqlAlchemyDependencyEdgeRepository.save_analysis_result` deletes all
existing `dependency_edges` rows for the repository, then inserts the newly
computed set — the same replace-on-rerun strategy Phase 3's
`save_parse_result` already uses. Because edge ids are deterministic (§10),
re-running analysis on unchanged parsed data produces an identical set of
edge ids, even though the underlying rows are physically deleted and
reinserted rather than upserted. This is verified directly: both real
end-to-end tests (§14) re-run `/analyze-dependencies` and assert the edge
id set is unchanged and the edge count does not grow.

**Re-parsing cascades away dependency data.** `dependency_edges` rows carry
`ON DELETE CASCADE` foreign keys to both `parsed_files` and `symbols`
(§12), so a Phase 3 re-`/parse` that replaces those rows implicitly deletes
any Phase 4 edges derived from the old data. This is intentional: stale
edges referencing pre-re-parse symbols would be actively wrong, and
re-running `/analyze-dependencies` is already a cheap, explicit step —
mirroring the explicit-stage philosophy already established between Phase 2
(import) and Phase 3 (parse).

## 12. PostgreSQL model and persistence

```sql
dependency_edges(
  id                     UUID PRIMARY KEY,
  repository_id          UUID REFERENCES repositories(id),
  kind                   VARCHAR(20),   -- imports | calls | inherits | references
  resolution_status      VARCHAR(20),   -- resolved | ambiguous | unresolved
  source_file_id         UUID REFERENCES parsed_files(id) ON DELETE CASCADE,
  source_symbol_id       UUID NULL REFERENCES symbols(id) ON DELETE CASCADE,
  target_file_id         UUID NULL REFERENCES parsed_files(id) ON DELETE CASCADE,
  target_symbol_id       UUID NULL REFERENCES symbols(id) ON DELETE CASCADE,
  raw_target_expression  TEXT,
  start_line             INTEGER,
  end_line               INTEGER,
  start_column           INTEGER NULL,
  end_column             INTEGER NULL,
  detail                 TEXT NULL
)
-- indexes: repository_id; (repository_id, kind); source_symbol_id;
--          target_symbol_id; resolution_status
```

One table for every `DependencyKind` — IMPORTS/CALLS/INHERITS/REFERENCES
share every column (a source, a possibly-unknown target, a location, a
resolution status); splitting by kind would only duplicate structure with
no behavioral difference.

**Additive Phase 3 schema changes** made to support §2's parser extension:
- `symbols.base_class_names` — a nullable JSON column, populated only for
  `CLASS` rows.
- A new `call_sites` table (`symbol_id` FK to `symbols`, `ON DELETE
  CASCADE`; `callee_expression`; `start_line`/`end_line`), one row per call
  expression captured inside a `FUNCTION`/`METHOD` symbol's body.

Both are purely additive — every previously-existing Phase 3 table,
column, and query is unchanged, and the full pre-existing Phase 3 test
suite passes unmodified against them.

`SqlAlchemyDependencyEdgeRepository` (`infrastructure/persistence/
dependency_edge_repository_impl.py`) is the only code that translates
between `DependencyEdge` and `DependencyEdgeRow` — no resolution logic
lives there, matching Phase 3's own `models.py`/`*_repository_impl.py`
split.

## 13. API endpoints

All routes are registered under
`/api/v1/projects/{project_id}/repositories/{repository_id}`
(`api/dependencies.py`, registered in `core/app_factory.py`):

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/analyze-dependencies` | Runs analysis on an already-`READY`, already-parsed repository; persists and returns a summary. `201 Created`. Idempotent — re-running replaces the previous result (§11). |
| `GET` | `/dependencies` | Lists edges for the repository. Query parameters: `kind`, `source_symbol_id`, `target_symbol_id`, `resolution_status`, `limit` (default 100), `offset` (default 0) — all optional, applied as SQL `WHERE` filters. |
| `GET` | `/dependencies/{dependency_id}` | A single edge by id. `404` if unknown. |

`POST /analyze-dependencies` response (`DependencyAnalysisSummaryResponse`):
`repository_id`, `edge_count`, `resolved_count`, `ambiguous_count`,
`unresolved_count`, `analyzed_at`.

`GET` responses (`DependencyEdgeResponse`, one per edge): `id`,
`repository_id`, `kind`, `resolution_status`, `source_file_id`,
`source_symbol_id`, `target_file_id`, `target_symbol_id`,
`raw_target_expression`, `start_line`, `end_line`, `start_column`,
`end_column`, `detail`.

The router constructs its own `CompositeModuleResolver` (wrapping
`PythonModuleResolver` and one `EcmaScriptModuleResolver` shared by both
`JAVASCRIPT` and `TYPESCRIPT`) and its own `SymbolDependencyResolver` — no
resolution logic lives in the router itself; it only translates between
HTTP and `DependencyAnalysisService`.

## 14. Error handling

Phase 4 introduces no new domain error types — it reuses the two already
established by Phases 1–3 (`domain/errors.py`, mapped to HTTP status in
`api/error_handlers.py`):

- **`NotFoundError` → `404`**: unknown `repository_id` (on
  analyze/list/get), or unknown `dependency_id` (on single-edge get).
- **`UnsupportedRepositoryStateError` → `409`**: the repository exists but
  is not `READY`, or is `READY` but has not been parsed yet (no
  `ParsedFile` rows) — there is nothing to analyze.

A single relationship's resolution failure (an unexpected exception from a
resolver) never raises out of `analyze_repository` — see §5. The only
exceptions that propagate to the API layer are the two above, both
representing a request-level precondition failure, not a partial-analysis
failure.

## 15. Known limitations

Stated explicitly, matching what §5–§9 above already describe in context:

- **No type inference.** A call through an arbitrary object attribute chain
  (`obj.attr.method()`, two or more dots) is always UNRESOLVED — Forge has
  no notion of a local variable's type, so it never guesses.
- **`self.`/`this.` calls resolve one level only** (§9) — inherited methods
  are never resolved, even when the base class itself is resolvable.
- **No dynamic-dispatch, decorator, metaclass, or monkeypatch modeling.**
  Python decorators/metaclasses and JavaScript prototype manipulation are
  not analyzed; resolution is based solely on the static structure Phase 3
  captured.
- **A bare call to a class name is always UNRESOLVED, not a constructor
  call.** `Dog()` is a call expression whose callee (`"Dog"`) matches a
  `CLASS`, not a `FUNCTION` — bare-name call resolution deliberately only
  ever matches `SymbolKind.FUNCTION` (§7), so an instantiation is correctly
  reported as UNRESOLVED rather than misrepresented as a call to the class
  symbol. Class instantiation is not modeled as a CALLS relationship at
  all in this phase.
- **Wildcard-import ambiguity detection is heuristic, not exhaustive.** It
  checks whether more than one wildcard-imported file defines a same-named
  top-level symbol; it does not model `__all__` restrictions (Python) or
  named-export lists (JS/TS) that would narrow what a wildcard import
  actually re-exports.
- **A bare relative import naming multiple submodules at once**
  (`from . import a, b`) resolves AMBIGUOUS, since a single `Import` record
  cannot represent two distinct target files (§4).
- **No bundler/tsconfig path-alias resolution** (`"@app/utils"` style
  specifiers) — Forge has no config-file parsing to learn such mappings
  from, so these resolve UNRESOLVED like any other bare specifier.
- **`REFERENCES` is declared but not produced.** It exists in
  `DependencyKind` for forward extensibility only; no resolver in this
  phase emits it. A general "any identifier reference" extractor was
  deliberately not built — CALLS and INHERITS are the relationship kinds
  Forge can support reliably without type inference.
- **Re-parsing invalidates dependency data** (§11) — by design, but it
  means a consumer must re-run `/analyze-dependencies` after any
  `/parse` that changes parsed data.
- **Neo4j is untouched.** All Phase 4 data lives in PostgreSQL only; the
  knowledge-graph projection is Phase 5's responsibility.

## 16. Testing coverage (for reference)

- **Unit**: `PythonModuleResolver` and `EcmaScriptModuleResolver` (relative,
  absolute, aliased, unresolved, ambiguous imports);
  `SymbolDependencyResolver` (bare/qualified/instance-prefixed calls,
  inheritance, ambiguity, the one-level limitation);
  `DependencyAnalysisService` against in-memory fakes (orchestration,
  resolver-exception isolation, not-found/not-ready/not-parsed rejection,
  re-analysis replacement).
- **Integration (real PostgreSQL)**:
  `test_postgres_dependency_persistence.py` (FK/cascade behavior, round
  trip, idempotent re-analysis, deterministic ids);
  `test_dependencies_api.py` (HTTP status codes, filtering, pagination).
- **Real end-to-end** (`test_real_dependency_analysis.py`, no mocking
  anywhere): real ZIP import → real `/parse` → real
  `/analyze-dependencies` → real PostgreSQL → real API queries.
  - `test_real_python_import_analysis_end_to_end`: a focused Python-only
    IMPORTS fixture (relative, absolute, external/unresolved, a circular
    pair).
  - `test_real_mixed_language_dependency_analysis_end_to_end`: the full
    scenario — Python and JS/TS files, an aliased import, function calls,
    method calls (including the one-level self/this limitation in both
    languages), class inheritance, a genuine wildcard-import ambiguity,
    several genuinely unresolved references, a circular import pair, and
    re-analysis idempotency — asserted against a hand-tallied expected edge
    count (18 edges: 12 resolved, 1 ambiguous, 5 unresolved) that matched
    on the first real run against Postgres.
