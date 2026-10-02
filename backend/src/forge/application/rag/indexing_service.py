"""RAG indexing application service (Phase 7).

Purpose:       Turn a parsed, READY repository into a stored, embedded, per-
                repository vector index — the "repository source -> chunks ->
                embeddings -> storage" half of the RAG flow.
Responsibility: Orchestrate the domain chunker, the source reader, the embedding
                provider, and the chunk repository. No chunking maths (that's
                domain/rag/chunking.py), no HTTP, no SQL — just sequencing, with
                two efficiency guarantees:
                  * embeddings are computed in provider-batched calls, never one
                    request per chunk;
                  * a chunk whose content is byte-identical to one already
                    embedded (this run or a prior run) is embedded once, not
                    repeatedly — unchanged code is never re-sent to the model.
Depends on:    application/shared.py, domain/rag/{chunking,entities,ports}.py,
                domain/parsing/ports.py, domain/repository/*, domain/errors.py.
Depended on by: api/rag.py.

Repository isolation: the owning project is verified up front via
`require_owned_repository`, and every chunk/embedding read and write is scoped to
this `repository_id` by the `ChunkRepository` contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from forge.application.shared import require_owned_repository
from forge.domain.errors import UnsupportedRepositoryStateError
from forge.domain.parsing.ports import ParsedFileRepository
from forge.domain.rag.chunking import ChunkingConfig, build_chunks
from forge.domain.rag.entities import CodeChunk, EmbeddedChunk, IndexingResult, IndexStatus
from forge.domain.rag.ports import ChunkRepository, EmbeddingProvider, SourceReader
from forge.domain.repository.entities import RepositoryStatus
from forge.domain.repository.ports import RepositoryRepository


class RagIndexingService:
    """Builds and stores a repository's chunk+embedding index."""

    def __init__(
        self,
        repositories: RepositoryRepository,
        parsed_files: ParsedFileRepository,
        chunks: ChunkRepository,
        source_reader: SourceReader,
        embedder: EmbeddingProvider,
        chunking_config: ChunkingConfig,
    ) -> None:
        self._repositories = repositories
        self._parsed_files = parsed_files
        self._chunks = chunks
        self._source_reader = source_reader
        self._embedder = embedder
        self._chunking_config = chunking_config

    async def index_repository(self, project_id: UUID, repository_id: UUID) -> IndexingResult:
        """(Re)build the index for `repository_id`, which must belong to
        `project_id`, be `READY`, and have been parsed.

        Raises:
            NotFoundError: the repository doesn't exist or isn't in this project.
            UnsupportedRepositoryStateError: the repository isn't `READY`, or has
                no parsed files to index (parse it first).
            RagProviderError: the embedding provider was unreachable/failed.
        """
        repository = await require_owned_repository(
            self._repositories, project_id, repository_id
        )
        if repository.status != RepositoryStatus.READY:
            raise UnsupportedRepositoryStateError(
                f"Repository {repository_id} is {repository.status.value}, not ready to index"
            )

        files = await self._parsed_files.get_files(repository_id)
        if not files:
            raise UnsupportedRepositoryStateError(
                f"Repository {repository_id} has no parsed files; parse it before indexing"
            )

        all_chunks: list[CodeChunk] = []
        files_indexed = 0
        skipped_files = 0
        for parsed_file in files:
            source_text = self._source_reader.read_text(
                repository.workspace_path, parsed_file.path
            )
            if source_text is None:
                # Unreadable/missing/oversized file — skip it, don't abort the run.
                skipped_files += 1
                continue
            file_chunks = build_chunks(
                parsed_file=parsed_file,
                source_text=source_text,
                config=self._chunking_config,
            )
            if file_chunks:
                files_indexed += 1
                all_chunks.extend(file_chunks)

        embedded, embedded_count, reused_count = await self._embed_chunks(
            repository_id, all_chunks
        )
        await self._chunks.replace_chunks(repository_id, tuple(embedded))

        return IndexingResult(
            repository_id=repository_id,
            chunk_count=len(embedded),
            embedded_count=embedded_count,
            reused_count=reused_count,
            files_indexed=files_indexed,
            skipped_files=skipped_files,
            embedding_model=self._embedder.model_name,
            indexed_at=datetime.now(UTC),
        )

    async def get_index_status(self, project_id: UUID, repository_id: UUID) -> IndexStatus:
        """Return the index status for `repository_id`, which must belong to
        `project_id`.

        Raises:
            NotFoundError: the repository doesn't exist or isn't in this project.
        """
        await require_owned_repository(self._repositories, project_id, repository_id)
        return await self._chunks.get_status(repository_id)


    async def _embed_chunks(
        self, repository_id: UUID, chunks: list[CodeChunk]
    ) -> tuple[list[EmbeddedChunk], int, int]:
        """Attach an embedding to every chunk, reusing a stored vector for any
        content already embedded under this model and computing the rest in one
        batched pass. Returns (embedded chunks, newly-embedded count, reused
        count)."""
        model = self._embedder.model_name
        reusable = await self._chunks.get_existing_embeddings_by_hash(repository_id, model)

        # Unique unembedded contents, keyed by hash, so identical chunks (a repeated
        # boilerplate block, the same file re-indexed) cost one embed call, not many.
        pending: dict[str, str] = {}
        for chunk in chunks:
            if chunk.content_hash not in reusable and chunk.content_hash not in pending:
                pending[chunk.content_hash] = chunk.content

        fresh: dict[str, tuple[float, ...]] = {}
        if pending:
            hashes = tuple(pending.keys())
            vectors = await self._embedder.embed_documents(tuple(pending.values()))
            fresh = dict(zip(hashes, vectors, strict=True))

        embedded: list[EmbeddedChunk] = []
        embedded_count = 0
        reused_count = 0
        for chunk in chunks:
            reused_vector = reusable.get(chunk.content_hash)
            if reused_vector is not None:
                embedding = reused_vector
                reused_count += 1
            else:
                embedding = fresh[chunk.content_hash]
                embedded_count += 1
            embedded.append(
                EmbeddedChunk(chunk=chunk, embedding=embedding, embedding_model=model)
            )
        return embedded, embedded_count, reused_count
