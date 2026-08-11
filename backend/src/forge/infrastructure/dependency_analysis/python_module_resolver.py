"""Python `ModuleResolver`.

Purpose:
    Resolve a Python `Import.module` string (absolute dotted, or
    leading-dot relative) to a `ParsedFile` within the same repository.

Responsibility:
    Path computation and matching against already-parsed files.
    No filesystem access and no source re-reading.

The resolver supports repositories where Python source files live below
a source-root prefix such as:

    backend/src/forge/domain/parsing/entities.py

while an absolute import is represented as:

    forge.domain.parsing.entities

In that case the resolver matches the module path against the suffix of
the repository path.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from forge.domain.dependency_analysis.entities import ResolutionStatus
from forge.domain.dependency_analysis.ports import ModuleResolution
from forge.domain.parsing.entities import Import, Language, ParsedFile


class PythonModuleResolver:
    """A `ModuleResolver` for Python's import syntax."""

    def resolve_import(
        self,
        import_: Import,
        source_file: ParsedFile,
        all_files: list[ParsedFile],
    ) -> ModuleResolution:
        python_files = {
            self._normalize_path(f.path): f
            for f in all_files
            if f.language is Language.PYTHON
        }

        source_path = PurePosixPath(self._normalize_path(source_file.path))
        source_dir = source_path.parent
        module = import_.module

        if module.startswith("."):
            return self._resolve_relative(
                module,
                import_,
                source_dir,
                python_files,
            )

        target = PurePosixPath(module.replace(".", "/"))

        return self._match(
            target,
            python_files,
            module,
        )

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

        # One dot means the current package/directory.
        # Two dots means the parent package, etc.
        for _ in range(dots - 1):
            base_dir = base_dir.parent

        if remainder:
            target = base_dir / remainder.replace(".", "/")

            return self._match(
                target,
                python_files,
                module,
            )

        # Bare relative imports such as:
        #
        #     from . import utils
        #
        # or:
        #
        #     from .. import models
        #
        # can refer to multiple modules when multiple names are imported.
        if len(import_.imported_names) != 1:
            return ModuleResolution(
                status=ResolutionStatus.AMBIGUOUS,
                target_file_id=None,
                detail=(
                    f"bare relative import {module!r} names "
                    f"{len(import_.imported_names)} submodules at once — "
                    "cannot identify a single target file"
                ),
            )

        name = import_.imported_names[0]

        return self._match(
            base_dir / name,
            python_files,
            f"{module}{name}",
        )

    def _match(
        self,
        target: PurePosixPath,
        python_files: dict[str, ParsedFile],
        raw_text: str,
    ) -> ModuleResolution:
        """Match a module path against parsed repository files.

        Supports both:

            forge/domain/parsing/entities.py

        and source-root-prefixed paths such as:

            backend/src/forge/domain/parsing/entities.py

        Exact matches are preferred. If there is no exact match, a
        suffix match is attempted so that source roots such as
        `backend/src`, `src`, etc. do not prevent resolution.
        """

        target_str = self._normalize_path(str(target))

        candidate_paths = (
            f"{target_str}.py",
            f"{target_str}/__init__.py",
        )

        candidates: list[ParsedFile] = []

        # ------------------------------------------------------------
        # 1. Prefer exact repository-path matches.
        # ------------------------------------------------------------
        for path in candidate_paths:
            found = python_files.get(path)

            if found is not None:
                candidates.append(found)

        # ------------------------------------------------------------
        # 2. If there is no exact match, support source-root prefixes.
        #
        # Example:
        #
        # target:
        #     forge/domain/parsing/entities.py
        #
        # repository:
        #     backend/src/forge/domain/parsing/entities.py
        #
        # The repository path ends with the module path, so it is a
        # valid match.
        #
        # Restricted to genuinely qualified (multi-segment) targets only —
        # `target.parts` has more than one component, i.e. the import was
        # dotted (`pkg.utils`) or nested-relative, never a bare top-level
        # name. A single-segment target (e.g. `models`, from a bare
        # `import models`) would trivially satisfy `path.endswith(f"/{candidate}")`
        # against *any* same-named file at *any* depth in the repository
        # (every path ending in `/models.py` "ends with" `/models.py`,
        # regardless of nesting) — that is not a source-root prefix, it is
        # a false positive that would resolve an absolute, repo-root-relative
        # bare import against an unrelated, arbitrarily-nested sibling file.
        # ------------------------------------------------------------
        if not candidates and len(target.parts) > 1:
            suffix_candidates: list[ParsedFile] = []

            for path, parsed_file in python_files.items():
                for candidate_path in candidate_paths:
                    if path.endswith(f"/{candidate_path}"):
                        suffix_candidates.append(parsed_file)
                        break

            candidates = suffix_candidates

        if not candidates:
            return ModuleResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                detail=(
                    f"no matching file in repository for {raw_text!r} "
                    "(likely an external or standard-library module)"
                ),
            )

        # Remove duplicate ParsedFile objects in case a path was matched
        # through more than one route.
        unique_candidates: list[ParsedFile] = []
        seen_ids = set()

        for candidate in candidates:
            if candidate.id not in seen_ids:
                seen_ids.add(candidate.id)
                unique_candidates.append(candidate)

        candidates = unique_candidates

        if len(candidates) > 1:
            return ModuleResolution(
                status=ResolutionStatus.AMBIGUOUS,
                target_file_id=candidates[0].id,
                detail=(
                    f"multiple files in the repository could satisfy "
                    f"{raw_text!r}"
                ),
            )

        return ModuleResolution(
            status=ResolutionStatus.RESOLVED,
            target_file_id=candidates[0].id,
            detail=None,
        )

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize a repository path for deterministic matching."""

        return str(PurePosixPath(path.replace("\\", "/"))).lstrip("./")