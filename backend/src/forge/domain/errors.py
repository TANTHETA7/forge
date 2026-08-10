"""Shared domain error hierarchy.

Purpose:       Give every layer above infrastructure one exception family to raise
                and catch, so driver-specific exceptions (``zipfile.BadZipFile``,
                ``git.GitCommandError``, asyncpg errors) never leak past the
                infrastructure layer that produced them.
Responsibility: Define the error types only — no handling logic. Handling (catch,
                log, translate to an HTTP response) lives at the API layer
                (api/error_handlers.py).
Depends on:    stdlib only.
Depended on by: every layer.
"""

from __future__ import annotations


class ForgeError(Exception):
    """Base class for every error Forge raises deliberately."""


class NotFoundError(ForgeError):
    """Raised when a requested entity does not exist."""


class ValidationError(ForgeError):
    """Raised when caller-supplied input fails validation."""


class SourceValidationError(ValidationError):
    """Raised when a repository source (archive, URL) fails a safety check before
    any extraction/clone is attempted."""


class UnsafeArchiveError(SourceValidationError):
    """Raised when a ZIP archive fails a specific safety check — path traversal,
    Zip Slip, symlink entry, oversized, too many entries, or a suspicious
    compression ratio."""


class WorkspaceError(ForgeError):
    """Raised when an isolated workspace cannot be created, or an operation would
    touch a path outside the configured workspace root."""


class SourceImportError(ForgeError):
    """Raised when an already-validated source still fails during materialization —
    network failure, clone timeout, corrupt archive discovered mid-extraction."""


class ParseFailure(ForgeError):
    """Raised by a single `LanguageParser` for a single file it cannot produce a
    usable structure from. Caught by `application/parsing/service.py` and recorded
    as a `ParseError` — never allowed to abort parsing the rest of the repository
    (see docs/architecture/03-parser-engine.md, "Error handling")."""


class UnsupportedRepositoryStateError(ForgeError):
    """Raised when an operation is requested against a `Repository` whose current
    `status` doesn't support it — e.g. parsing a repository that isn't `READY`."""


class GraphUnavailableError(ForgeError):
    """Raised when a Neo4j graph operation (Phase 5) can't reach or complete
    against Neo4j — connection refused, authentication failure, or the
    connection dropping mid-operation. Translated from `neo4j.exceptions`
    types by `infrastructure/graph/neo4j_graph_repository.py`; a raw driver
    exception never crosses out of infrastructure (see
    docs/architecture/05-knowledge-graph.md, "Failure handling")."""
