/**
 * StatusBadge component.
 *
 * Purpose:       Render the backend's current health state.
 * Responsibility: Presentation only — reads view-state from `useHealthStatus`,
 *                 renders markup. No fetching logic of its own.
 * Depends on:    application/health/useHealthStatus.ts.
 * Depended on by: presentation/shell/AppShell.tsx.
 */

import { useHealthStatus } from "@/application/health/useHealthStatus";

export function StatusBadge() {
  const { status, isLoading, error } = useHealthStatus();

  if (isLoading) {
    return <span className="text-sm text-neutral-400">Checking backend…</span>;
  }

  if (error || !status) {
    return (
      <span className="rounded-full bg-red-950 px-3 py-1 text-sm text-red-300">
        Backend unreachable
      </span>
    );
  }

  const isOk = status.state === "ok";

  return (
    <span
      className={
        "rounded-full px-3 py-1 text-sm " +
        (isOk ? "bg-emerald-950 text-emerald-300" : "bg-amber-950 text-amber-300")
      }
    >
      {status.appName} v{status.version} · {status.state}
    </span>
  );
}
