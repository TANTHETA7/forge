"""Dispatches to a per-language `ModuleResolver` by file language.

Purpose:       Let `DependencyAnalysisService` stay agnostic to "how many
                languages are configured" — it depends on exactly one
                `ModuleResolver`, this one, which routes each import to the
                resolver for its source file's language.
Responsibility: Dispatch only — no resolution logic of its own.
Depends on:    domain/dependency_analysis/{entities,ports}.py,
                domain/parsing/entities.py.
Depended on by: api/dependencies.py (constructs this with the full
                `{Language: ModuleResolver}` map).

Mirrors `infrastructure/parsing/registry.py::DefaultParserRegistry`'s pattern
(Phase 3) — one dict-dispatch class per "select the right per-language
implementation" need, rather than an if/elif chain duplicated wherever
language selection matters.
"""

from __future__ import annotations

from forge.domain.dependency_analysis.entities import ResolutionStatus
from forge.domain.dependency_analysis.ports import ModuleResolution, ModuleResolver
from forge.domain.parsing.entities import Import, Language, ParsedFile


class CompositeModuleResolver:
    """A `ModuleResolver` that dispatches to a per-language resolver based on
    `source_file.language`."""

    def __init__(self, resolvers: dict[Language, ModuleResolver]) -> None:
        self._resolvers = resolvers

    def resolve_import(
        self, import_: Import, source_file: ParsedFile, all_files: list[ParsedFile]
    ) -> ModuleResolution:
        resolver = self._resolvers.get(source_file.language)
        if resolver is None:
            return ModuleResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                detail=f"no module resolver configured for language {source_file.language.value!r}",
            )
        return resolver.resolve_import(import_, source_file, all_files)
