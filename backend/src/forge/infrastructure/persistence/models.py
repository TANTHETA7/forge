"""SQLAlchemy ORM models — the Postgres-side shape of `Project` and `Repository`.

Purpose:       Map domain entities to relational rows.
Responsibility: Table/column definitions only. Conversion to/from domain entities
                lives in the `*_impl.py` repository classes, not here — these ORM
                classes never leak into application/domain code.
Depends on:    sqlalchemy.
Depended on by: infrastructure/persistence/*_impl.py, infrastructure/persistence/database.py.

Schema note: this phase uses `Base.metadata.create_all` (see database.py) rather
than an Alembic migration chain. Alembic is a declared dependency
(backend/pyproject.toml) and is the intended tool once the schema needs to evolve
under real data — introducing it now, before there is a second migration to write
or a live Postgres instance available in this environment to validate one against,
would be exactly the "unnecessary machinery ahead of a proven need" this project's
own architecture review says to avoid. Wiring Alembic is the natural next step
before this schema's first change.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for every ORM row in this package.

    `type_annotation_map` is what makes this the *structural* fix rather than a
    per-column patch: every `Mapped[datetime]` (and `Mapped[datetime | None]`)
    column below — present or future — gets `TIMESTAMP WITH TIME ZONE` without
    needing to remember `DateTime(timezone=True)` at each call site. The domain
    layer only ever produces timezone-aware UTC `datetime`s (see
    `domain/project/entities.py`, `domain/repository/entities.py`); the column type
    must match that or asyncpg rejects the bind with `DataError: can't subtract
    offset-naive and offset-aware datetimes` — the exact failure a plain
    `Mapped[datetime]` (defaulting to a naive `TIMESTAMP`) produced here before this
    fix. Postgres stores `TIMESTAMPTZ` values normalized to UTC regardless of
    session timezone, so this doesn't depend on the connecting session's `TimeZone`
    setting.
    """

    type_annotation_map = {datetime: DateTime(timezone=True)}


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class RepositoryRow(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    source_type: Mapped[str] = mapped_column(String(20))
    source_ref: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(200))
    workspace_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    # Metadata columns — nullable until the repository reaches READY. Flattened
    # rather than one JSON blob so the common fields stay directly queryable; only
    # `language_stats` (an open-ended map) needs JSON.
    meta_file_count: Mapped[int | None]
    meta_directory_count: Mapped[int | None]
    meta_total_size_bytes: Mapped[int | None]
    meta_language_stats: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    meta_has_readme: Mapped[bool | None]
    meta_has_git: Mapped[bool | None]
    meta_scanned_at: Mapped[datetime | None]


# -- Phase 3: Code Parser -----------------------------------------------------
# `repository_id` is denormalized onto SymbolRow/ImportRow (reachable via
# `file_id` too) so the read APIs' common case — "every symbol/import for this
# repository" — doesn't require a join. `ON DELETE CASCADE` from ParsedFileRow
# down through SymbolRow/ImportRow/ParameterRow is what lets
# `SqlAlchemyParsedFileRepository.save_parse_result` re-parse a repository by
# deleting its `parsed_files` rows and letting Postgres cascade the rest, rather
# than four separate delete statements.


class ParsedFileRow(Base):
    __tablename__ = "parsed_files"
    __table_args__ = (UniqueConstraint("repository_id", "path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"))
    path: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(20))
    has_syntax_errors: Mapped[bool]
    parsed_at: Mapped[datetime]


class SymbolRow(Base):
    __tablename__ = "symbols"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("parsed_files.id", ondelete="CASCADE")
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"))
    parent_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("symbols.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(500))
    qualified_name: Mapped[str] = mapped_column(Text)
    start_line: Mapped[int]
    end_line: Mapped[int]
    start_column: Mapped[int | None]
    end_column: Mapped[int | None]


class ParameterRow(Base):
    __tablename__ = "parameters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    symbol_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(500))
    position: Mapped[int]
    annotation: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_value: Mapped[str | None] = mapped_column(Text, nullable=True)


class ImportRow(Base):
    __tablename__ = "imports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("parsed_files.id", ondelete="CASCADE")
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"))
    module: Mapped[str] = mapped_column(Text)
    imported_names: Mapped[list[str]] = mapped_column(JSON)
    alias: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_line: Mapped[int]
    end_line: Mapped[int]


class ParseErrorRow(Base):
    __tablename__ = "parse_errors"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"))
    file_path: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime]
