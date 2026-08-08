"""Regression test for the naive-vs-timezone-aware datetime column bug.

Context: `Mapped[datetime]` without an explicit `DateTime(timezone=True)` produces a
Postgres `TIMESTAMP WITHOUT TIME ZONE` column. The domain layer only ever produces
timezone-aware UTC datetimes (`datetime.now(UTC)` in `domain/project/entities.py`
and `domain/repository/entities.py`), so binding one to a naive column raises
`asyncpg.exceptions.DataError: can't subtract offset-naive and offset-aware
datetimes` at insert time — a failure that only ever surfaced against a real
Postgres connection, never against the in-memory fakes the rest of the API test
suite runs against (see tests/fakes.py).

This test catches it statically, for every current *and future* datetime column on
either ORM row, without needing a database — it inspects the actual materialized
column type, not just that `Base.type_annotation_map` looks right in isolation.
"""

from __future__ import annotations

from sqlalchemy import DateTime

from forge.infrastructure.persistence.models import ProjectRow, RepositoryRow


def test_every_datetime_column_is_timezone_aware() -> None:
    checked_any = False
    for row_class in (ProjectRow, RepositoryRow):
        for column in row_class.__table__.columns:
            if not isinstance(column.type, DateTime):
                continue
            checked_any = True
            assert column.type.timezone is True, (
                f"{row_class.__name__}.{column.name} maps to a naive TIMESTAMP "
                "column — inserting the timezone-aware UTC datetime the domain "
                "layer always produces will raise "
                "asyncpg.exceptions.DataError at write time. Use "
                "DateTime(timezone=True) (or rely on Base.type_annotation_map)."
            )

    # Guard against this test silently checking nothing if the columns are ever
    # renamed/restructured away from `Mapped[datetime]`.
    assert checked_any, "expected at least one datetime column across ProjectRow/RepositoryRow"


def test_expected_datetime_columns_are_present() -> None:
    """Names the specific columns this bug affected, so a future rename that drops
    one of them without noticing is caught here rather than by silently checking
    fewer columns than intended."""
    project_columns = {c.name for c in ProjectRow.__table__.columns}
    repository_columns = {c.name for c in RepositoryRow.__table__.columns}

    assert {"created_at", "updated_at"} <= project_columns
    assert {"created_at", "updated_at", "meta_scanned_at"} <= repository_columns
