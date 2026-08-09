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
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.dependency_analysis.entities import (
    DependencyEdge,
    DependencyKind,
    ResolutionStatus,
)
from forge.domain.parsing.entities import SourceLocation
from forge.infrastructure.persistence.dependency_models import DependencyEdgeRow


class SqlAlchemyDependencyEdgeRepository:
    """A `DependencyEdgeRepository` backed by Postgres via SQLAlchemy's async
    engine."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_analysis_result(
        self, repository_id: UUID, edges: tuple[DependencyEdge, ...]
    ) -> None:
        await self._session.execute(
            delete(DependencyEdgeRow).where(DependencyEdgeRow.repository_id == repository_id)
        )
        for edge in edges:
            self._session.add(_to_row(edge))
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
        query = select(DependencyEdgeRow).where(DependencyEdgeRow.repository_id == repository_id)
        if kind is not None:
            query = query.where(DependencyEdgeRow.kind == kind.value)
        if source_symbol_id is not None:
            query = query.where(DependencyEdgeRow.source_symbol_id == source_symbol_id)
        if target_symbol_id is not None:
            query = query.where(DependencyEdgeRow.target_symbol_id == target_symbol_id)
        if resolution_status is not None:
            query = query.where(DependencyEdgeRow.resolution_status == resolution_status.value)
        query = query.order_by(DependencyEdgeRow.start_line).limit(limit).offset(offset)

        rows = (await self._session.execute(query)).scalars().all()
        return [_to_entity(row) for row in rows]

    async def get_edge(self, dependency_id: UUID) -> DependencyEdge | None:
        row = await self._session.get(DependencyEdgeRow, dependency_id)
        return _to_entity(row) if row is not None else None


def _to_row(edge: DependencyEdge) -> DependencyEdgeRow:
    return DependencyEdgeRow(
        id=edge.id,
        repository_id=edge.repository_id,
        kind=edge.kind.value,
        resolution_status=edge.resolution_status.value,
        source_file_id=edge.source_file_id,
        source_symbol_id=edge.source_symbol_id,
        target_file_id=edge.target_file_id,
        target_symbol_id=edge.target_symbol_id,
        raw_target_expression=edge.raw_target_expression,
        start_line=edge.location.start_line,
        end_line=edge.location.end_line,
        start_column=edge.location.start_column,
        end_column=edge.location.end_column,
        detail=edge.detail,
    )


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
