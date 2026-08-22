/**
 * SymbolList component.
 *
 * Purpose:       List symbols with a kind filter and paging, and report which one is
 *                selected.
 * Responsibility: Presentation only. Filter and page state live in
 *                 `useRepositoryExplorer`; this renders controls and reports intent.
 * Why it exists: The kind filter maps exactly onto the backend's `kind` query
 *                parameter (`function | class | method`) — no client-side filtering
 *                and no unsupported filters are offered.
 * Depends on:    domain/explorer/types.ts, application/explorer/useRepositoryExplorer.ts
 *                (for `KindFilter`), presentation/shared/AsyncSection.tsx.
 * Depended on by: presentation/explorer/ExplorerPanel.tsx.
 */

import type { KindFilter } from "@/application/explorer/useRepositoryExplorer";
import type { AsyncDataState } from "@/application/shared/useAsyncData";
import { SYMBOL_KINDS, type CodeSymbol } from "@/domain/explorer/types";
import { AsyncSection } from "@/presentation/shared/AsyncSection";

const FILTERS: readonly KindFilter[] = ["all", ...SYMBOL_KINDS];

interface SymbolListProps {
  state: AsyncDataState<CodeSymbol[]>;
  kindFilter: KindFilter;
  onKindChange: (kind: KindFilter) => void;
  selectedSymbolId: string | null;
  onSelectSymbol: (symbolId: string) => void;
  isFileFiltered: boolean;
  page: number;
  hasNextPage: boolean;
  onNextPage: () => void;
  onPreviousPage: () => void;
}

export function SymbolList({
  state,
  kindFilter,
  onKindChange,
  selectedSymbolId,
  onSelectSymbol,
  isFileFiltered,
  page,
  hasNextPage,
  onNextPage,
  onPreviousPage,
}: SymbolListProps) {
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-1.5" role="group" aria-label="Filter by kind">
        {FILTERS.map((kind) => (
          <button
            key={kind}
            type="button"
            aria-pressed={kindFilter === kind}
            onClick={() => onKindChange(kind)}
            className={
              "rounded-md px-2.5 py-1 text-xs " +
              (kindFilter === kind
                ? "bg-neutral-100 font-medium text-neutral-900"
                : "bg-neutral-800 text-neutral-300 hover:bg-neutral-700")
            }
          >
            {kind}
          </button>
        ))}
      </div>

      <AsyncSection
        state={state}
        loadingMessage="Loading symbols…"
        emptyMessage={
          page > 0
            ? "No symbols on this page — go back a page."
            : isFileFiltered
              ? "No symbols of this kind in the selected file."
              : "No symbols of this kind in this repository."
        }
      >
        {(symbols) => (
          <ul className="divide-y divide-neutral-800">
            {symbols.map((symbol) => {
              const isSelected = symbol.id === selectedSymbolId;
              return (
                <li key={symbol.id}>
                  <button
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => onSelectSymbol(symbol.id)}
                    className={
                      "flex w-full flex-wrap items-baseline gap-2 px-2 py-1.5 text-left text-sm " +
                      (isSelected ? "bg-neutral-800" : "hover:bg-neutral-900")
                    }
                  >
                    <span className="font-mono text-xs text-neutral-500">{symbol.kind}</span>
                    <span className="text-neutral-100">{symbol.name}</span>
                    <span className="ml-auto font-mono text-xs text-neutral-600">
                      L{symbol.startLine}–{symbol.endLine}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </AsyncSection>

      {/* The API returns no total count, so paging is Prev/Next over offsets only. */}
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={onPreviousPage}
          disabled={page === 0 || state.isLoading}
          className="rounded-md bg-neutral-800 px-2.5 py-1 text-xs text-neutral-300 hover:bg-neutral-700 disabled:opacity-40"
        >
          Previous
        </button>
        <span className="text-xs text-neutral-600">page {page + 1}</span>
        <button
          type="button"
          onClick={onNextPage}
          disabled={!hasNextPage || state.isLoading}
          className="rounded-md bg-neutral-800 px-2.5 py-1 text-xs text-neutral-300 hover:bg-neutral-700 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
