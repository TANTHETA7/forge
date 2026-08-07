/**
 * Health application hook.
 *
 * Purpose:       Orchestrate fetching health status and expose it as view-state.
 * Responsibility: React state management around one use case — no fetch/DOM
 *                 details (those live in infrastructure), no rendering (that
 *                 lives in presentation).
 * Depends on:    infrastructure/api/healthApi.ts, domain/health/types.ts.
 * Depended on by: presentation/shell/StatusBadge.tsx.
 */

import { useEffect, useState } from "react";

import { fetchHealth } from "@/infrastructure/api/healthApi";
import type { SystemStatus } from "@/domain/health/types";

interface HealthStatusView {
  status: SystemStatus | null;
  isLoading: boolean;
  error: string | null;
}

export function useHealthStatus(): HealthStatusView {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetchHealth()
      .then((result) => {
        if (!cancelled) setStatus(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Unknown error");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { status, isLoading, error };
}
