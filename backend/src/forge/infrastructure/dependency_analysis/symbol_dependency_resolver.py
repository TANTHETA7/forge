"""Language-agnostic CALLS/INHERITS resolver.

Purpose:       Resolve a call site's callee expression, or a class's base-class
                name, to a specific `Symbol` within the same repository.
Responsibility: Pure computation over already-parsed `ParsedFile`/`Symbol`/
                `Import` data — no I/O, no tree-sitter, no filesystem access.
"""

from __future__ import annotations

from forge.domain.dependency_analysis.entities import (
    ResolutionStatus,
    SymbolResolution,
)
from forge.domain.dependency_analysis.ports import ModuleResolver
from forge.domain.parsing.entities import (
    CallReference,
    Import,
    ParsedFile,
    Symbol,
    SymbolKind,
)


class SymbolDependencyResolver:
    """Resolves CALLS/INHERITS relationships."""

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

        # Instance method calls.
        if callee.startswith("self.") or callee.startswith("this."):
            method_name = callee.split(".", 1)[1]

            return self._resolve_instance_call(
                method_name,
                caller,
                file,
            )

        # Qualified calls such as:
        #   module.function()
        #   package.Class()
        #
        # These currently require exactly one dot because the receiver type
        # of expressions such as obj.attr.method() is not statically known.
        if "." in callee:
            return self._resolve_qualified(
                callee,
                file,
                all_files,
                SymbolKind.FUNCTION,
            )

        # A bare call can refer to either a function or a class.
        #
        # Example:
        #   helper()
        #   Settings()
        #   NotFoundError()
        #
        # Previously only FUNCTION was checked, which caused constructor/class
        # calls to be incorrectly reported as unresolved.
        function_result = self._resolve_bare_name(
            callee,
            file,
            all_files,
            SymbolKind.FUNCTION,
        )

        if function_result.status is ResolutionStatus.RESOLVED:
            return function_result

        class_result = self._resolve_bare_name(
            callee,
            file,
            all_files,
            SymbolKind.CLASS,
        )

        if class_result.status is ResolutionStatus.RESOLVED:
            return class_result

        # If either lookup found multiple possible definitions, preserve the
        # ambiguity rather than incorrectly reporting the call as unresolved.
        if (
            function_result.status is ResolutionStatus.AMBIGUOUS
            or class_result.status is ResolutionStatus.AMBIGUOUS
        ):
            return SymbolResolution(
                status=ResolutionStatus.AMBIGUOUS,
                target_file_id=None,
                target_symbol_id=None,
                detail=f"multiple possible definitions for {callee!r}",
            )

        # Neither a function nor a class could be resolved.
        return function_result

    def resolve_inheritance(
        self,
        base_class_name: str,
        file: ParsedFile,
        all_files: list[ParsedFile],
    ) -> SymbolResolution:
        """Resolve a class inheritance target."""

        if "." in base_class_name:
            return self._resolve_qualified(
                base_class_name,
                file,
                all_files,
                SymbolKind.CLASS,
            )

        return self._resolve_bare_name(
            base_class_name,
            file,
            all_files,
            SymbolKind.CLASS,
        )

    def _resolve_instance_call(
        self,
        method_name: str,
        caller: Symbol,
        file: ParsedFile,
    ) -> SymbolResolution:
        """Resolve self.method()/this.method() against the immediate class."""

        if caller.parent_symbol_id is None:
            return SymbolResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                target_symbol_id=None,
                detail="call has no enclosing class to resolve against",
            )

        candidates = [
            symbol
            for symbol in file.symbols
            if (
                symbol.parent_symbol_id == caller.parent_symbol_id
                and symbol.kind is SymbolKind.METHOD
                and symbol.name == method_name
            )
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
                detail=(
                    f"multiple methods named {method_name!r} "
                    "on the same class"
                ),
            )

        return SymbolResolution(
            status=ResolutionStatus.UNRESOLVED,
            target_file_id=None,
            target_symbol_id=None,
            detail=(
                f"{method_name!r} not found on the immediate class — "
                "inherited methods are not resolved"
            ),
        )

    def _resolve_qualified(
        self,
        expression: str,
        file: ParsedFile,
        all_files: list[ParsedFile],
        target_kind: SymbolKind,
    ) -> SymbolResolution:
        """Resolve expressions such as module.function or module.Class."""

        # We only resolve one-level qualified expressions.
        #
        # obj.attr.method has two dots and requires knowing the type of obj,
        # which is outside the resolver's current static-analysis scope.
        if expression.count(".") != 1:
            return SymbolResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                target_symbol_id=None,
                detail="receiver/qualifier type is not statically known",
            )

        module_name, _, target_name = expression.partition(".")

        if not module_name or not target_name:
            return SymbolResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                target_symbol_id=None,
                detail="invalid qualified expression",
            )

        files_by_id = {
            file_.id: file_
            for file_ in all_files
        }

        found: dict[object, tuple[ParsedFile, Symbol]] = {}

        # Find imports that bind the module/qualifier locally.
        for import_ in _imports_binding(file, module_name):
            resolution = self._module_resolver.resolve_import(
                import_,
                file,
                all_files,
            )

            target_file_id = resolution.target_file_id

            if (
                resolution.status is not ResolutionStatus.RESOLVED
                or target_file_id is None
            ):
                continue

            target_file = files_by_id.get(target_file_id)

            if target_file is None:
                continue

            symbol = _find_top_level(
                target_file,
                target_name,
                target_kind,
            )

            if symbol is not None:
                found[symbol.id] = (
                    target_file,
                    symbol,
                )

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
                detail=(
                    f"multiple imported modules define "
                    f"{target_name!r} for {module_name!r}"
                ),
            )

        imports = _imports_binding(
            file,
            module_name,
        )

        if imports:
            return SymbolResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                target_symbol_id=None,
                detail=(
                    f"{target_name!r} not found in the module bound to "
                    f"{module_name!r}"
                ),
            )

        return SymbolResolution(
            status=ResolutionStatus.UNRESOLVED,
            target_file_id=None,
            target_symbol_id=None,
            detail=(
                f"{module_name!r} is not a known import binding "
                "in this file"
            ),
        )

    def _resolve_bare_name(
        self,
        name: str,
        file: ParsedFile,
        all_files: list[ParsedFile],
        target_kind: SymbolKind,
    ) -> SymbolResolution:
        """Resolve an unqualified function/class name."""

        # ---------------------------------------------------------------
        # 1. Same-file top-level definitions
        # ---------------------------------------------------------------
        local = [
            symbol
            for symbol in file.symbols
            if (
                symbol.name == name
                and symbol.kind is target_kind
                and symbol.parent_symbol_id is None
            )
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

        files_by_id = {
            file_.id: file_
            for file_ in all_files
        }

        found: dict[object, tuple[ParsedFile, Symbol]] = {}

        # ---------------------------------------------------------------
        # 2. Explicit imports
        # ---------------------------------------------------------------
        for import_ in _imports_binding(
            file,
            name,
        ):
            resolution = self._module_resolver.resolve_import(
                import_,
                file,
                all_files,
            )

            target_file_id = resolution.target_file_id

            if (
                resolution.status is not ResolutionStatus.RESOLVED
                or target_file_id is None
            ):
                continue

            target_file = files_by_id.get(target_file_id)

            if target_file is None:
                continue

            symbol = _find_top_level(
                target_file,
                name,
                target_kind,
            )

            if symbol is not None:
                found[symbol.id] = (
                    target_file,
                    symbol,
                )

        # ---------------------------------------------------------------
        # 3. Wildcard imports
        # ---------------------------------------------------------------
        for import_ in _wildcard_imports(file):
            resolution = self._module_resolver.resolve_import(
                import_,
                file,
                all_files,
            )

            target_file_id = resolution.target_file_id

            if (
                resolution.status is not ResolutionStatus.RESOLVED
                or target_file_id is None
            ):
                continue

            target_file = files_by_id.get(target_file_id)

            if target_file is None:
                continue

            symbol = _find_top_level(
                target_file,
                name,
                target_kind,
            )

            if symbol is not None:
                found[symbol.id] = (
                    target_file,
                    symbol,
                )

        # ---------------------------------------------------------------
        # 4. Final result
        # ---------------------------------------------------------------
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
            detail=(
                f"no definition found for {name!r} "
                "(likely external, or defined dynamically)"
            ),
        )


def _imports_binding(
    file: ParsedFile,
    name: str,
) -> list[Import]:
    """Return imports that bind `name` locally."""

    return [
        import_
        for import_ in file.imports
        if import_.alias == name
        or name in import_.imported_names
    ]


def _wildcard_imports(
    file: ParsedFile,
) -> list[Import]:
    """Return wildcard imports."""

    return [
        import_
        for import_ in file.imports
        if "*" in import_.imported_names
    ]


def _find_top_level(
    file: ParsedFile,
    name: str,
    kind: SymbolKind,
) -> Symbol | None:
    """Find exactly one top-level symbol with the given name and kind."""

    matches = [
        symbol
        for symbol in file.symbols
        if (
            symbol.name == name
            and symbol.kind is kind
            and symbol.parent_symbol_id is None
        )
    ]

    return matches[0] if len(matches) == 1 else None
