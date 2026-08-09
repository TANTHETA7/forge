"""FastAPI dependency providers for persistence.

Purpose:       Wire SQLAlchemy async sessions and repository-port implementations
                into FastAPI's dependency-injection system.
Responsibility: Construction/lifecycle only — no business logic.
Depends on:    infrastructure/persistence/database.py, infrastructure/persistence/*_impl.py.
Depended on by: api/projects.py, api/repositories.py, api/parsing.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.config import Settings, get_settings
from forge.domain.parsing.ports import ParsedFileRepository
from forge.domain.project.ports import ProjectRepository
from forge.domain.repository.ports import RepositoryRepository
from forge.infrastructure.persistence.database import ensure_schema, get_session_factory
from forge.infrastructure.persistence.parsed_file_repository_impl import (
    SqlAlchemyParsedFileRepository,
)
from forge.infrastructure.persistence.project_repository_impl import SqlAlchemyProjectRepository
from forge.infrastructure.persistence.repository_repository_impl import (
    SqlAlchemyRepositoryRepository,
)


async def get_session(settings: Settings = Depends(get_settings)) -> AsyncIterator[AsyncSession]:
    await ensure_schema(settings)
    session_factory = get_session_factory(settings)
    async with session_factory() as session:
        yield session


def get_project_repository(session: AsyncSession = Depends(get_session)) -> ProjectRepository:
    return SqlAlchemyProjectRepository(session)


def get_repository_repository(
    session: AsyncSession = Depends(get_session),
) -> RepositoryRepository:
    return SqlAlchemyRepositoryRepository(session)


def get_parsed_file_repository(
    session: AsyncSession = Depends(get_session),
) -> ParsedFileRepository:
    return SqlAlchemyParsedFileRepository(session)
