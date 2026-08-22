/**
 * useRepositoryExplorer hook.
 *
 * Purpose:       Read-only exploration of a parsed repository — its files, its
 *                symbols (filtered and paged), one selected symbol's details, and
 *                its parse errors.
 * Responsibility: React state and request orchestration — no fetch details, no
 *                 rendering.
 * Why it exists: Keeps the request budget explicit and small. Opening the explorer
 *                costs exactly three requests (files, first symbol page, parse
 *                errors); changing a filter or page costs one; selecting a symbol
 *                costs one. Nothing is fetched per row, so there is no N+1.
 * Depends on:    application/shared/useAsyncData.ts,
 *                infrastructure/api/explorerApi.ts, domain/explorer/types.ts.
 * Depended on by: presentation/explorer/ExplorerPanel.tsx.
 */

import { useCallback, useState } from "react";

import { useAsyncData } from "@/application/shared/useAsyncData";
import {
  fetchFiles,
  fetchParseErrors,
  fetchSymbol,
  fetchSymbols,
} from "@/infrastructure/api/explorerApi";
import type { SymbolKind } from "@/domain/explorer/types";

/**
 * Symbols per page. The endpoint's own default is 100; a smaller page keeps the
 * initial render bounded on a real repository. It is well under the backend default,
 * so no limit is being exceeded.
 */
export const SYMBOL_PAGE_SIZE = 25;

/** `"all"` means "send no `kind` parameter", not a value the backend understands. */
export type KindFilter = SymbolKind | "all";

export function useRepositoryExplorer(
  projectId: string | null,
  repositoryId: string | null,
  enabled: boolean,
) {
  const [kindFilter, setKind] = useState<KindFilter>("all");
  const [fileFilter, setFile] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [selectedSymbolId, setSelectedSymbolId] = useState<string | null>(null);

  const scoped = enabled && projectId !== null && repositoryId !== null;
  const scope = `${projectId ?? "-"}:${repositoryId ?? "-"}`;

  const files = useAsyncData(
    `files:${scope}`,
    () => fetchFiles(projectId as string, repositoryId as string),
    scoped,
  );

  const symbols = useAsyncData(
    `symbols:${scope}:${kindFilter}:${fileFilter ?? "-"}:${page}`,
    () =>
      fetchSymbols(projectId as string, repositoryId as string, {
        ...(kindFilter === "all" ? {} : { kind: kindFilter }),
        ...(fileFilter ? { fileId: fileFilter } : {}),
        limit: SYMBOL_PAGE_SIZE,
        offset: page * SYMBOL_PAGE_SIZE,
      }),
    scoped,
  );

  const parseErrors = useAsyncData(
    `parse-errors:${scope}`,
    () => fetchParseErrors(projectId as string, repositoryId as string),
    scoped,
  );

  const selectedSymbol = useAsyncData(
    `symbol:${scope}:${selectedSymbolId ?? "-"}`,
    () => fetchSymbol(projectId as string, repositoryId as string, selectedSymbolId as string),
    scoped && selectedSymbolId !== null,
  );

  /**
   * The API returns a bare array with no total count, so "there may be another page"
   * can only be inferred from a full page. A final page that happens to be exactly
   * full shows a Next that lands on an empty page — the honest cost of having no
   * count, rather than a fabricated total.
   */
  const hasNextPage = (symbols.data?.length ?? 0) === SYMBOL_PAGE_SIZE;

  // Changing a filter invalidates the current offset, so paging restarts.
  const setKindFilter = useCallback((kind: KindFilter) => {
    setKind(kind);
    setPage(0);
  }, []);

  const setFileFilter = useCallback((fileId: string | null) => {
    setFile(fileId);
    setPage(0);
  }, []);

  const selectSymbol = useCallback((symbolId: string | null) => {
    setSelectedSymbolId(symbolId);
  }, []);

  const nextPage = useCallback(() => setPage((p) => p + 1), []);
  const previousPage = useCallback(() => setPage((p) => Math.max(0, p - 1)), []);

  return {
    files,
    symbols,
    parseErrors,
    selectedSymbol,
    selectedSymbolId,
    selectSymbol,
    kindFilter,
    setKindFilter,
    fileFilter,
    setFileFilter,
    page,
    hasNextPage,
    nextPage,
    previousPage,
  };
}
