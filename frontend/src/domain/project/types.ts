/**
 * Project domain types.
 *
 * Purpose:       Mirror the backend's `ProjectResponse` wire contract as TypeScript types.
 * Responsibility: Type definitions only — no fetching, no React.
 * Why it exists: Keeps "what a project looks like" independent of how it's fetched
 *                (infrastructure) or displayed (presentation), matching the domain
 *                layer's role on the backend (see domain/project/entities.py).
 * Depended on by: infrastructure/api/projectApi.ts,
 *                 application/pipeline/useRepositoryPipeline.ts.
 */

/** Mirrors backend `ProjectStatus` (domain/project/entities.py). */
export type ProjectStatus = "created" | "importing" | "ready" | "failed";

export interface Project {
  id: string;
  name: string;
  description: string | null;
  status: ProjectStatus;
  createdAt: string;
  updatedAt: string;
}
