/**
 * Health domain types.
 *
 * Purpose:       Mirror the backend's `SystemStatus` wire contract as TypeScript types.
 * Responsibility: Type definitions only — no fetching, no React.
 * Why it exists: Keeps the shape of "what health data looks like" independent of how
 *                it's fetched (infrastructure) or displayed (presentation), matching
 *                the domain layer's role on the backend (see domain/health.py).
 * Depended on by: infrastructure/api/healthApi.ts, application/health/useHealthStatus.ts,
 *                 presentation/shell/StatusBadge.tsx.
 */

export type ServiceState = "ok" | "degraded";

export interface SystemStatus {
  state: ServiceState;
  appName: string;
  version: string;
}
