"""RAG domain ports (Phase 7).

Purpose:       The abstract seams between the RAG application services and the
                outside world — persistence of chunks/embeddings, embedding
                inference, text generation, and reading source off disk.
Responsibility: Declare *what* each collaborator must do, never *how*. Every
                method here is implemented twice in infrastructure: once for
                real use (Postgres, Ollama, filesystem) and once as a
                deterministic offline double for unit tests.

Design notes:
  * `ChunkRepository` is written to make repository isolation and bounded reads
    structural, not optional: every read is scoped to a single `repository_id`
    and capped by an explicit `limit`. There is no "get all chunks" method.
  * Retrieval is split deliberately — `get_embeddings` returns vectors *without*
    content so scoring is cheap, then `get_chunks_by_ids` hydrates only the
    winners. This is what keeps a repository-wide similarity scan from loading
    every chunk's full source text into memory.

Depends on:    domain/rag/entities.py, stdlib typing.
Depended on by: application/rag/*, infrastructure/rag/*.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from forge.domain.rag.entities import (
    ChunkEmbedding,
    CodeChunk,
    EmbeddedChunk,
    IndexStatus,
)


@runtime_checkable
class ChunkRepository(Protocol):
    """Persistence for code chunks and their embeddings, scoped per repository.

    Every method takes a `repository_id` and every read is bounded — there is no
    unbounded "fetch everything" call, and no method that crosses repositories.
    """

    async def replace_chunks(
        self, repository_id: UUID, chunks: tuple[EmbeddedChunk, ...]
    ) -> None:
        """Atomically replace *all* stored chunks for `repository_id` with
        `chunks` (delete-then-insert in one transaction).

        Full replacement — not merge — so a re-index can never leave chunks for
        source that no longer exists. Passing an empty tuple clears the
        repository's index.
        """
        ...

    async def get_existing_embeddings_by_hash(
        self, repository_id: UUID, embedding_model: str
    ) -> dict[str, tuple[float, ...]]:
        """Return `{content_hash: embedding}` for chunks already stored for this
        repository under `embedding_model`.

        Lets a re-index reuse the vector for any chunk whose content is
        byte-identical to a previously embedded chunk, so unchanged code is never
        re-sent to the embedding model. Scoped to the repository and the model
        (a vector from a different model must never be reused).
        """
        ...

    async def get_embeddings(
        self, repository_id: UUID, *, limit: int
    ) -> tuple[ChunkEmbedding, ...]:
        """Return up to `limit` `(chunk_id, embedding)` pairs for this repository,
        *without* chunk content — the cheap candidate set the scorer ranks.

        The `limit` is the hard candidate cap (`rag_retrieval_candidate_limit`);
        repository isolation is a `WHERE repository_id = :id` the implementation
        must always apply.
        """
        ...

    async def get_chunks_by_ids(
        self, repository_id: UUID, chunk_ids: tuple[UUID, ...]
    ) -> dict[UUID, CodeChunk]:
        """Hydrate the full `CodeChunk` (with content) for each id in `chunk_ids`,
        returned as `{id: chunk}`.

        Also filtered by `repository_id` as defense in depth: even if a caller
        somehow supplied an id from another repository, it must not be returned.
        Ids with no match in this repository are simply absent from the result.
        """
        ...

    async def get_chunks_by_symbol_ids(
        self, repository_id: UUID, symbol_ids: tuple[UUID, ...], *, limit: int
    ) -> tuple[CodeChunk, ...]:
        """Return up to `limit` chunks in this repository whose `symbol_id` is in
        `symbol_ids` — used to pull the code for symbols surfaced by bounded graph
        expansion. Scoped to `repository_id`; bounded by `limit`.
        """
        ...

    async def get_status(self, repository_id: UUID) -> IndexStatus:
        """Return whether this repository is indexed, its chunk count, the
        embedding model used, and when it was last indexed."""
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turns text into unit-normalised embedding vectors.

    Implementations must return vectors of consistent dimensionality and are
    expected to L2-normalise, so cosine similarity reduces to a dot product in
    the retrieval layer. Real providers raise `RagProviderError` on any transport
    or model failure — never a partial or fabricated vector.
    """

    @property
    def model_name(self) -> str:
        """The model identifier stored alongside embeddings (so a re-index under a
        different model doesn't silently mix vector spaces)."""
        ...

    @property
    def dimensions(self) -> int:
        """The vector length this provider produces."""
        ...

    async def embed_documents(
        self, texts: tuple[str, ...]
    ) -> tuple[tuple[float, ...], ...]:
        """Embed a batch of *documents* (code chunks) for storage, returning one
        vector per input in the same order. Providers should apply the model's
        document-side prompt convention (e.g. nomic's `search_document:` prefix).
        """
        ...

    async def embed_query(self, text: str) -> tuple[float, ...]:
        """Embed a single *query* for retrieval, applying the model's query-side
        prompt convention (e.g. nomic's `search_query:` prefix). Kept separate
        from `embed_documents` because asymmetric models score far better when
        query and document are prefixed differently."""
        ...


@runtime_checkable
class LlmProvider(Protocol):
    """Generates an answer from a system instruction and a grounded prompt.

    The provider receives already-assembled, already-bounded context and returns
    text. It never selects sources and never fetches anything itself. Real
    providers raise `RagProviderError` on transport/model failure.
    """

    @property
    def model_name(self) -> str:
        """The generation model identifier, surfaced in the answer for provenance."""
        ...

    async def generate(self, *, system: str, prompt: str) -> str:
        """Return the model's completion for `prompt` under the `system`
        instruction. Deterministic-leaning settings (low temperature) are the
        provider's responsibility."""
        ...


@runtime_checkable
class SourceReader(Protocol):
    """Reads a file's text out of a repository's isolated workspace.

    The one seam that touches the filesystem during indexing. Implementations
    must confine reads to within the given workspace root (no traversal outside
    it) and return `None` for a file that cannot be read, so one unreadable file
    never aborts a whole index run.
    """

    def read_text(self, workspace_path: str, relative_path: str) -> str | None:
        """Return the UTF-8 text of `relative_path` under `workspace_path`, or
        `None` if it is missing, too large, outside the workspace, or not
        decodable as text."""
        ...
