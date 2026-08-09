"""Language-agnostic CALLS/INHERITS resolver.

Purpose:       Resolve a call site's callee expression, or a class's base-class
                name, to a specific `Symbol` within the same repository.
Responsibility: Pure computation over already-parsed `ParsedFile`/`Symbol`/
                `Import` data — no I/O, no tree-sitter, no filesystem access.
Depends on:    domain/dependency_analysis/{entities,ports}.py,
                domain/parsing/entities.py.
Depended on by: application/dependency_analysis/service.py.

Why this is ONE class for all three languages, unlike `ModuleResolver` (which
has one implementation per language): once Phase 3's parsers have normalized a
call site down to `CallReference.callee_expression` (raw text: `"helper"`,
`"self.method_b"`, `"obj.attr.method"`, `"module.func"`) and a class down to
`Symbol.base_class_names` (raw text: `"Base"`, `"pkg.Base"`), resolving either
is the *same* algorithm regardless of source language — same-file lookup,
import-binding lookup, an instance-prefixed lookup against the enclosing class.
The one place a genuinely language-specific decision would matter (which import
syntax `module.func()`'s `module` segment resolves through) is delegated to the
injected `ModuleResolver` rather than duplicated here — this class never
inspects a raw module string itself, only asks the resolver it was built with.

Both `self.` and `this.` prefixes are checked unconditionally (not branched on
detected language) — a Python file will never coincidentally contain a
`this.`-prefixed call, so checking both is harmless, and it's what keeps this
class language-agnostic rather than needing a language parameter.

Scope, stated rather than silently gapped (see docs/architecture/
04-dependency-analysis.md, "Risks / limitations"):
- `self.`/`this.` calls resolve against the immediate enclosing class's own
  methods only — inherited methods (from a base class, resolvable or not) are
  not walked. Guessing which base class actually defines the method would risk
  exactly the "pretend it's resolvable" outcome the brief warns against more
  than stopping at UNRESOLVED does.
- A qualified expression (`module.func`, `pkg.Base`) is only attempted when it
  has exactly one dot — `obj.attr.method` (two dots) has no statically known
  receiver type and is always UNRESOLVED.
- AMBIGUOUS is reserved for a genuine tie: more than one distinct import
  (commonly, more than one wildcard `from x import *`) resolves to a different
  file that itself defines a same-named target.
"""

from __future__ import annotations

from forge.domain.dependency_analysis.entities import ResolutionStatus, SymbolResolution
from forge.domain.dependency_analysis.ports import ModuleResolver
from forge.domain.parsing.entities import CallReference, Import, ParsedFile, Symbol, SymbolKind


