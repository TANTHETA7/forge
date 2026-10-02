"""Package initializer for RAG infrastructure adapters (Phase 7).

Concrete implementations of the `domain/rag/ports.py` seams: Postgres chunk
persistence, filesystem source reading, and the Ollama / offline embedding and
LLM providers. Nothing here is imported by the domain or application layers
directly — they receive these via `infrastructure/rag/dependencies.py`.
"""
