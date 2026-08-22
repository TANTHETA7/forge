/**
 * HTTP client.
 *
 * Purpose:       One place that knows the backend's base URL, how to make a
 *                request against it, and how to turn a failure response into an
 *                `ApiError` carrying the backend's own message.
 * Responsibility: Transport only — no domain knowledge, no React.
 * Why it exists: Every infrastructure/api/*Api.ts module (projectApi,
 *                repositoryApi, pipelineApi, ...) calls through this instead of
 *                using `fetch` directly, so the base URL and error handling live
 *                in exactly one place.
 * Depends on:    import.meta.env only.
 * Depended on by: infrastructure/api/healthApi.ts, projectApi.ts,
 *                 repositoryApi.ts, pipelineApi.ts.
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

/** Domain error body from api/error_handlers.py: `{"error": "...", "message": "..."}`. */
interface DomainErrorBody {
  error: string;
  message: string;
}

/** FastAPI validation error body: `{"detail": [{"loc": [...], "msg": "..."}]}`. */
interface ValidationErrorBody {
  detail: { loc?: (string | number)[]; msg: string }[] | string;
}

function isDomainErrorBody(body: unknown): body is DomainErrorBody {
  return (
    typeof body === "object" &&
    body !== null &&
    typeof (body as DomainErrorBody).message === "string"
  );
}

function isValidationErrorBody(body: unknown): body is ValidationErrorBody {
  return typeof body === "object" && body !== null && "detail" in body;
}

/**
 * Extract the most useful human-readable message the backend gave us.
 *
 * Forge answers failures in two shapes — domain errors (`NotFoundError`,
 * `UnsupportedRepositoryStateError`, ...) carry `message`, while FastAPI's
 * request validation carries `detail`. Both are unwrapped here so callers and
 * the UI never have to branch on which one arrived.
 */
async function toApiError(response: Response, method: string, path: string): Promise<ApiError> {
  const fallback = `${method} ${path} failed with status ${response.status}`;

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return new ApiError(response.status, fallback);
  }

  if (isDomainErrorBody(body)) {
    return new ApiError(response.status, body.message);
  }

  if (isValidationErrorBody(body)) {
    const { detail } = body;
    if (typeof detail === "string") {
      return new ApiError(response.status, detail);
    }
    const message = detail
      .map((item) => {
        // Drop the leading "body"/"path"/"query" segment — it adds no signal for a user.
        const field = item.loc?.slice(1).join(".");
        return field ? `${field}: ${item.msg}` : item.msg;
      })
      .join("; ");
    return new ApiError(response.status, message || fallback);
  }

  return new ApiError(response.status, fallback);
}

async function request<T>(method: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { method, ...init });

  if (!response.ok) {
    throw await toApiError(response, method, path);
  }

  return (await response.json()) as T;
}

/**
 * Perform a GET request against the Forge backend and parse the JSON response.
 *
 * @param path - Path relative to the API base URL, e.g. "/health".
 * @throws {ApiError} if the response status is not ok.
 */
export async function apiGet<T>(path: string): Promise<T> {
  return request<T>("GET", path);
}

/**
 * Perform a POST request with an optional JSON body.
 *
 * Forge's pipeline operations (parse, analyze-dependencies, graph/project) take
 * no body at all, so `body` is optional and the `Content-Type` header is only
 * set when there is something to send.
 *
 * @throws {ApiError} if the response status is not ok.
 */
export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(
    "POST",
    path,
    body === undefined
      ? undefined
      : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  );
}

/**
 * Perform a multipart POST — used for ZIP upload, where the browser must set the
 * `Content-Type` boundary itself, so no headers are supplied here.
 *
 * @throws {ApiError} if the response status is not ok.
 */
export async function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  return request<T>("POST", path, { body: form });
}