class SymbolDependencyResolver:
    """Resolves CALLS/INHERITS relationships. Not a `domain/dependency_analysis/
    ports.py` Protocol implementation — there is exactly one of these, used for
    every language, so no port/swap point is warranted (see this module's own
    docstring)."""

    def __init__(self, module_resolver: ModuleResolver) -> None:
        self._module_resolver = module_resolver

    def resolve_call(
        self,
        call: CallReference,
        caller: Symbol,
        file: ParsedFile,
        all_files: list[ParsedFile],
    ) -> SymbolResolution:
        callee = call.callee_expression
        if callee.startswith("self.") or callee.startswith("this."):
            method_name = callee.split(".", 1)[1]
            return self._resolve_instance_call(method_name, caller, file)
        if "." in callee:
            return self._resolve_qualified(callee, file, all_files, SymbolKind.FUNCTION)
        return self._resolve_bare_name(callee, file, all_files, SymbolKind.FUNCTION)

    def resolve_inheritance(
        self, base_class_name: str, file: ParsedFile, all_files: list[ParsedFile]
    ) -> SymbolResolution:
        if "." in base_class_name:
            return self._resolve_qualified(base_class_name, file, all_files, SymbolKind.CLASS)
        return self._resolve_bare_name(base_class_name, file, all_files, SymbolKind.CLASS)

    def _resolve_instance_call(
        self, method_name: str, caller: Symbol, file: ParsedFile
    ) -> SymbolResolution:
        if caller.parent_symbol_id is None:
            return SymbolResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                target_symbol_id=None,
                detail="call has no enclosing class to resolve against",
            )
        candidates = [
            s
            for s in file.symbols
            if s.parent_symbol_id == caller.parent_symbol_id
            and s.kind is SymbolKind.METHOD
            and s.name == method_name
        ]
        if len(candidates) == 1:
            return SymbolResolution(
                status=ResolutionStatus.RESOLVED,
                target_file_id=file.id,
                target_symbol_id=candidates[0].id,
                detail=None,
            )
        if len(candidates) > 1:
            return SymbolResolution(
                status=ResolutionStatus.AMBIGUOUS,
                target_file_id=file.id,
                target_symbol_id=None,
                detail=f"multiple methods named {method_name!r} on the same class",
            )
        return SymbolResolution(
            status=ResolutionStatus.UNRESOLVED,
            target_file_id=None,
            target_symbol_id=None,
            detail=(
                f"{method_name!r} not found on the immediate class — inherited "
                "methods are not resolved (see docs/architecture/"
                "04-dependency-analysis.md, \"Risks / limitations\")"
            ),
        )

    def _resolve_qualified(
        self,
        expression: str,
        file: ParsedFile,
        all_files: list[ParsedFile],
        target_kind: SymbolKind,
    ) -> SymbolResolution:
        if expression.count(".") != 1:
            return SymbolResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                target_symbol_id=None,
                detail="receiver/qualifier type is not statically known",
            )
        module_name, _, target_name = expression.partition(".")
        files_by_id = {f.id: f for f in all_files}

        for import_ in _imports_binding(file, module_name):
            resolution = self._module_resolver.resolve_import(import_, file, all_files)
            target_file_id = resolution.target_file_id
            if resolution.status is not ResolutionStatus.RESOLVED or target_file_id is None:
                continue
            target_file = files_by_id.get(target_file_id)
            if target_file is None:
                continue
            symbol = _find_top_level(target_file, target_name, target_kind)
            if symbol is not None:
                return SymbolResolution(
                    status=ResolutionStatus.RESOLVED,
                    target_file_id=target_file.id,
                    target_symbol_id=symbol.id,
                    detail=None,
                )
            return SymbolResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=target_file.id,
                target_symbol_id=None,
                detail=f"{target_name!r} not found in the module bound to {module_name!r}",
            )

        return SymbolResolution(
            status=ResolutionStatus.UNRESOLVED,
            target_file_id=None,
            target_symbol_id=None,
            detail=f"{module_name!r} is not a known import binding in this file",
        )

    def _resolve_bare_name(
        self, name: str, file: ParsedFile, all_files: list[ParsedFile], target_kind: SymbolKind
    ) -> SymbolResolution:
        local = [
            s
            for s in file.symbols
            if s.name == name and s.kind is target_kind and s.parent_symbol_id is None
        ]
        if len(local) == 1:
            return SymbolResolution(
                status=ResolutionStatus.RESOLVED,
                target_file_id=file.id,
                target_symbol_id=local[0].id,
                detail=None,
            )
        if len(local) > 1:
            return SymbolResolution(
                status=ResolutionStatus.AMBIGUOUS,
                target_file_id=file.id,
                target_symbol_id=None,
                detail=f"multiple same-file definitions named {name!r}",
            )

        files_by_id = {f.id: f for f in all_files}
        found: dict[object, tuple[ParsedFile, Symbol]] = {}

        for import_ in _imports_binding(file, name):
            resolution = self._module_resolver.resolve_import(import_, file, all_files)
            target_file_id = resolution.target_file_id
            if resolution.status is not ResolutionStatus.RESOLVED or target_file_id is None:
                continue
            target_file = files_by_id.get(target_file_id)
            if target_file is None:
                continue
            symbol = _find_top_level(target_file, name, target_kind)
            if symbol is not None:
                found[symbol.id] = (target_file, symbol)

        for import_ in _wildcard_imports(file):
            resolution = self._module_resolver.resolve_import(import_, file, all_files)
            target_file_id = resolution.target_file_id
            if resolution.status is not ResolutionStatus.RESOLVED or target_file_id is None:
                continue
            target_file = files_by_id.get(target_file_id)
            if target_file is None:
                continue
            symbol = _find_top_level(target_file, name, target_kind)
            if symbol is not None:
                found[symbol.id] = (target_file, symbol)

        if len(found) == 1:
            target_file, symbol = next(iter(found.values()))
            return SymbolResolution(
                status=ResolutionStatus.RESOLVED,
                target_file_id=target_file.id,
                target_symbol_id=symbol.id,
                detail=None,
            )
        if len(found) > 1:
            return SymbolResolution(
                status=ResolutionStatus.AMBIGUOUS,
                target_file_id=None,
                target_symbol_id=None,
                detail=f"{len(found)} imported modules define {name!r}",
            )

        return SymbolResolution(
            status=ResolutionStatus.UNRESOLVED,
            target_file_id=None,
            target_symbol_id=None,
            detail=f"no definition found for {name!r} (likely external, or defined dynamically)",
        )


def _imports_binding(file: ParsedFile, name: str) -> list[Import]:
    """Every import in `file` that binds `name` locally — via alias, or as one
    of its explicitly imported names."""
    return [
        import_
        for import_ in file.imports
        if import_.alias == name or name in import_.imported_names
    ]


def _wildcard_imports(file: ParsedFile) -> list[Import]:
    return [import_ for import_ in file.imports if "*" in import_.imported_names]


def _find_top_level(file: ParsedFile, name: str, kind: SymbolKind) -> Symbol | None:
    matches = [
        s for s in file.symbols if s.name == name and s.kind is kind and s.parent_symbol_id is None
    ]
    return matches[0] if len(matches) == 1 else None
