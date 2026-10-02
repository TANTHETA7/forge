"""RAG domain entities (Phase 7).

Purpose:       The immutable value objects the RAG pipeline produces and consumes
                — code chunks, their embeddings, retrieved results, grounded
                answers with citations, and index bookkeeping.
Responsibility: Data shapes only. No IO, no inference, no persistence — every
                field is a plain fact (a path, a line range, a cosine score, a
                model name), never anything inferred or fabricated.

Grounding invariant: a `SourceReference` is always built from a `CodeChunk`
Forge actually retrieved from its own store — its `path`/`start_line`/`end_line`/
`symbol_qualified_name` are the chunk's real metadata, never parsed out of model
output. This is the structural guarantee that citations cannot be hallucinated:
the model never gets to choose them.

Depends on:    stdlib only.
Depended on by: domain/rag/ports.py, domain/rag/chunking.py, application/rag/*,
                infrastructure/rag/*, api/rag.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CodeChunk:
    """One retrievable unit of source code, carved at a symbol/region boundary.

    Attributes:
        id: Deterministic (`uuid5` of repository_id|path|start_line|end_line) so
            re-indexing unchanged source yields stable ids.
        repository_id: Owning repository — the isolation key on every query.
        file_id: The `ParsedFile` this chunk came from.
        path: Workspace-relative, forward-slash path (from `ParsedFile.path`).
        language: `Language` value string, e.g. `"python"`.
        start_line: 1-based inclusive first line of the chunk in `path`.
        end_line: 1-based inclusive last line.
        content: The verbatim source text of lines `start_line..end_line`.
        content_hash: sha256 hex of `content` — used to reuse an embedding for
            identical content across re-indexes instead of recomputing it.
        symbol_id: The enclosing `Symbol`'s id, or `None` for a file-level region
            (module preamble/imports, trailing module code). Also the direct key
            into the Neo4j graph (a `GraphNode`'s id is the same PostgreSQL id).
        symbol_qualified_name: The enclosing symbol's dotted name, or `None`.
        symbol_kind: `"function"`/`"class"`/`"method"`, or `None` for a region.
        token_estimate: Rough token count (chars // 4) — for context budgeting.
    """

    id: UUID
    repository_id: UUID
    file_id: UUID
    path: str
    language: str
    start_line: int
    end_line: int
    content: str
    content_hash: str
    symbol_id: UUID | None
    symbol_qualified_name: str | None
    symbol_kind: str | None
    token_estimate: int


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """A `CodeChunk` paired with its (unit-normalised) embedding vector and the
    model that produced it — the unit persisted by `ChunkRepository`."""

    chunk: CodeChunk
    embedding: tuple[float, ...]
    embedding_model: str


@dataclass(frozen=True, slots=True)
class ChunkEmbedding:
    """A chunk id plus its vector, without the (potentially large) content —
    what the scoring phase loads so cosine similarity runs over vectors alone,
    then only the winning ids have their full content fetched."""

    chunk_id: UUID
    embedding: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A chunk selected for the answer context, with why it was selected.

    Attributes:
        chunk: The retrieved `CodeChunk`.
        score: Cosine similarity to the query in [-1, 1]. Higher is closer.
        via: `"vector"` (selected by embedding similarity) or `"graph"` (pulled
            in by bounded Neo4j expansion from a top vector hit).
    """

    chunk: CodeChunk
    score: float
    via: str


@dataclass(frozen=True, slots=True)
class GraphContextItem:
    """A related symbol surfaced by bounded graph expansion, shown to the model
    and the user as structural context — a plain graph fact, never scored."""

    qualified_name: str
    kind: str
    relationship: str
    direction: str


@dataclass(frozen=True, slots=True)
class SourceReference:
    """A citation attached to an answer — always the real metadata of a chunk
    Forge retrieved, never text produced by the model (see module docstring)."""

    path: str
    start_line: int
    end_line: int
    score: float
    via: str
    symbol_qualified_name: str | None
    symbol_kind: str | None


@dataclass(frozen=True, slots=True)
class RagAnswer:
    """The result of answering a question against one repository.

    Attributes:
        question: The question asked, verbatim.
        answer: The generated answer text, grounded in `sources`.
        has_sufficient_evidence: `False` when the repository isn't indexed, when
            no retrieved chunk clears the similarity floor, or when the model
            itself reports the context doesn't contain the answer. When `False`,
            `answer` says so explicitly rather than guessing.
        sources: The citations backing the answer (real chunk metadata).
        graph_context: Related symbols surfaced by bounded graph expansion.
        llm_provider: Which generation provider ran (`"ollama"`/`"extractive"`).
        llm_model: The generation model name.
        embedding_model: The embedding model used for retrieval.
    """

    question: str
    answer: str
    has_sufficient_evidence: bool
    sources: tuple[SourceReference, ...]
    graph_context: tuple[GraphContextItem, ...]
    llm_provider: str
    llm_model: str
    embedding_model: str


@dataclass(frozen=True, slots=True)
class IndexingResult:
    """Bookkeeping returned by an index/re-index run.

    Attributes:
        repository_id: The repository indexed.
        chunk_count: Total chunks now stored for the repository.
        embedded_count: Chunks whose vectors were newly computed this run.
        reused_count: Chunks whose vectors were reused from identical content
            embedded in a prior run (see `CodeChunk.content_hash`).
        files_indexed: Files that produced at least one chunk.
        skipped_files: Files that could not be read from the workspace.
        embedding_model: The embedding model used.
        indexed_at: When this run completed (UTC).
    """

    repository_id: UUID
    chunk_count: int
    embedded_count: int
    reused_count: int
    files_indexed: int
    skipped_files: int
    embedding_model: str
    indexed_at: datetime


@dataclass(frozen=True, slots=True)
class IndexStatus:
    """Whether a repository is indexed, and with what — for the status endpoint."""

    repository_id: UUID
    indexed: bool
    chunk_count: int
    embedding_model: str | None
    last_indexed_at: datetime | None
