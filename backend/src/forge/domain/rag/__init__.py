"""Retrieval-Augmented code intelligence domain (Phase 7).

Defines what a code chunk, a retrieved result, a grounded answer, and the ports
for embedding/generation/persistence are — independent of Ollama, httpx,
SQLAlchemy, or FastAPI. See docs/architecture (Phase 7) for the flow:
repository source -> symbol-aware chunking -> embeddings -> repository-scoped
vector retrieval -> bounded Neo4j graph context -> grounded generation ->
answer with real file/symbol/line citations.
"""
