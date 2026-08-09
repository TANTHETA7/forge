"""Python `ModuleResolver`.

Purpose:       Resolve a Python `Import.module` string (absolute dotted, or
                leading-dot relative) to a `ParsedFile` within the same
                repository.
Responsibility: Path computation and matching against already-parsed files —
                no filesystem access, no re-reading source (the repository's
                `ParsedFile`s, already in memory, are the only input).
Depends on:    domain/dependency_analysis/{entities,ports}.py,
                domain/parsing/entities.py.
Depended on by: application/dependency_analysis/service.py.

Scope, stated rather than silently gapped: a bare relative import naming
multiple submodules at once (`from . import a, b`, where `a` and `b` are
distinct sibling files) genuinely implies more than one target file — one
`Import` record can only produce one `ModuleResolution` (see domain/
dependency_analysis/ports.py::ModuleResolver), so this specific form resolves
AMBIGUOUS rather than arbitrarily picking one of several real targets. The far
more common single-name form (`from . import utils`) and every dotted form
(`from .models import User`, `from ..pkg.mod import X`, `import a.b.c`) resolve
properly.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from forge.domain.dependency_analysis.entities import ResolutionStatus
from forge.domain.dependency_analysis.ports import ModuleResolution
from forge.domain.parsing.entities import Import, Language, ParsedFile


class PythonModuleResolver:
    """A `ModuleResolver` for Python's import syntax."""

    def resolve_import(
        self, import_: Import, source_file: ParsedFile, all_files: list[ParsedFile]
    ) -> ModuleResolution:
        python_files = {f.path: f for f in all_files if f.language is Language.PYTHON}
        source_dir = PurePosixPath(source_file.path).parent
        module = import_.module

        if module.startswith("."):
            return self._resolve_relative(module, import_, source_dir, python_files)
        return self._match(PurePosixPath(module.replace(".", "/")), python_files, module)

    def _resolve_relative(
        self,
        module: str,
        import_: Import,
        source_dir: PurePosixPath,
        python_files: dict[str, ParsedFile],
    ) -> ModuleResolution:
        dots = len(module) - len(module.lstrip("."))
        remainder = module[dots:]

        base_dir = source_dir
        for _ in range(dots - 1):
            base_dir = base_dir.parent

        if remainder:
            target = base_dir / remainder.replace(".", "/")
            return self._match(target, python_files, module)

        # Bare dots (`from . import x` / `from .. import x`) — each imported
        # name is a candidate submodule of `base_dir`, not a name inside
        # `module` itself (there is no further module path to resolve).
        if len(import_.imported_names) != 1:
            return ModuleResolution(
                status=ResolutionStatus.AMBIGUOUS,
                target_file_id=None,
                detail=(
                    f"bare relative import {module!r} names "
                    f"{len(import_.imported_names)} submodules at once — cannot "
                    "identify a single target file"
                ),
            )
        name = import_.imported_names[0]
        return self._match(base_dir / name, python_files, f"{module}{name}")

    def _match(
        self, target: PurePosixPath, python_files: dict[str, ParsedFile], raw_text: str
    ) -> ModuleResolution:
        candidates: list[ParsedFile] = []
        for path in (f"{target}.py", f"{target}/__init__.py"):
            found = python_files.get(path)
            if found is not None:
                candidates.append(found)

        if not candidates:
            return ModuleResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                detail=(
                    f"no matching file in repository for {raw_text!r} "
                    "(likely an external or standard-library module)"
                ),
            )
        if len(candidates) > 1:
            return ModuleResolution(
                status=ResolutionStatus.AMBIGUOUS,
                target_file_id=candidates[0].id,
                detail=f"multiple files in the repository could satisfy {raw_text!r}",
            )
        return ModuleResolution(
            status=ResolutionStatus.RESOLVED, target_file_id=candidates[0].id, detail=None
        )
