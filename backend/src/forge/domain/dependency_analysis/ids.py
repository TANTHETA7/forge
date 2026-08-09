"""Deterministic id generation for dependency-analysis entities.

Purpose:       One `uuid5`-based id function, used everywhere a `DependencyEdge`
                id needs to be built from its identifying facts (see
                domain/dependency_analysis/entities.py::DependencyEdge.id).
Responsibility: Pure id derivation — no business logic.
Depends on:    stdlib only.
Depended on by: infrastructure/dependency_analysis/*.py,
                application/dependency_analysis/service.py.

A near-identical helper already exists in infrastructure/parsing/
treesitter_support.py (Phase 3, private to that module). Not reused here
deliberately — it would mean importing across two sibling infrastructure
packages (parsing <- dependency_analysis) for a five-line pure function, and
touching a Phase 3 file this phase's plan explicitly scoped changes to (see
docs/architecture/04-dependency-analysis.md). Both use the same `uuid5`
approach; if they ever need to diverge (different namespace, different
separator) that's a sign they were never really the same concern to begin with.
"""

from __future__ import annotations

import uuid

# Fixed, arbitrary namespace for every id this module mints — distinct from
# Phase 3's own namespace (treesitter_support.py) so a `Symbol` id and a
# `DependencyEdge` id can never collide even if their input parts happened to
# match. Generated once with `uuid.uuid4()`; never changes.
_ID_NAMESPACE = uuid.UUID("2f7b6a3e-8c1d-4b5a-9e2f-6a1d3c8b7e4f")
_ID_SEPARATOR = "\x1f"


def deterministic_id(*parts: str) -> uuid.UUID:
    """A stable `uuid5` derived from `parts` — the same inputs always produce
    the same id, which is what makes re-running dependency analysis on
    unchanged parsed data idempotent."""
    return uuid.uuid5(_ID_NAMESPACE, _ID_SEPARATOR.join(parts))
