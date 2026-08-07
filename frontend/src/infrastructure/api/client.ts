/**
 * HTTP client.
 *
 * Purpose:       One place that knows the backend's base URL and how to make a
 *                request against it.
 * Responsibility: Transport only — no domain knowledge, no React.
 * Why it exists: Every future infrastructure/api/*Api.ts module (repositoryApi,
 *                dependencyGraphApi, ...) calls through this instead of using
 *                `fetch` directly, so the base URL and error handling live in
 *                exactly one place.
 * Depends on:    import.meta.env only.
 * Depended on by: infrastructure/api/healthApi.ts, and every future *Api.ts module.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Perform a GET request against the Forge backend and parse the JSON response.
 *
 * @param path - Path relative to the API base URL, e.g. "/health".
 * @throws {ApiError} if the response status is not ok.
 */
export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);

  if (!response.ok) {
    throw new ApiError(response.status, `GET ${path} failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}
