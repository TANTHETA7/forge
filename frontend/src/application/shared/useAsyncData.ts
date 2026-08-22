/**
 * useAsyncData hook.
 *
 * Purpose:       Load data when a component mounts or its inputs change, exposing
 *                loading/data/error view-state.
 * Responsibility: React state management around one read — no fetch details (those
 *                 live in infrastructure), no rendering (presentation).
 * Why it exists: `useAsyncAction` covers operations the *user* triggers; the explorer
 *                needs reads that fire on their own when inputs change. It is a
 *                separate hook rather than an option on that one because
 *                `useAsyncAction.run` intentionally changes identity per render to
 *                stay free of stale closures — putting it in an effect's dependency
 *                array would re-fetch on every render, forever. Here the caller
 *                supplies an explicit `key` describing its inputs, so re-fetching is
 *                driven by that string rather than by function identity.
 *
 *                Only the settled result is stored; `isLoading` and the idle state are
 *                *derived* from whether the stored result belongs to the current
 *                request. That keeps `setState` out of the effect body entirely — it is
 *                called only from the fetch's own callbacks — so no render cascades.
 *
 * Depends on:    react only.
 * Depended on by: application/explorer/useRepositoryExplorer.ts.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncDataState<T> {
  data: T | null;
  isLoading: boolean;
  error: string | null;
}

export interface AsyncData<T> extends AsyncDataState<T> {
  /** Re-run the current fetch, e.g. after the pipeline re-parses a repository. */
  reload: () => void;
}

const IDLE: AsyncDataState<never> = { data: null, isLoading: false, error: null };

/** A finished fetch, tagged with the request it belongs to. */
interface Settled<T> {
  stamp: string;
  data: T | null;
  error: string | null;
}

/**
 * @param key - Serialized inputs. A change re-fetches; an identical value does not.
 * @param fetcher - Read to perform. May be an inline closure; it is not a dependency.
 * @param enabled - When false, nothing is fetched and state stays idle. Use this
 *                  rather than conditionally calling the hook.
 */
export function useAsyncData<T>(
  key: string,
  fetcher: () => Promise<T>,
  enabled = true,
): AsyncData<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  // `reload` must re-fetch even when `key` is unchanged, so the identity of a request
  // is the key plus the reload counter.
  const stamp = `${key}#${reloadToken}`;

  // Keep the newest fetcher without making it a dependency. Assigned inside an
  // effect — never during render.
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    fetcherRef
      .current()
      .then((data) => {
        if (!cancelled) setSettled({ stamp, data, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setSettled({
            stamp,
            data: null,
            error: err instanceof Error ? err.message : "Unknown error",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [stamp, enabled]);

  const reload = useCallback(() => setReloadToken((n) => n + 1), []);

  // A stored result from a previous key/reload is stale, so it reads as loading.
  const current = settled?.stamp === stamp ? settled : null;
  const state: AsyncDataState<T> = !enabled
    ? IDLE
    : current
      ? { data: current.data, isLoading: false, error: current.error }
      : { data: null, isLoading: true, error: null };

  return { ...state, reload };
}
