/**
 * Repository domain types.
 *
 * Purpose:       Mirror the backend's `RepositoryResponse` /
 *                `RepositoryMetadataResponse` wire contracts as TypeScript types.
 * Responsibility: Type definitions only — no fetching, no React.
 * Why it exists: Keeps "what an imported repository looks like" independent of how
 *                it's fetched (infrastructure) or displayed (presentation), matching
 *                the domain layer's role on the backend (see
 *                domain/repository/entities.py).
 * Depended on by: infrastructure/api/repositoryApi.ts,
 *                 application/pipeline/useRepositoryPipeline.ts,
 *                 presentation/repository/RepositoryCard.tsx.
 */

/** Mirrors backend `RepositorySourceType` (domain/repository/entities.py). */
export type RepositorySourceType = "zip" | "git";

/** Mirrors backend `RepositoryStatus` (domain/repository/entities.py). */
export type RepositoryStatus = "pending" | "importing" | "ready" | "failed";

export interface RepositoryMetadata {
  fileCount: number;
  directoryCount: number;
  totalSizeBytes: number;
  /** Language name -> percentage of the repository, e.g. `{ Python: 100.0 }`. */
  languageStats: Record<string, number>;
  hasReadme: boolean;
  hasGit: boolean;
  scannedAt: string;
}

export interface Repository {
  id: string;
  projectId: string;
  sourceType: RepositorySourceType;
  displayName: string;
  status: RepositoryStatus;
  /** Populated once the repository reaches `ready`; `null` until then. */
  metadata: RepositoryMetadata | null;
  /** Populated once the repository reaches `failed`; `null` otherwise. */
  errorMessage: string | null;
  createdAt: string;
  updatedAt: string;
}
