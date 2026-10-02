"""Symbol-aware code chunking (Phase 7).

Purpose:       Carve one parsed source file into `CodeChunk`s aligned to symbol
                boundaries (functions, classes, methods) and module regions, so
                each retrievable unit is a coherent piece of code with real
                file/symbol/line metadata attached.
Responsibility: Pure, deterministic transformation
                `(ParsedFile, source_text, ChunkingConfig) -> list[CodeChunk]`.
                No IO, no embeddings, no persistence. Given identical inputs it
                always produces identical chunks (same ids, same order).

Why symbol-aware rather than fixed-size windows:
    A retrieval hit should point at "the `parse_repository` method in
    `service.py`, lines 40-95", not "bytes 3000-4000 of some file". Chunking on
    the structure the parser already extracted means every chunk carries a real
    `symbol_id` (which is *also* its Neo4j graph key — see
    application/rag/ask_service.py) and every citation is a genuine
    definition span, not an arbitrary slice.

The region model (non-overlapping, gap-filling, so coverage is complete without
duplication):
  * Symbols form a tree via `parent_symbol_id` (methods under their class).
  * A *leaf* symbol (function, method, class without methods) becomes one region
    [start, end] owned by that symbol.
  * A *class with methods* becomes: a header region [class.start,
    first_method.start-1] owned by the class (its `class ...:` line, docstring,
    class attributes), then each method as its own region, then any code between
    or after methods attributed back to the class.
  * Module-level code — the preamble before the first top-level symbol (imports,
    module docstring) and any code between/after top-level symbols (e.g. an
    `if __name__ == "__main__":` block) — becomes regions owned by no symbol.
  * A file with no symbols at all becomes one whole-file region.
Each region is then split into windows of at most `max_lines` lines and
`max_chars` characters, so a single thousand-line function can never become one
giant chunk that dominates an embedding or a prompt. Windows never overlap.

Depends on:    domain/rag/entities.py, domain/parsing/entities.py, stdlib.
Depended on by: application/rag/indexing_service.py.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID, uuid5

from forge.domain.parsing.entities import ParsedFile, Symbol
from forge.domain.rag.entities import CodeChunk

# Fixed namespace for deterministic chunk ids. A chunk's id is uuid5 of
# "repository_id|path|start_line|end_line" under this namespace, so re-indexing
# unchanged source produces the same id (stable references) while two
# repositories with an identical file still get distinct chunk ids (the
# repository_id is folded in).
_CHUNK_NAMESPACE = UUID("a7d3f8e2-1c4b-4e9a-9f6d-2b8c5e1a0d47")


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    """Bounds for windowing a region into chunks. Built from `Settings` by the
    indexing service so this module stays free of configuration plumbing.

    Attributes:
        max_lines: Hard cap on a single chunk's line count.
        max_chars: Hard cap on a single chunk's character count. A region over
            either cap is split into multiple windows; a single line longer than
            `max_chars` (e.g. minified code) is truncated to avoid an unbounded
            chunk.
        min_chars: A chunk whose stripped content is shorter than this is dropped
            — too little signal to embed usefully (blank runs, a lone brace).
    """

    max_lines: int
    max_chars: int
    min_chars: int


# One region of a file: an inclusive 1-based line span and the symbol that owns
# it (or None for module-level code).
_Region = tuple[int, int, Symbol | None]


def build_chunks(
    *,
    parsed_file: ParsedFile,
    source_text: str,
    config: ChunkingConfig,
) -> list[CodeChunk]:
    """Split one parsed file into symbol-aware, bounded `CodeChunk`s.

    Args:
        parsed_file: The structural extraction for the file (symbols in source
            order, workspace-relative `path`, owning `repository_id`/`file_id`).
        source_text: The file's current text. Split on `"\\n"` to match the
            parser's line numbering; a trailing `"\\r"` on any line is stripped
            from chunk content so hashes are stable across CRLF/LF checkouts.
        config: Windowing bounds.

    Returns:
        Chunks in source order. Empty if the file is empty/whitespace-only or
        every region falls below `config.min_chars`.
    """
    if not source_text.strip():
        return []

    lines = source_text.split("\n")
    line_count = len(lines)

    regions = _plan_regions(parsed_file.symbols, line_count)

    chunks: list[CodeChunk] = []
    for start, end, symbol in regions:
        chunks.extend(_window_region(parsed_file, lines, start, end, symbol, config))
    return chunks


def _plan_regions(symbols: tuple[Symbol, ...], line_count: int) -> list[_Region]:
    """Partition [1, line_count] into non-overlapping regions owned by a symbol
    or by no symbol (module-level), reconstructing nesting from
    `parent_symbol_id`."""
    by_id = {symbol.id: symbol for symbol in symbols}
    children_by_parent: dict[UUID, list[Symbol]] = defaultdict(list)
    top_level: list[Symbol] = []
    for symbol in symbols:
        parent_id = symbol.parent_symbol_id
        if parent_id is not None and parent_id in by_id:
            children_by_parent[parent_id].append(symbol)
        else:
            # A top-level symbol, or one whose parent isn't in this file (defensive
            # — a method should always ship with its class, but never assume it).
            top_level.append(symbol)

    top_level.sort(key=lambda s: (s.location.start_line, s.location.end_line))
    for children in children_by_parent.values():
        children.sort(key=lambda s: (s.location.start_line, s.location.end_line))

    if not top_level:
        return [(1, line_count, None)]

    regions: list[_Region] = []

    # Module preamble before the first top-level symbol (imports, module docstring).
    first_start = top_level[0].location.start_line
    if first_start > 1:
        regions.append((1, min(first_start - 1, line_count), None))

    for index, symbol in enumerate(top_level):
        regions.extend(_symbol_regions(symbol, children_by_parent, line_count))
        # Module-level code between this top-level symbol and the next (or the end
        # of the file) — e.g. a module-level constant or an `if __name__` block.
        symbol_end = min(symbol.location.end_line, line_count)
        if index + 1 < len(top_level):
            next_start = top_level[index + 1].location.start_line
        else:
            next_start = line_count + 1
        if next_start > symbol_end + 1:
            regions.append((symbol_end + 1, min(next_start - 1, line_count), None))

    return regions


def _symbol_regions(
    symbol: Symbol,
    children_by_parent: dict[UUID, list[Symbol]],
    line_count: int,
) -> list[_Region]:
    """Regions for one symbol: the whole span if it's a leaf, or a header +
    per-child + inter-child breakdown if it contains nested symbols."""
    start = max(symbol.location.start_line, 1)
    end = min(symbol.location.end_line, line_count)
    if start > end:
        return []

    children = children_by_parent.get(symbol.id, [])
    if not children:
        return [(start, end, symbol)]

    regions: list[_Region] = []
    first_child_start = children[0].location.start_line
    # Header: the `class ...:` line, its docstring, and any class-level attributes
    # before the first method — owned by the class itself.
    if first_child_start > start:
        regions.append((start, min(first_child_start - 1, end), symbol))

    for index, child in enumerate(children):
        regions.extend(_symbol_regions(child, children_by_parent, line_count))
        child_end = min(child.location.end_line, line_count)
        if index + 1 < len(children):
            next_start = children[index + 1].location.start_line
        else:
            next_start = end + 1
        # Code between methods, or after the last method but still inside the
        # class body — attributed back to the enclosing class.
        if next_start > child_end + 1:
            regions.append((child_end + 1, min(next_start - 1, end), symbol))

    return regions


def _window_region(
    parsed_file: ParsedFile,
    lines: list[str],
    start: int,
    end: int,
    symbol: Symbol | None,
    config: ChunkingConfig,
) -> list[CodeChunk]:
    """Split an inclusive [start, end] line span into non-overlapping windows,
    each within `max_lines`/`max_chars`, emitting a chunk per window that clears
    `min_chars`."""
    if start < 1 or end > len(lines) or start > end:
        return []

    chunks: list[CodeChunk] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + config.max_lines - 1, end)
        content = _slice(lines, cursor, window_end)
        # Shrink the window line-by-line if it exceeds the character budget, but
        # never below a single line.
        while window_end > cursor and len(content) > config.max_chars:
            window_end -= 1
            content = _slice(lines, cursor, window_end)
        # A lone line longer than the budget (minified/generated code) is
        # truncated so no chunk is ever unbounded; the [cursor, window_end] span
        # still names its real single line.
        if len(content) > config.max_chars:
            content = content[: config.max_chars]

        if len(content.strip()) >= config.min_chars:
            chunks.append(_make_chunk(parsed_file, cursor, window_end, content, symbol))

        cursor = window_end + 1
    return chunks


def _slice(lines: list[str], start: int, end: int) -> str:
    """Join lines [start, end] (1-based inclusive) with `"\\n"`, stripping a
    trailing carriage return from each so content is CRLF/LF-stable."""
    return "\n".join(line.rstrip("\r") for line in lines[start - 1 : end])


def _make_chunk(
    parsed_file: ParsedFile,
    start_line: int,
    end_line: int,
    content: str,
    symbol: Symbol | None,
) -> CodeChunk:
    """Build one `CodeChunk` with a deterministic id, content hash, and the
    owning symbol's metadata (or `None` for a module-level region)."""
    chunk_id = uuid5(
        _CHUNK_NAMESPACE,
        f"{parsed_file.repository_id}|{parsed_file.path}|{start_line}|{end_line}",
    )
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return CodeChunk(
        id=chunk_id,
        repository_id=parsed_file.repository_id,
        file_id=parsed_file.id,
        path=parsed_file.path,
        language=parsed_file.language.value,
        start_line=start_line,
        end_line=end_line,
        content=content,
        content_hash=content_hash,
        symbol_id=symbol.id if symbol is not None else None,
        symbol_qualified_name=symbol.qualified_name if symbol is not None else None,
        symbol_kind=symbol.kind.value if symbol is not None else None,
        token_estimate=max(1, len(content) // 4),
    )
