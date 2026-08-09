"""JavaScript/TypeScript `ModuleResolver`.

Purpose:       Resolve a JS/TS `Import.module` string (a relative path) to a
                `ParsedFile` within the same repository.
Responsibility: Path computation and matching against already-parsed files —
                no filesystem access, no re-reading source. One implementation
                shared by JavaScript and TypeScript (registry.py already treats
                them as needing separate `LanguageParser`s but the same import-
                resolution algorithm — both use ESM relative-path syntax).
Depends on:    domain/dependency_analysis/{entities,ports}.py,
                domain/parsing/entities.py.
Depended on by: application/dependency_analysis/service.py.

Bare/package specifiers (`"react"`, `"lodash"` — anything not starting with
`.`) are always UNRESOLVED, never attempted against repository files — under
ESM convention a non-relative specifier always resolves through node_modules,
never to a sibling source file. The one real-world exception this doesn't
model is a bundler/tsconfig path alias (`"@app/utils"` mapped to `src/utils`)
— Forge has no config-file parsing to learn that mapping from, so such imports
correctly come out UNRESOLVED rather than a guessed match.

`posixpath.normpath` (not `pathlib`'s `/` operator) does the `../`/`./`
collapsing here — verified empirically that `PurePosixPath` does NOT collapse
`..` segments on its own (`PurePosixPath("src/lib") / "../utils"` stays
`"src/lib/../utils"`, not `"src/utils"`), unlike `Path.resolve()` which needs a
real filesystem. `posixpath.normpath` does the same collapsing purely
lexically, which is what's needed here (only ever-parsed file paths, not real
paths, are involved).
"""

from __future__ import annotations

import posixpath
from pathlib import PurePosixPath

from forge.domain.dependency_analysis.entities import ResolutionStatus
from forge.domain.dependency_analysis.ports import ModuleResolution
from forge.domain.parsing.entities import Import, Language, ParsedFile

_CANDIDATE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx")
_ECMASCRIPT_LANGUAGES = frozenset({Language.JAVASCRIPT, Language.TYPESCRIPT})


class EcmaScriptModuleResolver:
    """A `ModuleResolver` for JavaScript/TypeScript's relative-import syntax."""

    def resolve_import(
        self, import_: Import, source_file: ParsedFile, all_files: list[ParsedFile]
    ) -> ModuleResolution:
        if not import_.module.startswith("."):
            return ModuleResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                detail=(
                    f"{import_.module!r} is a bare package specifier — always "
                    "external (node_modules), never a repository file"
                ),
            )

        candidate_files = {f.path: f for f in all_files if f.language in _ECMASCRIPT_LANGUAGES}
        source_dir = str(PurePosixPath(source_file.path).parent)
        target = posixpath.normpath(posixpath.join(source_dir, import_.module))

        matches: list[ParsedFile] = []
        for suffix in _CANDIDATE_SUFFIXES:
            for candidate_path in (f"{target}{suffix}", f"{target}/index{suffix}"):
                found = candidate_files.get(candidate_path)
                if found is not None:
                    matches.append(found)

        if not matches:
            return ModuleResolution(
                status=ResolutionStatus.UNRESOLVED,
                target_file_id=None,
                detail=f"no matching file in repository for {import_.module!r}",
            )
        if len(matches) > 1:
            return ModuleResolution(
                status=ResolutionStatus.AMBIGUOUS,
                target_file_id=matches[0].id,
                detail=f"multiple files in the repository could satisfy {import_.module!r}",
            )
        return ModuleResolution(
            status=ResolutionStatus.RESOLVED, target_file_id=matches[0].id, detail=None
        )
