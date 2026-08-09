"""Dependency relationship domain model — Phase 4.

Purpose:       Define what a "dependency edge" is — a relationship Forge found
                between two things in an already-parsed repository (a file
                importing another file, a function calling another function, a
                class inheriting from another class) — independent of how it was
                resolved or persisted.
Responsibility: `DependencyEdge`, `DependencyKind`, `ResolutionStatus`,
                `DependencyAnalysisResult` — the full result of analyzing one
                repository's already-parsed data.

Why one `DependencyEdge` entity instead of a separate shape per kind: IMPORTS,
CALLS, INHERITS, and (future) REFERENCES share every field — a source, a target
that may or may not be known, a location, a resolution status. Splitting them
would only duplicate structure with no behavioral difference, the same reasoning
Phase 3 already applied to `Symbol` (see domain/parsing/entities.py).

Why there is no separate "unresolved dependency" or "resolution error" entity:
an `UNRESOLVED` or `AMBIGUOUS` `DependencyEdge` already carries everything an
error record would (`raw_target_expression`, `location`, `detail`) — a second
table would duplicate this one's purpose. RESOLVED/AMBIGUOUS/UNRESOLVED are
first-class outcomes, not exceptions: Forge does not raise or discard when it
can't resolve something, it records that fact structurally (see
docs/architecture/04-dependency-analysis.md, "Resolution strategy").

Depends on:    domain/parsing/entities.py (SourceLocation only).
Depended on by: domain/dependency_analysis/ports.py, infrastructure/
                dependency_analysis/*.py, application/dependency_analysis/
                service.py, infrastructure/persistence/
                dependency_edge_repository_impl.py, api/dependencies.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from forge.domain.parsing.entities import SourceLocation


class DependencyKind(StrEnum):
    """What kind of relationship a `DependencyEdge` represents.

    `REFERENCES` is declared for extensibility (the brief's own forward-looking
    relationship sketch) but is not produced by any resolver in this phase —
    IMPORTS/CALLS/INHERITS are the reliably-resolvable relationships Forge
    supports without type inference; see docs/architecture/04-dependency-analysis.md.
    """

    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"
    REFERENCES = "references"


class ResolutionStatus(StrEnum):
    """The outcome of trying to resolve a dependency's target.

    RESOLVED: exactly one target found, with reasonable confidence.
    AMBIGUOUS: more than one equally-plausible target found — never guessed
        down to one.
    UNRESOLVED: no target found in this repository (commonly: an external
        package/stdlib import, or a call whose receiver's type isn't statically
        known) — the normal, expected outcome for a great many real edges, not
        a failure.
    """

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    """One dependency relationship found in an already-parsed repository.

    Attributes:
        id: Deterministic — `uuid5` of `(repository_id, kind, source_symbol_id
            or source_file_id, raw_target_expression, location)`. Stable across
            re-analysis of unchanged parsed data, which is what makes
            re-running analysis idempotent (see application/dependency_analysis/
            service.py).
        repository_id: The `Repository` this edge belongs to.
        kind: IMPORTS, CALLS, INHERITS, or (reserved) REFERENCES.
        resolution_status: RESOLVED, AMBIGUOUS, or UNRESOLVED.
        source_file_id: The `ParsedFile` this edge originates from — always set.
        source_symbol_id: The `Symbol` this edge originates from — set for
            CALLS/INHERITS (the calling function/method, or the subclass);
            `None` for file-level IMPORTS edges.
        target_file_id: The target `ParsedFile`, when known — set whenever
            resolution identified which file the target lives in, even if the
            specific symbol within it couldn't be pinned down.
        target_symbol_id: The target `Symbol`, set only when RESOLVED to one
            specific symbol.
        raw_target_expression: The original text being resolved — a module
            path, a callee expression, or a base-class name — always present,
            even (especially) when unresolved, so the raw fact is never lost.
        location: Where in `source_file_id` this dependency was found.
        detail: Human-readable explanation, most useful for AMBIGUOUS/
            UNRESOLVED (e.g. "no matching file in repository (likely
            external)"). `None` for a plain RESOLVED edge.
    """

    id: UUID
    repository_id: UUID
    kind: DependencyKind
    resolution_status: ResolutionStatus
    source_file_id: UUID
    source_symbol_id: UUID | None
    target_file_id: UUID | None
    target_symbol_id: UUID | None
    raw_target_expression: str
    location: SourceLocation
    detail: str | None


@dataclass(frozen=True, slots=True)
class DependencyAnalysisResult:
    """The complete outcome of analyzing one repository's already-parsed data.

    Attributes:
        repository_id: The `Repository` that was analyzed.
        edges: Every dependency edge found, regardless of resolution status —
            filtering by status is a read-time concern (see
            domain/dependency_analysis/ports.py::DependencyEdgeRepository), not
            something analysis itself decides.
        analyzed_at: When this analysis run completed (UTC).
    """

    repository_id: UUID
    edges: tuple[DependencyEdge, ...]
    analyzed_at: datetime


@dataclass(frozen=True, slots=True)
class SymbolResolution:
    """The outcome of resolving one call site's callee or one class's base-class
    name to a specific `Symbol` — the CALLS/INHERITS counterpart to
    `domain/dependency_analysis/ports.py::ModuleResolution`. Not a port return
    type (unlike `ModuleResolution`): `SymbolDependencyResolver`
    (infrastructure/dependency_analysis/symbol_dependency_resolver.py) is one
    concrete, language-agnostic class, not a per-language port implementation
    (see docs/architecture/04-dependency-analysis.md, "Architecture") — this
    type just needs a home both application and infrastructure can import.

    Attributes:
        status: RESOLVED, AMBIGUOUS, or UNRESOLVED.
        target_file_id: The file the target symbol lives in, when known.
        target_symbol_id: The specific target `Symbol`, set only when RESOLVED.
        detail: Human-readable reason — always set for AMBIGUOUS/UNRESOLVED.
    """

    status: ResolutionStatus
    target_file_id: UUID | None
    target_symbol_id: UUID | None
    detail: str | None
