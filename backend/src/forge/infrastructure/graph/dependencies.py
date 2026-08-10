"""FastAPI dependency providers for the Neo4j graph.

Purpose:       Wire Neo4j sessions and the `GraphRepository` implementation
                into FastAPI's dependency-injection system — the Neo4j
                counterpart to `infrastructure/persistence/dependencies.py`.
Responsibility: Construction/lifecycle only — no business logic.
Depends on:    infrastructure/graph/{neo4j_driver,neo4j_graph_repository}.py.
Depended on by: api/graph.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from neo4j import AsyncSession

from forge.core.config import Settings, get_settings
from forge.domain.graph.ports import GraphRepository
from forge.infrastructure.graph.neo4j_driver import ensure_constraints, get_driver
from forge.infrastructure.graph.neo4j_graph_repository import Neo4jGraphRepository


async def get_neo4j_session(
    settings: Settings = Depends(get_settings),
) -> AsyncIterator[AsyncSession]:
    await ensure_constraints(settings)
    driver = get_driver(settings)
    async with driver.session() as session:
        yield session


def get_graph_repository(
    session: AsyncSession = Depends(get_neo4j_session),
) -> GraphRepository:
    return Neo4jGraphRepository(session)
