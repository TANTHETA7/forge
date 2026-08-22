/**
 * Project API client.
 *
 * Purpose:       Create projects, translating the wire format into the domain's
 *                `Project` type.
 * Responsibility: One endpoint — `POST /projects`.
 * Why it exists: `GET /projects/{id}` also exists on the backend but nothing in the
 *                UI needs it yet: the create response already carries every field,
 *                and the pipeline holds the project in state for its lifetime. It is
 *                left unwrapped rather than added speculatively.
 * Depends on:    infrastructure/api/client.ts, domain/project/types.ts.
 * Depended on by: application/pipeline/useRepositoryPipeline.ts.
 */

import { apiPost } from "@/infrastructure/api/client";
import { narrow } from "@/infrastructure/api/wire";
import type { Project, ProjectStatus } from "@/domain/project/types";

const PROJECT_STATUSES: readonly ProjectStatus[] = ["created", "importing", "ready", "failed"];

interface ProjectResponseDto {
  id: string;
  name: string;
  description: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

function toProject(dto: ProjectResponseDto): Project {
  return {
    id: dto.id,
    name: dto.name,
    description: dto.description,
    status: narrow(dto.status, PROJECT_STATUSES, "created"),
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  };
}

/**
 * Create a project.
 *
 * @param name - 1–200 characters, per the backend's `ProjectCreateRequest`.
 * @param description - Optional, up to 2000 characters. Omitted when blank.
 */
export async function createProject(name: string, description?: string): Promise<Project> {
  const body: { name: string; description?: string } = { name };
  if (description) body.description = description;
  return toProject(await apiPost<ProjectResponseDto>("/projects", body));
}
