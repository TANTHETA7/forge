"""SQLAlchemy ORM model for dependency edges — Phase 4.

Purpose:       Map `DependencyEdge` to a relational row.
Responsibility: Table/column definition only. Conversion to/from the domain
                entity lives in dependency_edge_repository_impl.py, not here —
                same split Phase 3's `models.py`/`*_repository_impl.py` already
                establish.
Depends on:    sqlalchemy, infrastructure/persistence/models.py (shares `Base`).
Depended on by: infrastructure/persistence/dependency_edge_repository_impl.py.

One table for every `DependencyKind` (IMPORTS/CALLS/INHERITS/REFERENCES) — see
domain/dependency_analysis/entities.py for why splitting by kind would only
duplicate structure with no behavioral difference. `ON DELETE CASCADE` from
`parsed_files`/`symbols` is deliberate: a Phase 3 re-parse replacing those rows
should take this phase's derived edges down with it (see
docs/architecture/04-dependency-analysis.md) — stale edges referencing
pre-re-parse symbols would be actively wrong, and re-analysis is already a
cheap, explicit, re-runnable step.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from forge.infrastructure.persistence.models import Base


class DependencyEdgeRow(Base):
    __tablename__ = "dependency_edges"
    __table_args__ = (
        Index("ix_dependency_edges_repository_kind", "repository_id", "kind"),
        Index("ix_dependency_edges_source_symbol", "source_symbol_id"),
        Index("ix_dependency_edges_target_symbol", "target_symbol_id"),
        Index("ix_dependency_edges_resolution_status", "resolution_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    resolution_status: Mapped[str] = mapped_column(String(20))
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("parsed_files.id", ondelete="CASCADE")
    )
    source_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), nullable=True
    )
    target_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("parsed_files.id", ondelete="CASCADE"), nullable=True
    )
    target_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), nullable=True
    )
    raw_target_expression: Mapped[str] = mapped_column(Text)
    start_line: Mapped[int]
    end_line: Mapped[int]
    start_column: Mapped[int | None]
    end_column: Mapped[int | None]
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
