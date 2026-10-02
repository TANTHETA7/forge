"""SQLAlchemy implementation of `domain/rag/ports.py::ChunkRepository` (Phase 7).

Purpose:       Persist and retrieve a repository's code chunks and their
                embeddings in Postgres, with repository isolation and bounded
                reads as structural properties of every query.
Responsibility: Translate between `CodeChunk`/`EmbeddedChunk`/`ChunkEmbedding`
                and `CodeChunkRow` only. No chunking, no embedding, no scoring —
                cosine ranking happens in the pure `domain/rag/retrieval.py` over
                the candidates this repository hands back.
Depends on:    sqlalchemy, domain/rag/entities.py, infrastructure/persistence/models.py.
Depended on by: infrastructure/rag/dependencies.py.

Two isolation guarantees hold on every method here:
  * Reads are filtered by `WHERE repository_id = :id` — repository A's query can
    never surface repository B's chunks, even `get_chunks_by_ids` (which filters
    by repository *and* id, so a leaked id from another repository returns
    nothing).
  * Reads are bounded — `get_embeddings`/`get_chunks_by_symbol_ids` take an
    explicit `limit`; there is no "load every chunk" path.

No pgvector: embeddings are stored as JSON float arrays (already L2-normalised by
the provider) and scored in Python. `get_embeddings` returns vectors *without*
content so the similarity scan stays cheap; only the winning ids are hydrated to
full `CodeChunk`s via `get_chunks_by_ids`.

Bulk insert (`Session.execute(insert(model), rows)` in bounded chunks) is used
for the same measured reason as `parsed_file_repository_impl.py`: a large
repository can produce tens of thousands of chunks, and per-row `Session.add()`
does not reliably batch into multi-row INSERTs here.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.rag.entities import (
    ChunkEmbedding,
    CodeChunk,
    EmbeddedChunk,
    IndexStatus,
)
from forge.infrastructure.persistence.models import CodeChunkRow

# Mirrors parsed_file_repository_impl.py's batching. CodeChunkRow has 16 columns;
# 500 rows is at most 8,000 bound parameters, comfortably under asyncpg's
# ~32,767-parameter ceiling per statement.
_INSERT_BATCH_SIZE = 500


def _chunked[T](items: list[T], size: int) -> Iterator[list[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class SqlAlchemyChunkRepository:
    """A `ChunkRepository` backed by Postgres via SQLAlchemy's async engine."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_chunks(
        self, repository_id: UUID, chunks: tuple[EmbeddedChunk, ...]
    ) -> None:
        """Delete every stored chunk for `repository_id` and insert `chunks` in
        one transaction. Full replacement, so a re-index never leaves chunks for
        source that no longer exists; an empty `chunks` clears the index."""
        indexed_at = datetime.now(UTC)
        await self._session.execute(
            delete(CodeChunkRow).where(CodeChunkRow.repository_id == repository_id)
        )
        rows = [_embedded_to_params(embedded, indexed_at=indexed_at) for embedded in chunks]
        for batch in _chunked(rows, _INSERT_BATCH_SIZE):
            await self._session.execute(insert(CodeChunkRow), batch)
        await self._session.commit()

    async def get_existing_embeddings_by_hash(
        self, repository_id: UUID, embedding_model: str
    ) -> dict[str, tuple[float, ...]]:
        """Return `{content_hash: embedding}` for this repository's chunks under
        `embedding_model`, so a re-index can reuse a vector for byte-identical
        content instead of re-embedding it. Scoped to the repository and model."""
        result = await self._session.execute(
            select(CodeChunkRow.content_hash, CodeChunkRow.embedding).where(
                CodeChunkRow.repository_id == repository_id,
                CodeChunkRow.embedding_model == embedding_model,
            )
        )
        reuse: dict[str, tuple[float, ...]] = {}
        for content_hash, embedding in result.all():
            # First occurrence wins; duplicate hashes share one vector anyway.
            if content_hash not in reuse:
                reuse[content_hash] = tuple(float(value) for value in embedding)
        return reuse

    async def get_embeddings(
        self, repository_id: UUID, *, limit: int
    ) -> tuple[ChunkEmbedding, ...]:
        """Return up to `limit` `(chunk_id, embedding)` pairs for this repository,
        without content — the candidate set the scorer ranks. Ordered by id so
        the (bounded) candidate window is deterministic across runs."""
        result = await self._session.execute(
            select(CodeChunkRow.id, CodeChunkRow.embedding)
            .where(CodeChunkRow.repository_id == repository_id)
            .order_by(CodeChunkRow.id)
            .limit(limit)
        )
        return tuple(
            ChunkEmbedding(
                chunk_id=chunk_id,
                embedding=tuple(float(value) for value in embedding),
            )
            for chunk_id, embedding in result.all()
        )

    async def get_chunks_by_ids(
        self, repository_id: UUID, chunk_ids: tuple[UUID, ...]
    ) -> dict[UUID, CodeChunk]:
        """Hydrate full `CodeChunk`s for `chunk_ids`, as `{id: chunk}`. Filtered
        by `repository_id` as defense in depth — an id from another repository is
        simply absent from the result."""
        if not chunk_ids:
            return {}
        result = await self._session.execute(
            select(CodeChunkRow).where(
                CodeChunkRow.repository_id == repository_id,
                CodeChunkRow.id.in_(chunk_ids),
            )
        )
        return {row.id: _row_to_chunk(row) for row in result.scalars().all()}

    async def get_chunks_by_symbol_ids(
        self, repository_id: UUID, symbol_ids: tuple[UUID, ...], *, limit: int
    ) -> tuple[CodeChunk, ...]:
        """Return up to `limit` chunks in this repository whose `symbol_id` is in
        `symbol_ids` — the code for symbols surfaced by bounded graph expansion.
        Scoped to `repository_id`; bounded by `limit`."""
        if not symbol_ids:
            return ()
        result = await self._session.execute(
            select(CodeChunkRow)
            .where(
                CodeChunkRow.repository_id == repository_id,
                CodeChunkRow.symbol_id.in_(symbol_ids),
            )
            .order_by(CodeChunkRow.symbol_id, CodeChunkRow.start_line, CodeChunkRow.id)
            .limit(limit)
        )
        return tuple(_row_to_chunk(row) for row in result.scalars().all())

    async def get_status(self, repository_id: UUID) -> IndexStatus:
        """Return whether this repository is indexed, its chunk count, the
        embedding model used, and when it was last indexed — one aggregate query."""
        result = await self._session.execute(
            select(
                func.count(CodeChunkRow.id),
                func.max(CodeChunkRow.indexed_at),
                func.max(CodeChunkRow.embedding_model),
            ).where(CodeChunkRow.repository_id == repository_id)
        )
        chunk_count, last_indexed_at, embedding_model = result.one()
        return IndexStatus(
            repository_id=repository_id,
            indexed=chunk_count > 0,
            chunk_count=chunk_count,
            embedding_model=embedding_model,
            last_indexed_at=last_indexed_at,
        )


def _embedded_to_params(embedded: EmbeddedChunk, *, indexed_at: datetime) -> dict[str, Any]:
    chunk = embedded.chunk
    return {
        "id": chunk.id,
        "repository_id": chunk.repository_id,
        "file_id": chunk.file_id,
        "path": chunk.path,
        "language": chunk.language,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "content": chunk.content,
        "content_hash": chunk.content_hash,
        "symbol_id": chunk.symbol_id,
        "symbol_qualified_name": chunk.symbol_qualified_name,
        "symbol_kind": chunk.symbol_kind,
        "token_estimate": chunk.token_estimate,
        "embedding": list(embedded.embedding),
        "embedding_model": embedded.embedding_model,
        "indexed_at": indexed_at,
    }


def _row_to_chunk(row: CodeChunkRow) -> CodeChunk:
    return CodeChunk(
        id=row.id,
        repository_id=row.repository_id,
        file_id=row.file_id,
        path=row.path,
        language=row.language,
        start_line=row.start_line,
        end_line=row.end_line,
        content=row.content,
        content_hash=row.content_hash,
        symbol_id=row.symbol_id,
        symbol_qualified_name=row.symbol_qualified_name,
        symbol_kind=row.symbol_kind,
        token_estimate=row.token_estimate,
    )
