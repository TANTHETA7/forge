/**
 * Wire-level API helpers.
 *
 * Purpose:       Build the repository-scoped URL prefixes every analysis endpoint
 *                shares, and narrow loosely-typed wire strings onto domain unions.
 * Responsibility: Pure string/type helpers — no fetching, no React, no domain rules.
 * Why it exists: Forge scopes almost everything under
 *                `/projects/{id}/repositories/{id}`. Building that by hand in each
 *                *Api.ts module would duplicate the one piece of URL structure most
 *                likely to change. `narrow` exists because the backend's
 *                `response_model` serializes its `StrEnum`s as plain strings, so the
 *                OpenAPI schema types them as `string` — this maps them back onto
 *                the domain's literal unions without an unchecked cast.
 * Depended on by: infrastructure/api/projectApi.ts, repositoryApi.ts, pipelineApi.ts.
 */

export function projectPath(projectId: string): string {
  return `/projects/${projectId}`;
}

export function repositoryPath(projectId: string, repositoryId: string): string {
  return `${projectPath(projectId)}/repositories/${repositoryId}`;
}

/**
 * Narrow a wire string onto a domain union, falling back when the backend sends a
 * value this build doesn't know.
 *
 * A fallback rather than a throw: an unrecognized status means the backend grew a
 * new enum member, which should degrade the display, not break the whole screen.
 * This mirrors how `healthApi.fetchHealth` already normalizes `state`.
 */
export function narrow<T extends string>(value: string, allowed: readonly T[], fallback: T): T {
  return (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}
