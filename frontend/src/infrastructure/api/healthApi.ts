/**
 * Health API client.
 *
 * Purpose:       Fetch system health from the backend and translate the wire
 *                format into the domain's `SystemStatus` type.
 * Responsibility: One function, one endpoint.
 * Depends on:    infrastructure/api/client.ts, domain/health/types.ts.
 * Depended on by: application/health/useHealthStatus.ts.
 */

import { apiGet } from "@/infrastructure/api/client";
import type { SystemStatus } from "@/domain/health/types";

interface HealthResponseDto {
  state: string;
  app_name: string;
  version: string;
}

export async function fetchHealth(): Promise<SystemStatus> {
  const dto = await apiGet<HealthResponseDto>("/health");
  return {
    state: dto.state === "ok" ? "ok" : "degraded",
    appName: dto.app_name,
    version: dto.version,
  };
}
