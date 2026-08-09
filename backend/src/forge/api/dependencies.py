"""Dependency analysis API router.

Purpose:       Expose dependency analysis (trigger + read) over HTTP.
Responsibility: Translate between HTTP and application/dependency_analysis/
                service.py only — no resolution logic here, matching api/
                parsing.py's rule for its own router. This router is the one
                place that constructs the concrete per-language `ModuleResolver`s
                (wrapped in `CompositeModuleResolver`) and the single
                `SymbolDependencyResolver`; application code only ever sees the
                domain/dependency_analysis/ports.py::ModuleResolver interface
                and the concrete (port-less by design) `SymbolDependencyResolver`.
Depends on:    application/dependency_analysis/service.py, infrastructure/
                dependency_analysis/*, api/schemas.py.
Depended on by: core/app_factory.py (registers this router).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from forge.api.schemas import DependencyAnalysisSummaryResponse, DependencyEdgeResponse
from forge.application.dependency_analysis.service import DependencyAnalysisService
from forge.domain.dependency_analysis.entities import (
    DependencyAnalysisResult,
    DependencyEdge,
    DependencyKind,
    ResolutionStatus,
)
from forge.domain.dependency_analysis.ports import DependencyEdgeRepository
from forge.domain.parsing.entities import Language
from forge.domain.parsing.ports import ParsedFileRepository
from forge.domain.repository.ports import RepositoryRepository
from forge.infrastructure.dependency_analysis.composite_module_resolver import (
    CompositeModuleResolver,
)
from forge.infrastructure.dependency_analysis.ecmascript_module_resolver import (
    EcmaScriptModuleResolver,
)
from forge.infrastructure.dependency_analysis.python_module_resolver import PythonModuleResolver
from forge.infrastructure.dependency_analysis.symbol_dependency_resolver import (
    SymbolDependencyResolver,
)
from forge.infrastructure.persistence.dependencies import (
    get_dependency_edge_repository,
    get_parsed_file_repository,
    get_repository_repository,
)

router = APIRouter(
    prefix="/projects/{project_id}/repositories/{repository_id}", tags=["dependencies"]
)


def get_dependency_analysis_service(
    repositories: RepositoryRepository = Depends(get_repository_repository),
    parsed_files: ParsedFileRepository = Depends(get_parsed_file_repository),
    dependency_edges: DependencyEdgeRepository = Depends(get_dependency_edge_repository),
) -> DependencyAnalysisService:
    module_resolver = CompositeModuleResolver(
        {
            Language.PYTHON: PythonModuleResolver(),
            Language.JAVASCRIPT: EcmaScriptModuleResolver(),
            Language.TYPESCRIPT: EcmaScriptModuleResolver(),
        }
    )
    return DependencyAnalysisService(
        repositories=repositories,
        parsed_files=parsed_files,
        dependency_edges=dependency_edges,
        module_resolver=module_resolver,
        symbol_resolver=SymbolDependencyResolver(module_resolver),
    )


@router.post(
    "/analyze-dependencies",
    response_model=DependencyAnalysisSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def analyze_dependencies(
    project_id: UUID,
    repository_id: UUID,
    service: DependencyAnalysisService = Depends(get_dependency_analysis_service),
) -> DependencyAnalysisSummaryResponse:
    """Analyze an already-parsed `READY` repository's dependencies.

    404s if the repository doesn't exist; 409s if it exists but isn't `READY`,
    or is `READY` but hasn't been parsed yet (via api/error_handlers.py).
    Idempotent — re-analyzing replaces any previous result for this repository.
    """
    result = await service.analyze_repository(repository_id)
    return _to_summary(result)


@router.get("/dependencies", response_model=list[DependencyEdgeResponse])
async def list_dependencies(
    project_id: UUID,
    repository_id: UUID,
    kind: DependencyKind | None = None,
    source_symbol_id: UUID | None = None,
    target_symbol_id: UUID | None = None,
    resolution_status: ResolutionStatus | None = None,
    limit: int = 100,
    offset: int = 0,
    service: DependencyAnalysisService = Depends(get_dependency_analysis_service),
) -> list[DependencyEdgeResponse]:
    """Dependency edges for this repository, optionally filtered, paginated."""
    edges = await service.get_edges(
        repository_id,
        kind=kind,
        source_symbol_id=source_symbol_id,
        target_symbol_id=target_symbol_id,
        resolution_status=resolution_status,
        limit=limit,
        offset=offset,
    )
    return [_to_response(edge) for edge in edges]


@router.get("/dependencies/{dependency_id}", response_model=DependencyEdgeResponse)
async def get_dependency(
    project_id: UUID,
    repository_id: UUID,
    dependency_id: UUID,
    service: DependencyAnalysisService = Depends(get_dependency_analysis_service),
) -> DependencyEdgeResponse:
    """A single dependency edge by id."""
    edge = await service.get_edge(dependency_id)
    return _to_response(edge)


def _to_summary(result: DependencyAnalysisResult) -> DependencyAnalysisSummaryResponse:
    resolved = sum(1 for e in result.edges if e.resolution_status is ResolutionStatus.RESOLVED)
    ambiguous = sum(1 for e in result.edges if e.resolution_status is ResolutionStatus.AMBIGUOUS)
    unresolved = sum(1 for e in result.edges if e.resolution_status is ResolutionStatus.UNRESOLVED)
    return DependencyAnalysisSummaryResponse(
        repository_id=result.repository_id,
        edge_count=len(result.edges),
        resolved_count=resolved,
        ambiguous_count=ambiguous,
        unresolved_count=unresolved,
        analyzed_at=result.analyzed_at,
    )


def _to_response(edge: DependencyEdge) -> DependencyEdgeResponse:
    return DependencyEdgeResponse(
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
