/**
 * AsyncSection component.
 *
 * Purpose:       Render the loading, error, and empty states of an async read, and
 *                delegate to `children` once data has arrived.
 * Responsibility: Presentation only — it decides which of the four states to show.
 * Why it exists: The explorer has four independent reads (files, symbols, symbol
 *                details, parse errors) that each need identical loading/error/empty
 *                handling. Without this they would be four copies of the same
 *                branching, and the states would drift apart visually.
 * Depends on:    application/shared/useAsyncData.ts (for `AsyncDataState`).
 * Depended on by: presentation/explorer/*.
 */

import type { ReactNode } from "react";

import type { AsyncDataState } from "@/application/shared/useAsyncData";

interface AsyncSectionProps<T> {
  state: AsyncDataState<T>;
  /** Shown when the read succeeded but returned nothing. */
  emptyMessage: string;
  /** Defaults to treating an empty array as empty. */
  isEmpty?: (data: T) => boolean;
  loadingMessage?: string;
  children: (data: T) => ReactNode;
}

function defaultIsEmpty<T>(data: T): boolean {
  return Array.isArray(data) && data.length === 0;
}

export function AsyncSection<T>({
  state,
  emptyMessage,
  isEmpty = defaultIsEmpty,
  loadingMessage = "Loading…",
  children,
}: AsyncSectionProps<T>) {
  if (state.isLoading) {
    return <p className="py-3 text-sm text-neutral-500">{loadingMessage}</p>;
  }

  if (state.error) {
    return (
      <p role="alert" className="my-2 rounded-md bg-red-950 px-3 py-2 text-sm text-red-300">
        {state.error}
      </p>
    );
  }

  if (state.data === null) return null;

  if (isEmpty(state.data)) {
    return <p className="py-3 text-sm text-neutral-500">{emptyMessage}</p>;
  }

  return <>{children(state.data)}</>;
}
