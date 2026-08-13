"""SQLAlchemy implementation of
`domain/dependency_analysis/ports.py::DependencyEdgeRepository`.

Purpose:       Persist and retrieve a repository's dependency-analysis results.
Responsibility: Translate between the domain entity and the ORM row
                (persistence/dependency_models.py) only — no resolution logic.
Depends on:    sqlalchemy, domain/dependency_analysis/entities.py,
                infrastructure/persistence/dependency_models.py.
Depended on by: infrastructure/persistence/dependencies.py.

Re-analyzing a repository is idempotent by replacement, not merge — same
strategy as `SqlAlchemyParsedFileRepository.save_parse_result` (Phase 3):
delete this repository's existing edges, insert the new set.

Insertion is a single chunked bulk `INSERT` (`Session.execute(insert(...), rows)`
in `_INSERT_BATCH_SIZE`-row chunks), not one `Session.add()` per edge — the same
fix, for the same measured reason, as `parsed_file_repository_impl.py`'s
"Persistence performance" docstring: a real repository's dependency-edge count
is large (pytest-dev/pytest: 28,755 edges from 270 files) and per-row
`Session.add()` does not reliably batch itself into multi-row `INSERT`s at
flush time, making analysis of a real repository's dependencies far slower
than the bulk form.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.dependency_analysis.entities import (
    DependencyEdge,
    DependencyKind,
    ResolutionStatus,
)
from forge.domain.parsing.entities import SourceLocation
from forge.infrastructure.persistence.dependency_models import DependencyEdgeRow

# Rows per bulk-insert statement — see parsed_file_repository_impl.py's own
# `_INSERT_BATCH_SIZE` for the full rationale (network round trips vs. bound
# parameter count). Kept as the same value for consistency; `DependencyEdgeRow`
# has fewer columns than the widest table there, so 500 is comfortably under
# the per-statement parameter ceiling here too.
_INSERT_BATCH_SIZE = 500


def _chunked[T](items: list[T], size: int) -> Iterator[list[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class SqlAlchemyDependencyEdgeRepository:
    """A `DependencyEdgeRepository` backed by Postgres via SQLAlchemy's async
    engine.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_analysis_result(
        self,
        repository_id: UUID,
        edges: tuple[DependencyEdge, ...],
    ) -> None:
        # Remove the previous dependency-analysis result.
        await self._session.execute(
            delete(DependencyEdgeRow).where(
                DependencyEdgeRow.repository_id == repository_id
            )
        )

        # Ensure the DELETE is executed before the new rows are inserted.
        await self._session.flush()

        # Insert the new dependency-analysis result, chunked — see this
        # module's own docstring, "Persistence performance".
        rows = [_to_params(edge) for edge in edges]
        for chunk in _chunked(rows, _INSERT_BATCH_SIZE):
            await self._session.execute(insert(DependencyEdgeRow), chunk)

        await self._session.commit()

    async def get_edges(
        self,
        repository_id: UUID,
        *,
        kind: DependencyKind | None = None,
        source_symbol_id: UUID | None = None,
        target_symbol_id: UUID | None = None,
        resolution_status: ResolutionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DependencyEdge]:
        query = select(DependencyEdgeRow).where(
            DependencyEdgeRow.repository_id == repository_id
        )

        if kind is not None:
            query = query.where(
                DependencyEdgeRow.kind == kind.value
            )

        if source_symbol_id is not None:
            query = query.where(
                DependencyEdgeRow.source_symbol_id == source_symbol_id
            )

        if target_symbol_id is not None:
            query = query.where(
                DependencyEdgeRow.target_symbol_id == target_symbol_id
            )

        if resolution_status is not None:
            query = query.where(
                DependencyEdgeRow.resolution_status == resolution_status.value
            )

        # `.id` is a required secondary sort key, not cosmetic — see the
        # identical reasoning on `SqlAlchemyParsedFileRepository.get_symbols`
        # (parsed_file_repository_impl.py). `start_line` ties heavily on a
        # real repository (many edges start on the same line number across
        # different files/calls), so `LIMIT`/`OFFSET` alone is not guaranteed
        # to see the same tie-order across separate query executions —
        # empirically confirmed against a real repository-scale dataset
        # (pytest-dev/pytest: 28,755 edges over only 3,301 distinct
        # `start_line` values). This is not just a `GET /dependencies`
        # pagination-stability concern: `application/graph/service.py`'s
        # `_load_all_edges` drains this same paginated method to build every
        # graph projection, so an unstable page boundary here silently
        # corrupts the projected graph's relationship set. `.id` (the primary
        # key) is unique, making each page's boundary fully deterministic.
        query = (
            query.order_by(DependencyEdgeRow.start_line, DependencyEdgeRow.id)
            .limit(limit)
            .offset(offset)
        )

        rows = (await self._session.execute(query)).scalars().all()

        return [_to_entity(row) for row in rows]

    async def get_edge(
        self,
        dependency_id: UUID,
    ) -> DependencyEdge | None:
        row = await self._session.get(
            DependencyEdgeRow,
            dependency_id,
        )

        return _to_entity(row) if row is not None else None


def _to_params(edge: DependencyEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "repository_id": edge.repository_id,
        "kind": edge.kind.value,
        "resolution_status": edge.resolution_status.value,
        "source_file_id": edge.source_file_id,
        "source_symbol_id": edge.source_symbol_id,
        "target_file_id": edge.target_file_id,
        "target_symbol_id": edge.target_symbol_id,
        "raw_target_expression": edge.raw_target_expression,
        "start_line": edge.location.start_line,
        "end_line": edge.location.end_line,
        "start_column": edge.location.start_column,
        "end_column": edge.location.end_column,
        "detail": edge.detail,
    }


def _to_entity(row: DependencyEdgeRow) -> DependencyEdge:
    return DependencyEdge(
        id=row.id,
        repository_id=row.repository_id,
        kind=DependencyKind(row.kind),
        resolution_status=ResolutionStatus(row.resolution_status),
        source_file_id=row.source_file_id,
        source_symbol_id=row.source_symbol_id,
        target_file_id=row.target_file_id,
        target_symbol_id=row.target_symbol_id,
        raw_target_expression=row.raw_target_expression,
        location=SourceLocation(
            start_line=row.start_line,
            end_line=row.end_line,
            start_column=row.start_column,
            end_column=row.end_column,
        ),
        detail=row.detail,
    )
