"""Ollama embedding provider (Phase 7).

Purpose:       Produce real embedding vectors for code chunks and queries by
                calling a local Ollama server's `/api/embed` endpoint — the
                genuine retrieval signal behind Forge's code Q&A.
Responsibility: One `EmbeddingProvider` implementation. Request shaping (batching,
                nomic's task prefixes), response validation, and L2-normalisation
                only. Transport and error translation are delegated to
                `OllamaClient`; ranking lives in `domain/rag/retrieval.py`.
Depends on:    infrastructure/rag/ollama_client.py, domain/rag/retrieval.py,
                domain/errors.py.
Depended on by: infrastructure/rag/dependencies.py.

Asymmetric prompting matters for retrieval quality: `nomic-embed-text` was
trained with task-instruction prefixes, and using them lifts retrieval markedly.
Documents (the stored chunks) are embedded with `search_document: `; a query is
embedded with `search_query: `. Getting this wrong doesn't error — it silently
degrades relevance — so it is applied here, once, at the boundary.

Every returned vector is L2-normalised before it leaves this provider, so stored
vectors are unit-length and cosine similarity is well-conditioned downstream.
"""

from __future__ import annotations

from collections.abc import Iterator

from forge.domain.errors import RagProviderError
from forge.domain.rag.retrieval import normalize_vector
from forge.infrastructure.rag.ollama_client import OllamaClient

_DOCUMENT_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "
_EMBED_PATH = "/api/embed"


def _batched[T](items: list[T], size: int) -> Iterator[list[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class OllamaEmbeddingProvider:
    """An `EmbeddingProvider` backed by a local Ollama model (default
    `nomic-embed-text`)."""

    def __init__(
        self,
        *,
        client: OllamaClient,
        model: str,
        dimensions: int,
        batch_size: int,
    ) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions
        self._batch_size = max(1, batch_size)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_documents(
        self, texts: tuple[str, ...]
    ) -> tuple[tuple[float, ...], ...]:
        """Embed `texts` as documents (with the `search_document:` prefix) in
        batches of `batch_size`, so N chunks cost ~ceil(N/batch) requests, never
        N. Returns one unit vector per input, in order."""
        if not texts:
            return ()
        vectors: list[tuple[float, ...]] = []
        prefixed = [f"{_DOCUMENT_PREFIX}{text}" for text in texts]
        for batch in _batched(prefixed, self._batch_size):
            vectors.extend(await self._embed_batch(batch))
        return tuple(vectors)

    async def embed_query(self, text: str) -> tuple[float, ...]:
        """Embed a single query (with the `search_query:` prefix) as one unit
        vector."""
        (vector,) = await self._embed_batch([f"{_QUERY_PREFIX}{text}"])
        return vector

    async def _embed_batch(self, inputs: list[str]) -> list[tuple[float, ...]]:
        """POST one batch to `/api/embed`, validate the shape, and return
        normalised vectors in input order."""
        data = await self._client.post_json(
            _EMBED_PATH, {"model": self._model, "input": inputs}
        )
        raw = data.get("embeddings")
        if not isinstance(raw, list) or len(raw) != len(inputs):
            raise RagProviderError(
                f"Ollama {_EMBED_PATH} returned {_describe(raw)} embeddings for "
                f"{len(inputs)} inputs (model {self._model!r})"
            )
        vectors: list[tuple[float, ...]] = []
        for entry in raw:
            if not isinstance(entry, list) or len(entry) != self._dimensions:
                raise RagProviderError(
                    f"Ollama {_EMBED_PATH} returned a vector of "
                    f"{_describe(entry)} dimensions, expected {self._dimensions} "
                    f"(model {self._model!r})"
                )
            vectors.append(normalize_vector([float(value) for value in entry]))
        return vectors


def _describe(value: object) -> str:
    """A length for a list, else a type name — for a precise error message."""
    return str(len(value)) if isinstance(value, list) else type(value).__name__
