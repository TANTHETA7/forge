/**
 * Repository API client.
 *
 * Purpose:       Import repositories (ZIP upload or Git clone) and fetch their
 *                status/metadata, translating the wire format into the domain's
 *                `Repository` type.
 * Responsibility: The three repository endpoints — `import/zip`, `import/git`,
 *                 `GET {repository_id}`.
 * Why it exists: Import is synchronous on the backend (verified live: a ZIP import
 *                returns `status: "ready"` with metadata already populated), so
 *                these calls need no polling loop.
 * Depends on:    infrastructure/api/client.ts, wire.ts, domain/repository/types.ts.
 * Depended on by: application/pipeline/useRepositoryPipeline.ts.
 */

import { apiGet, apiPost, apiPostForm } from "@/infrastructure/api/client";
import { narrow, projectPath, repositoryPath } from "@/infrastructure/api/wire";
import type {
  Repository,
  RepositoryMetadata,
  RepositorySourceType,
  RepositoryStatus,
} from "@/domain/repository/types";

const SOURCE_TYPES: readonly RepositorySourceType[] = ["zip", "git"];
const STATUSES: readonly RepositoryStatus[] = ["pending", "importing", "ready", "failed"];

interface RepositoryMetadataDto {
  file_count: number;
  directory_count: number;
  total_size_bytes: number;
  language_stats: Record<string, number>;
  has_readme: boolean;
  has_git: boolean;
  scanned_at: string;
}

interface RepositoryResponseDto {
  id: string;
  project_id: string;
  source_type: string;
  display_name: string;
  status: string;
  metadata: RepositoryMetadataDto | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

function toMetadata(dto: RepositoryMetadataDto): RepositoryMetadata {
  return {
    fileCount: dto.file_count,
    directoryCount: dto.directory_count,
    totalSizeBytes: dto.total_size_bytes,
    languageStats: dto.language_stats,
    hasReadme: dto.has_readme,
    hasGit: dto.has_git,
    scannedAt: dto.scanned_at,
  };
}

function toRepository(dto: RepositoryResponseDto): Repository {
  return {
    id: dto.id,
    projectId: dto.project_id,
    sourceType: narrow(dto.source_type, SOURCE_TYPES, "zip"),
    displayName: dto.display_name,
    status: narrow(dto.status, STATUSES, "pending"),
    metadata: dto.metadata ? toMetadata(dto.metadata) : null,
    errorMessage: dto.error_message,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  };
}

/**
 * Import a repository from a ZIP archive.
 *
 * The multipart field names are fixed by the backend: `file` (required) and
 * `display_name` (optional).
 */
export async function importZipRepository(
  projectId: string,
  file: File,
  displayName?: string,
): Promise<Repository> {
  const form = new FormData();
  form.append("file", file);
  if (displayName) form.append("display_name", displayName);

  return toRepository(
    await apiPostForm<RepositoryResponseDto>(
      `${projectPath(projectId)}/repositories/import/zip`,
      form,
    ),
  );
}

/**
 * Import a repository by cloning a Git URL.
 *
 * @param url - HTTPS only; the backend rejects other schemes with 400
 *              `SourceValidationError`.
 */
export async function importGitRepository(projectId: string, url: string): Promise<Repository> {
  return toRepository(
    await apiPost<RepositoryResponseDto>(`${projectPath(projectId)}/repositories/import/git`, {
      url,
    }),
  );
}

export async function fetchRepository(
  projectId: string,
  repositoryId: string,
): Promise<Repository> {
  return toRepository(
    await apiGet<RepositoryResponseDto>(repositoryPath(projectId, repositoryId)),
  );
}
