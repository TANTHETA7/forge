"""Unit tests for symbol-aware code chunking (Phase 7).

Scope: the pure `build_chunks` transformation only — no IO, no embeddings, no
persistence. These prove the four properties the rest of the RAG pipeline relies
on: chunks align to real symbol boundaries (so every citation is a genuine
definition span), coverage is complete and non-overlapping, chunks are bounded
(no giant chunk can dominate an embedding or prompt), and ids are deterministic
and repository-scoped (stable references; two repositories never collide).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from forge.domain.parsing.entities import (
    Language,
    ParsedFile,
    SourceLocation,
    Symbol,
    SymbolKind,
)
from forge.domain.rag.chunking import ChunkingConfig, build_chunks

_CONFIG = ChunkingConfig(max_lines=160, max_chars=6000, min_chars=1)


def _loc(start: int, end: int) -> SourceLocation:
    return SourceLocation(start_line=start, end_line=end, start_column=0, end_column=None)


def _symbol(
    name: str,
    start: int,
    end: int,
    *,
    kind: SymbolKind = SymbolKind.FUNCTION,
    parent_symbol_id: UUID | None = None,
) -> Symbol:
    return Symbol(
        id=uuid4(),
        kind=kind,
        name=name,
        qualified_name=name,
        location=_loc(start, end),
        parameters=(),
        parent_symbol_id=parent_symbol_id,
    )


def _file(
    *,
    symbols: tuple[Symbol, ...] = (),
    repository_id: UUID | None = None,
    path: str = "pkg/module.py",
) -> ParsedFile:
    repository_id = repository_id or uuid4()
    return ParsedFile(
        id=uuid4(),
        repository_id=repository_id,
        path=path,
        language=Language.PYTHON,
        symbols=symbols,
        imports=(),
        has_syntax_errors=False,
    )


def test_empty_source_yields_no_chunks() -> None:
    assert build_chunks(parsed_file=_file(), source_text="", config=_CONFIG) == []


def test_whitespace_only_source_yields_no_chunks() -> None:
    assert build_chunks(parsed_file=_file(), source_text="   \n\n\t\n", config=_CONFIG) == []


def test_file_with_no_symbols_becomes_one_whole_file_region() -> None:
    source = "x = 1\ny = 2\nz = 3"  # no trailing newline -> exactly 3 lines
    chunks = build_chunks(parsed_file=_file(), source_text=source, config=_CONFIG)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.symbol_id is None
    assert chunk.symbol_qualified_name is None
    assert chunk.start_line == 1
    assert chunk.end_line == 3
    assert "x = 1" in chunk.content and "z = 3" in chunk.content


def test_symbol_aware_regions_for_class_with_methods_and_module_code() -> None:
    # Lines are hand-numbered so the assertions below are exact.
    source = "\n".join(
        [
            "import os",              # 1  module preamble
            "",                       # 2
            "class Foo:",             # 3  class header (owned by Foo)
            "    attr = 1",           # 4
            "    def method_a(self):",  # 5  method_a
            "        return 1",       # 6
            "    def method_b(self):",  # 7  method_b
            "        return 2",       # 8
            "",                       # 9  module-level gap
            "def top_level():",       # 10 top-level function
            "    return Foo()",       # 11
        ]
    )
    foo = _symbol("Foo", 3, 8, kind=SymbolKind.CLASS)
    method_a = _symbol("Foo.method_a", 5, 6, kind=SymbolKind.METHOD, parent_symbol_id=foo.id)
    method_b = _symbol("Foo.method_b", 7, 8, kind=SymbolKind.METHOD, parent_symbol_id=foo.id)
    top_level = _symbol("top_level", 10, 11)
    parsed = _file(symbols=(foo, method_a, method_b, top_level))

    chunks = build_chunks(parsed_file=parsed, source_text=source, config=_CONFIG)

    # (qualified_name, start_line, end_line) for each surviving region — blank-only
    # regions (line 9) fall below min_chars and are dropped.
    shape = [(c.symbol_qualified_name, c.start_line, c.end_line) for c in chunks]
    assert shape == [
        (None, 1, 2),            # module preamble: import + blank
        ("Foo", 3, 4),           # class header + attr, owned by the class
        ("Foo.method_a", 5, 6),
        ("Foo.method_b", 7, 8),
        ("top_level", 10, 11),
    ]
    # Kinds are carried through from the owning symbol.
    by_name = {c.symbol_qualified_name: c for c in chunks}
    assert by_name["Foo"].symbol_kind == "class"
    assert by_name["Foo.method_a"].symbol_kind == "method"
    assert by_name["top_level"].symbol_kind == "function"
    # The class-header chunk carries the class's own symbol id, methods their own.
    assert by_name["Foo"].symbol_id == foo.id
    assert by_name["Foo.method_a"].symbol_id == method_a.id


def test_regions_are_non_overlapping_and_cover_every_symbol_line() -> None:
    source = "\n".join(f"line{i}" for i in range(1, 13))  # 12 lines
    a = _symbol("a", 1, 4)
    b = _symbol("b", 7, 9)
    parsed = _file(symbols=(a, b))

    chunks = build_chunks(parsed_file=parsed, source_text=source, config=_CONFIG)

    spans = sorted((c.start_line, c.end_line) for c in chunks)
    # No two spans overlap.
    for (s1, e1), (s2, e2) in zip(spans, spans[1:], strict=False):
        assert e1 < s2, f"overlap between {(s1, e1)} and {(s2, e2)}"
    # The symbol lines are all covered (module gaps between/around them too).
    covered = {line for s, e in spans for line in range(s, e + 1)}
    assert {1, 2, 3, 4}.issubset(covered)  # symbol a
    assert {7, 8, 9}.issubset(covered)  # symbol b


def test_long_region_is_split_into_bounded_non_overlapping_windows() -> None:
    # 12 non-trivial lines under a single function, windowed at 5 lines each.
    source = "\n".join(f"statement_{i} = {i}" for i in range(1, 13))
    func = _symbol("big", 1, 12)
    parsed = _file(symbols=(func,))
    config = ChunkingConfig(max_lines=5, max_chars=6000, min_chars=1)

    chunks = build_chunks(parsed_file=parsed, source_text=source, config=config)

    spans = [(c.start_line, c.end_line) for c in chunks]
    assert spans == [(1, 5), (6, 10), (11, 12)]  # bounded, contiguous, no overlap
    assert all(c.symbol_id == func.id for c in chunks)  # all still attributed to the symbol
    assert all((c.end_line - c.start_line + 1) <= 5 for c in chunks)


def test_single_line_longer_than_max_chars_is_truncated_not_unbounded() -> None:
    long_line = "x = '" + ("A" * 500) + "'"
    parsed = _file()
    config = ChunkingConfig(max_lines=160, max_chars=100, min_chars=1)

    chunks = build_chunks(parsed_file=parsed, source_text=long_line, config=config)

    assert len(chunks) == 1
    assert len(chunks[0].content) <= 100  # a lone over-budget line is capped


def test_region_below_min_chars_is_dropped() -> None:
    source = "a\n"  # a single 1-char line
    parsed = _file()
    config = ChunkingConfig(max_lines=160, max_chars=6000, min_chars=24)

    assert build_chunks(parsed_file=parsed, source_text=source, config=config) == []


def test_chunk_ids_are_deterministic_across_identical_inputs() -> None:
    repo_id = uuid4()
    source = "def f():\n    return 1\n"
    symbols = (_symbol("f", 1, 2),)

    first = build_chunks(
        parsed_file=_file(symbols=symbols, repository_id=repo_id, path="a.py"),
        source_text=source,
        config=_CONFIG,
    )
    second = build_chunks(
        parsed_file=_file(symbols=symbols, repository_id=repo_id, path="a.py"),
        source_text=source,
        config=_CONFIG,
    )

    assert [c.id for c in first] == [c.id for c in second]
    assert [c.content_hash for c in first] == [c.content_hash for c in second]


def test_chunk_ids_differ_across_repositories_for_identical_files() -> None:
    source = "def f():\n    return 1\n"
    symbols = (_symbol("f", 1, 2),)
    repo_a = build_chunks(
        parsed_file=_file(symbols=symbols, repository_id=uuid4(), path="a.py"),
        source_text=source,
        config=_CONFIG,
    )
    repo_b = build_chunks(
        parsed_file=_file(symbols=symbols, repository_id=uuid4(), path="a.py"),
        source_text=source,
        config=_CONFIG,
    )

    # Same content -> same content_hash (embedding reuse is by content), but a
    # different repository_id -> different chunk id (no cross-repository collision).
    assert repo_a[0].content_hash == repo_b[0].content_hash
    assert repo_a[0].id != repo_b[0].id


def test_crlf_and_lf_produce_identical_content_and_hash() -> None:
    parsed = _file()
    lf = build_chunks(parsed_file=parsed, source_text="a = 1\nb = 2\n", config=_CONFIG)
    crlf = build_chunks(parsed_file=parsed, source_text="a = 1\r\nb = 2\r\n", config=_CONFIG)

    assert lf[0].content == crlf[0].content  # trailing \r stripped
    assert "\r" not in crlf[0].content
    assert lf[0].content_hash == crlf[0].content_hash  # stable across checkouts


def test_content_hash_matches_sha256_of_content() -> None:
    import hashlib

    chunks = build_chunks(parsed_file=_file(), source_text="value = 42\n", config=_CONFIG)

    expected = hashlib.sha256(chunks[0].content.encode("utf-8")).hexdigest()
    assert chunks[0].content_hash == expected
