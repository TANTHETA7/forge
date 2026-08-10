"""FastAPI dependency providers for code intelligence.

Purpose:       Wire the Neo4j session and `GraphIntelligenceRepository`
                implementation into FastAPI's dependency-injection system —
                the code-intelligence counterpart to
                infrastructure/graph/dependencies.py.
Responsibility: Construction/lifecycle only — no business logic. Reuses
                infrastructure/graph/dependencies.py::get_neo4j_session
                (the same connection primitive Phase 5's `Neo4jGraphRepository`
                uses) rather than duplicating driver/session setup.
Depends on:    infrastructure/graph/dependencies.py,
                infrastructure/graph_intelligence/neo4j_graph_intelligence_repository.py,
                core/config.py.
Depended on by: api/graph_intelligence.py.
"""

from __future__ import annotations

from fastapi import Depends
from neo4j import AsyncSession

from forge.core.config import Settings, get_settings
from forge.domain.graph_intelligence.ports import GraphIntelligenceRepository
from forge.infrastructure.graph.dependencies import get_neo4j_session
from forge.infrastructure.graph_intelligence.neo4j_graph_intelligence_repository import (
    Neo4jGraphIntelligenceRepository,
)


def get_graph_intelligence_repository(
    session: AsyncSession = Depends(get_neo4j_session),
    settings: Settings = Depends(get_settings),
) -> GraphIntelligenceRepository:
    return Neo4jGraphIntelligenceRepository(
        session, query_timeout_seconds=settings.graph_query_timeout_seconds
    )
