/**
 * useAsyncAction hook.
 *
 * Purpose:       Wrap a one-shot async call in the pending/data/error view-state
 *                every triggered operation needs.
 * Responsibility: React state management around a single async function — no
 *                 fetching details (those live in infrastructure), no rendering.
 * Why it exists: The repository pipeline has four user-triggered operations
 *                (import, parse, analyze, project) with identical state shape.
 *                Without this they would be four copies of the same
 *                `useState`/try/catch/finally block. Mirrors the pending-guard
 *                pattern already used by `useHealthStatus`, but for actions the
 *                user triggers rather than an effect that runs on mount.
 * Depends on:    react only.
 * Depended on by: application/pipeline/useRepositoryPipeline.ts.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncActionState<T> {
  data: T | null;
  isPending: boolean;
  error: string | null;
}

export interface AsyncAction<TArgs extends unknown[], TResult>
  extends AsyncActionState<TResult> {
  /** Runs the action. Resolves to the result, or `null` if it failed. */
  run: (...args: TArgs) => Promise<TResult | null>;
  reset: () => void;
}

const INITIAL: AsyncActionState<never> = { data: null, isPending: false, error: null };

export function useAsyncAction<TArgs extends unknown[], TResult>(
  fn: (...args: TArgs) => Promise<TResult>,
): AsyncAction<TArgs, TResult> {
  const [state, setState] = useState<AsyncActionState<TResult>>(INITIAL);

  // Never call setState after unmount — these actions can outlive the screen
  // (graph projection alone takes several seconds). Read only inside the async
  // callback below, never during render.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // `fn` is captured directly rather than held in a ref, so `run` always calls the
  // caller's latest closure and sees current state. Callers pass inline closures, so
  // `run`'s identity changes per render — nothing here is memoized on it.
  const run = useCallback(
    async (...args: TArgs): Promise<TResult | null> => {
      setState({ data: null, isPending: true, error: null });
      try {
        const result = await fn(...args);
        if (mountedRef.current) setState({ data: result, isPending: false, error: null });
        return result;
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Unknown error";
        if (mountedRef.current) setState({ data: null, isPending: false, error: message });
        return null;
      }
    },
    [fn],
  );

  const reset = useCallback(() => setState(INITIAL), []);

  return { ...state, run, reset };
}
