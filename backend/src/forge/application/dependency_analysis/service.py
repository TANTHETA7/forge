"""Dependency analysis application service.

Purpose:       Orchestrate resolving IMPORTS, CALLS, and INHERITS relationships
                from an already-parsed repository's data.
Responsibility: Sequencing only. It never touches the filesystem, tree-sitter,
                or SQLAlchemy directly — those are reached exclusively through
                the ports/collaborators this class is constructed with (domain/
                dependency_analysis/ports.py, domain/parsing/ports.py,
                domain/repository/ports.py, plus the language-agnostic
                `SymbolDependencyResolver`), the same rule Phase 2/3's
                application services already follow.

                Reuses Phase 3's `ParsedFileRepository` to load already-parsed
                files/symbols/imports — no new file reads, no new tree-sitter
                calls (see docs/architecture/04-dependency-analysis.md).

                A single dependency's resolution failure (an unexpected
                exception from `ModuleResolver`/`SymbolDependencyResolver`, not
                the normal RESOLVED/AMBIGUOUS/UNRESOLVED outcomes they're
                expected to return) is caught and degraded to an UNRESOLVED
                edge rather than aborting the rest of the repository — same
                "one bad thing doesn't abort the whole run" discipline Phase
                3's `ParsingService` already applies.

                Pure in-memory computation plus async DB calls — no
                `anyio.to_thread` needed (unlike Phase 2/3, there is no
                blocking filesystem or subprocess I/O here).
Depends on:    domain/dependency_analysis/{entities,ids,ports}.py,
                domain/parsing/ports.py, domain/repository/ports.py,
                domain/errors.py, infrastructure/dependency_analysis/
                symbol_dependency_resolver.py (concrete, not a port — see that
                module's own docstring for why).
Depended on by: api/dependencies.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from forge.domain.dependency_analysis.entities import (
    DependencyAnalysisResult,
    DependencyEdge,
    DependencyKind,
    ResolutionStatus,
    SymbolResolution,
)
from forge.domain.dependency_analysis.ids import deterministic_id
from forge.domain.dependency_analysis.ports import (
    DependencyEdgeRepository,
    ModuleResolution,
    ModuleResolver,
)
from forge.domain.errors import NotFoundError, UnsupportedRepositoryStateError
from forge.domain.parsing.entities import (
    CallReference,
    Import,
    ParsedFile,
    Symbol,
    SymbolKind,
)
from forge.domain.parsing.ports import ParsedFileRepository
from forge.domain.repository.entities import RepositoryStatus
from forge.domain.repository.ports import RepositoryRepository
from forge.infrastructure.dependency_analysis.symbol_dependency_resolver import (
    SymbolDependencyResolver,
)


class DependencyAnalysisService:
    def __init__(
        self,
        repositories: RepositoryRepository,
        parsed_files: ParsedFileRepository,
        dependency_edges: DependencyEdgeRepository,
        module_resolver: ModuleResolver,
        symbol_resolver: SymbolDependencyResolver,
    ) -> None:
        self._repositories = repositories
        self._parsed_files = parsed_files
        self._dependency_edges = dependency_edges
        self._module_resolver = module_resolver
        self._symbol_resolver = symbol_resolver

    async def analyze_repository(
        self,
        repository_id: UUID,
    ) -> DependencyAnalysisResult:
        """Run dependency analysis and return (and persist) the result.

        Raises:
            NotFoundError: `repository_id` doesn't exist.
            UnsupportedRepositoryStateError: the repository isn't `READY`, or
                is `READY` but has no parsed files yet.
        """
        repository = await self._repositories.get_by_id(repository_id)

        if repository is None:
            raise NotFoundError(
                f"Repository {repository_id} not found"
            )

        if repository.status is not RepositoryStatus.READY:
            raise UnsupportedRepositoryStateError(
                f"Repository {repository_id} is "
                f"{repository.status.value!r}, not READY"
            )

        files = await self._parsed_files.get_files(repository_id)

        if not files:
            raise UnsupportedRepositoryStateError(
                f"Repository {repository_id} has not been parsed yet — run "
                "POST .../parse first"
            )

        edges: list[DependencyEdge] = []

        for source_file in files:
            # ---------------------------------------------------------
            # IMPORTS
            # ---------------------------------------------------------
            for import_index, import_ in enumerate(source_file.imports):
                edges.append(
                    self._resolve_import(
                        repository_id,
                        source_file,
                        import_,
                        files,
                        occurrence_index=import_index,
                    )
                )

            # ---------------------------------------------------------
            # CALLS / INHERITS
            # ---------------------------------------------------------
            for symbol in source_file.symbols:
                if symbol.kind is SymbolKind.CLASS:
                    for inheritance_index, base_class_name in enumerate(
                        symbol.base_class_names
                    ):
                        edges.append(
                            self._resolve_inheritance(
                                repository_id,
                                source_file,
                                symbol,
                                base_class_name,
                                files,
                                occurrence_index=inheritance_index,
                            )
                        )
                else:
                    for call_index, call in enumerate(symbol.calls):
                        edges.append(
                            self._resolve_call(
                                repository_id,
                                source_file,
                                symbol,
                                call,
                                files,
                                occurrence_index=call_index,
                            )
                        )

        result = DependencyAnalysisResult(
            repository_id=repository_id,
            edges=tuple(edges),
            analyzed_at=datetime.now(UTC),
        )

        await self._dependency_edges.save_analysis_result(
            repository_id,
            result.edges,
        )

        return result

    def _resolve_import(
        self,
        repository_id: UUID,
        source_file: ParsedFile,
        import_: Import,
        all_files: list[ParsedFile],
        *,
        occurrence_index: int = 0,
    ) -> DependencyEdge:
        try:
            resolution = self._module_resolver.resolve_import(
                import_,
                source_file,
                all_files,
            )
        except Exception as exc:
            # A resolver failure for one import must not abort
            # dependency analysis for the entire repository.
            resolution = ModuleResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                detail=(
                    f"unexpected failure while resolving "
                    f"{import_.module!r}: {exc}"
                ),
            )

        edge_id = deterministic_id(
            str(repository_id),
            DependencyKind.IMPORTS.value,
            str(source_file.id),
            import_.module,
            str(import_.location.start_line),
            str(import_.location.end_line),
            str(import_.location.start_column),
            str(import_.location.end_column),
            str(occurrence_index),
        )

        return DependencyEdge(
            id=edge_id,
            repository_id=repository_id,
            kind=DependencyKind.IMPORTS,
            resolution_status=resolution.status,
            source_file_id=source_file.id,
            source_symbol_id=None,
            target_file_id=resolution.target_file_id,
            target_symbol_id=None,
            raw_target_expression=import_.module,
            location=import_.location,
            detail=resolution.detail,
        )

    def _resolve_call(
        self,
        repository_id: UUID,
        source_file: ParsedFile,
        caller: Symbol,
        call: CallReference,
        all_files: list[ParsedFile],
        *,
        occurrence_index: int = 0,
    ) -> DependencyEdge:
        try:
            resolution = self._symbol_resolver.resolve_call(
                call,
                caller,
                source_file,
                all_files,
            )
        except Exception as exc:
            # A resolver failure for one call must not abort
            # dependency analysis for the entire repository.
            resolution = SymbolResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                target_symbol_id=None,
                detail=(
                    f"unexpected failure while resolving "
                    f"{call.callee_expression!r}: {exc}"
                ),
            )

        edge_id = deterministic_id(
            str(repository_id),
            DependencyKind.CALLS.value,
            str(caller.id),
            call.callee_expression,
            str(call.location.start_line),
            str(call.location.end_line),
            str(call.location.start_column),
            str(call.location.end_column),
            str(occurrence_index),
        )

        return DependencyEdge(
            id=edge_id,
            repository_id=repository_id,
            kind=DependencyKind.CALLS,
            resolution_status=resolution.status,
            source_file_id=source_file.id,
            source_symbol_id=caller.id,
            target_file_id=resolution.target_file_id,
            target_symbol_id=resolution.target_symbol_id,
            raw_target_expression=call.callee_expression,
            location=call.location,
            detail=resolution.detail,
        )

    def _resolve_inheritance(
        self,
        repository_id: UUID,
        source_file: ParsedFile,
        subclass: Symbol,
        base_class_name: str,
        all_files: list[ParsedFile],
        *,
        occurrence_index: int = 0,
    ) -> DependencyEdge:
        try:
            resolution = self._symbol_resolver.resolve_inheritance(
                base_class_name,
                source_file,
                all_files,
            )
        except Exception as exc:
            # A resolver failure for one base class must not abort
            # dependency analysis for the entire repository.
            resolution = SymbolResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                target_symbol_id=None,
                detail=(
                    f"unexpected failure while resolving "
                    f"{base_class_name!r}: {exc}"
                ),
            )

        edge_id = deterministic_id(
            str(repository_id),
            DependencyKind.INHERITS.value,
            str(subclass.id),
            base_class_name,
            str(subclass.location.start_line),
            str(subclass.location.end_line),
            str(subclass.location.start_column),
            str(subclass.location.end_column),
            str(occurrence_index),
        )

        return DependencyEdge(
            id=edge_id,
            repository_id=repository_id,
            kind=DependencyKind.INHERITS,
            resolution_status=resolution.status,
            source_file_id=source_file.id,
            source_symbol_id=subclass.id,
            target_file_id=resolution.target_file_id,
            target_symbol_id=resolution.target_symbol_id,
            raw_target_expression=base_class_name,
            location=subclass.location,
            detail=resolution.detail,
        )

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
        await self._require_repository(repository_id)

        return await self._dependency_edges.get_edges(
            repository_id,
            kind=kind,
            source_symbol_id=source_symbol_id,
            target_symbol_id=target_symbol_id,
            resolution_status=resolution_status,
            limit=limit,
            offset=offset,
        )

    async def get_edge(
        self,
        dependency_id: UUID,
    ) -> DependencyEdge:
        edge = await self._dependency_edges.get_edge(
            dependency_id
        )

        if edge is None:
            raise NotFoundError(
                f"Dependency edge {dependency_id} not found"
            )

        return edge

    async def _require_repository(
        self,
        repository_id: UUID,
    ) -> None:
        if await self._repositories.get_by_id(repository_id) is None:
            raise NotFoundError(
                f"Repository {repository_id} not found"
            )
