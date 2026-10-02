"""RAG ask application service (Phase 7).

Purpose:       Answer a natural-language question about ONE repository, grounded
                strictly in that repository's own indexed code — the "query ->
                retrieve -> graph-expand -> generate -> cite" half of the RAG flow.
Responsibility: Orchestrate the pieces; own none of their internals. Embedding
                and generation are provider calls; similarity maths lives in
                domain/rag/retrieval.py; prompt shaping in domain/rag/prompting.py;
                persistence behind ChunkRepository; graph hops behind
                GraphRepository. This service enforces the four guarantees that
                make the answer trustworthy:

                  1. Isolation — ownership is verified and every read is scoped to
                     this repository_id; repository B's code can never surface.
                  2. Bounded work, no N+1 — one bounded candidate scan, one query
                     embedding, at most graph_seed_limit graph calls (a constant),
                     one generation call. Nothing scales with repository size
                     beyond the single capped candidate fetch.
                  3. Explicit insufficiency — if the repository isn't indexed, if
                     no chunk clears the similarity floor, or if the model itself
                     reports the context can't answer, we say so and DO NOT
                     fabricate. The floor case never even calls the model.
                  4. Un-fakeable citations — every SourceReference is built from a
                     chunk we actually retrieved (its real path/line/symbol/score),
                     never parsed from model output.

Depends on:    application/shared.py, domain/rag/{entities,ports,retrieval,
                prompting}.py, domain/graph/{ports,entities}.py, domain/repository/*.
Depended on by: api/rag.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from forge.application.shared import require_owned_repository
from forge.domain.graph.entities import GraphNodeKind
from forge.domain.graph.ports import GraphRepository
from forge.domain.rag.entities import (
    GraphContextItem,
    RagAnswer,
    RetrievedChunk,
    SourceReference,
)
from forge.domain.rag.ports import ChunkRepository, EmbeddingProvider, LlmProvider
from forge.domain.rag.prompting import (
    INSUFFICIENT_EVIDENCE_MARKER,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from forge.domain.rag.retrieval import cosine_similarity, rank_by_similarity
from forge.domain.repository.ports import RepositoryRepository

# Shown to the user when we decline to answer. Phrased so it is never mistaken for
# a real, grounded answer — the frontend also renders these in a distinct state.
_NOT_INDEXED_MESSAGE = (
    "This repository has not been indexed yet (or its index is empty), so there "
    "is no code to answer from. Index the repository and try again."
)
_NO_RELEVANT_CODE_MESSAGE = (
    "I couldn't find code in this repository relevant enough to answer that "
    "question confidently. Try rephrasing, or ask about code that exists here."
)
_MODEL_INSUFFICIENT_MESSAGE = (
    "Based on the retrieved code, there isn't enough information in this "
    "repository to answer that question."
)


@dataclass(frozen=True, slots=True)
class RagAskConfig:
    """Retrieval/graph/context bounds for one ask, all injected from settings so
    nothing here is a magic number and every bound is tunable centrally.

    Attributes:
        candidate_limit: Hard cap on embeddings scanned per query (the candidate
            set for similarity scoring). Bounds the one repository-wide read.
        top_k: How many top vector hits to keep as primary evidence.
        min_score: Cosine floor the best hit must clear, else we answer
            "insufficient" WITHOUT calling the model. Tuned empirically in E2E.
        graph_seed_limit: How many top hits seed graph expansion (constant number
            of graph calls — this is what keeps expansion off the N+1 path).
        graph_neighbor_limit: Max neighbors fetched per seed.
        graph_chunk_limit: Max neighbor code chunks pulled in as graph evidence.
        max_context_chars: Hard ceiling on assembled excerpt characters in the
            prompt — the whole repository is never dumped to the model.
    """

    candidate_limit: int
    top_k: int
    min_score: float
    graph_seed_limit: int
    graph_neighbor_limit: int
    graph_chunk_limit: int
    max_context_chars: int


class RagAskService:
    """Answers a question against one repository's index, grounded and cited."""

    def __init__(
        self,
        repositories: RepositoryRepository,
        chunks: ChunkRepository,
        graph: GraphRepository,
        embedder: EmbeddingProvider,
        llm: LlmProvider,
        llm_provider_label: str,
        config: RagAskConfig,
    ) -> None:
        self._repositories = repositories
        self._chunks = chunks
        self._graph = graph
        self._embedder = embedder
        self._llm = llm
        self._llm_provider_label = llm_provider_label
        self._config = config

    async def ask(self, project_id: UUID, repository_id: UUID, question: str) -> RagAnswer:
        """Answer `question` about `repository_id` (which must belong to
        `project_id`), grounded only in that repository's indexed code.

        Raises:
            NotFoundError: the repository doesn't exist or isn't in this project.
            RagProviderError: the embedding or generation provider failed.
        """
        # Ownership gate (defense in depth alongside the router dependency).
        await require_owned_repository(self._repositories, project_id, repository_id)

        query_embedding = await self._embedder.embed_query(question)
        candidates = await self._chunks.get_embeddings(
            repository_id, limit=self._config.candidate_limit
        )
        if not candidates:
            return self._insufficient(question, _NOT_INDEXED_MESSAGE)

        ranked = rank_by_similarity(query_embedding, candidates, top_k=self._config.top_k)
        if not ranked or ranked[0][1] < self._config.min_score:
            # Best match is below the floor — decline WITHOUT calling the model.
            return self._insufficient(question, _NO_RELEVANT_CODE_MESSAGE)

        vector_hits = await self._hydrate_vector_hits(repository_id, ranked)
        if not vector_hits:
            return self._insufficient(question, _NO_RELEVANT_CODE_MESSAGE)

        embedding_by_id = {c.chunk_id: c.embedding for c in candidates}
        existing_ids = {hit.chunk.id for hit in vector_hits}
        graph_context, graph_hits = await self._expand_graph(
            repository_id, vector_hits, query_embedding, embedding_by_id, existing_ids
        )

        retrieved = self._merge(vector_hits, graph_hits)
        prompt = build_user_prompt(
            question=question,
            retrieved=retrieved,
            graph_context=graph_context,
            max_context_chars=self._config.max_context_chars,
        )
        answer_text = await self._llm.generate(system=SYSTEM_PROMPT, prompt=prompt)

        if self._is_insufficient_reply(answer_text):
            # The model, looking at the real excerpts, says it can't answer.
            return self._insufficient(question, _MODEL_INSUFFICIENT_MESSAGE)

        return RagAnswer(
            question=question,
            answer=answer_text,
            has_sufficient_evidence=True,
            sources=tuple(self._to_source(hit) for hit in retrieved),
            graph_context=graph_context,
            llm_provider=self._llm_provider_label,
            llm_model=self._llm.model_name,
            embedding_model=self._embedder.model_name,
        )

    async def _hydrate_vector_hits(
        self, repository_id: UUID, ranked: list[tuple[UUID, float]]
    ) -> list[RetrievedChunk]:
        """Fetch full content for the ranked ids that clear the floor and wrap
        each as a `vector` retrieved chunk, preserving score order."""
        floor = self._config.min_score
        qualifying = [(cid, score) for cid, score in ranked if score >= floor]
        ids = tuple(cid for cid, _ in qualifying)
        by_id = await self._chunks.get_chunks_by_ids(repository_id, ids)
        return [
            RetrievedChunk(chunk=by_id[cid], score=score, via="vector")
            for cid, score in qualifying
            if cid in by_id
        ]

    async def _expand_graph(
        self,
        repository_id: UUID,
        vector_hits: list[RetrievedChunk],
        query_embedding: tuple[float, ...],
        embedding_by_id: dict[UUID, tuple[float, ...]],
        existing_ids: set[UUID],
    ) -> tuple[tuple[GraphContextItem, ...], list[RetrievedChunk]]:
        """Bounded, graph-aware expansion around the top vector hits.

        For up to `graph_seed_limit` top hits that map to a symbol, fetch their
        graph neighbors (a constant number of graph calls), record the related
        symbols as structural context, and pull the neighbors' own code as
        additional `graph` evidence — scored by real cosine against the query
        where their embedding is on hand, so a graph-surfaced chunk is ranked on
        its true relevance, not a fabricated one. Never crosses repositories:
        `get_neighbors`/`get_chunks_by_symbol_ids` are both repository-scoped.
        """
        seeds = [hit for hit in vector_hits if hit.chunk.symbol_id is not None]
        seeds = seeds[: self._config.graph_seed_limit]

        context_items: list[GraphContextItem] = []
        seen_context: set[tuple[str, str, str]] = set()
        neighbor_symbol_ids: list[UUID] = []
        seen_symbol_ids: set[UUID] = set()

        for seed in seeds:
            symbol_id = seed.chunk.symbol_id
            if symbol_id is None:  # narrowed for type-checkers; filtered above
                continue
            neighbors = await self._graph.get_neighbors(
                repository_id,
                symbol_id,
                direction="both",
                limit=self._config.graph_neighbor_limit,
            )
            if not neighbors:
                continue
            for neighbor in neighbors:
                properties = neighbor.node.properties
                qualified_name = properties.get("qualified_name")
                relationship = neighbor.relationship_kind.value
                key = (str(qualified_name), relationship, neighbor.direction)
                if qualified_name and key not in seen_context:
                    seen_context.add(key)
                    context_items.append(
                        GraphContextItem(
                            qualified_name=str(qualified_name),
                            kind=str(properties.get("kind") or neighbor.node.kind.value),
                            relationship=relationship,
                            direction=neighbor.direction,
                        )
                    )
                if (
                    neighbor.node.kind == GraphNodeKind.SYMBOL
                    and neighbor.node.id not in seen_symbol_ids
                    and neighbor.node.id not in existing_ids
                ):
                    seen_symbol_ids.add(neighbor.node.id)
                    neighbor_symbol_ids.append(neighbor.node.id)

        graph_hits = await self._graph_chunks(
            repository_id, neighbor_symbol_ids, query_embedding, embedding_by_id, existing_ids
        )
        return tuple(context_items), graph_hits

    async def _graph_chunks(
        self,
        repository_id: UUID,
        neighbor_symbol_ids: list[UUID],
        query_embedding: tuple[float, ...],
        embedding_by_id: dict[UUID, tuple[float, ...]],
        existing_ids: set[UUID],
    ) -> list[RetrievedChunk]:
        """Pull the code of graph-neighbor symbols (bounded) as `graph` evidence,
        skipping any chunk already selected by vector search."""
        if not neighbor_symbol_ids:
            return []
        chunks = await self._chunks.get_chunks_by_symbol_ids(
            repository_id,
            tuple(neighbor_symbol_ids),
            limit=self._config.graph_chunk_limit,
        )
        hits: list[RetrievedChunk] = []
        for chunk in chunks:
            if chunk.id in existing_ids:
                continue
            embedding = embedding_by_id.get(chunk.id)
            score = cosine_similarity(query_embedding, embedding) if embedding else 0.0
            hits.append(RetrievedChunk(chunk=chunk, score=score, via="graph"))
        return hits

    @staticmethod
    def _merge(
        vector_hits: list[RetrievedChunk], graph_hits: list[RetrievedChunk]
    ) -> tuple[RetrievedChunk, ...]:
        """Combine vector and graph evidence into one deterministically ordered
        sequence (highest score first, chunk id breaking ties)."""
        combined = [*vector_hits, *graph_hits]
        combined.sort(key=lambda hit: (-hit.score, hit.chunk.id.bytes))
        return tuple(combined)

    @staticmethod
    def _to_source(hit: RetrievedChunk) -> SourceReference:
        """Build a citation from a retrieved chunk's REAL metadata — never from
        model output. This is the structural anti-hallucination guarantee."""
        chunk = hit.chunk
        return SourceReference(
            path=chunk.path,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            score=hit.score,
            via=hit.via,
            symbol_qualified_name=chunk.symbol_qualified_name,
            symbol_kind=chunk.symbol_kind,
        )

    @staticmethod
    def _is_insufficient_reply(answer_text: str) -> bool:
        """True if the model's reply is (essentially) just the insufficiency
        marker — tolerating trailing punctuation/quoting the model may add."""
        core = answer_text.strip().strip("`\"'.*").strip()
        return core.upper() == INSUFFICIENT_EVIDENCE_MARKER

    def _insufficient(self, question: str, message: str) -> RagAnswer:
        """An explicit no-answer result: no sources, no graph context, evidence
        flag false. Carries provider/model provenance so the caller still knows
        what ran."""
        return RagAnswer(
            question=question,
            answer=message,
            has_sufficient_evidence=False,
            sources=(),
            graph_context=(),
            llm_provider=self._llm_provider_label,
            llm_model=self._llm.model_name,
            embedding_model=self._embedder.model_name,
        )
