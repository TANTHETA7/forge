import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiGet, apiPost, apiPostForm } from "@/infrastructure/api/client";

/** Build a `Response`-like stub; `body` is returned by `.json()`. */
function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

function invalidJsonResponse(status: number): Response {
  return {
    ok: false,
    status,
    json: () => Promise.reject(new Error("not json")),
  } as Response;
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiGet", () => {
  it("returns the parsed JSON body on success", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { state: "ok" }));

    await expect(apiGet<{ state: string }>("/health")).resolves.toEqual({ state: "ok" });
  });

  it("surfaces a domain error's own message", async () => {
    // Shape produced by the backend's api/error_handlers.py.
    fetchMock.mockResolvedValue(
      jsonResponse(404, { error: "NotFoundError", message: "Repository abc not found" }),
    );

    await expect(apiGet("/x")).rejects.toThrow(
      expect.objectContaining({ status: 404, message: "Repository abc not found" }),
    );
  });

  it("surfaces a 409 out-of-order pipeline error verbatim", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(409, {
        error: "UnsupportedRepositoryStateError",
        message: "Repository abc has not been parsed yet — run POST .../parse first",
      }),
    );

    await expect(apiGet("/x")).rejects.toThrow(/has not been parsed yet/);
  });

  it("flattens a FastAPI validation detail array, dropping the location prefix", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(422, {
        detail: [{ loc: ["body", "name"], msg: "Field required" }],
      }),
    );

    await expect(apiGet("/x")).rejects.toThrow(
      expect.objectContaining({ status: 422, message: "name: Field required" }),
    );
  });

  it("joins multiple validation errors", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(422, {
        detail: [
          { loc: ["body", "name"], msg: "Field required" },
          { loc: ["body", "url"], msg: "Too short" },
        ],
      }),
    );

    await expect(apiGet("/x")).rejects.toThrow("name: Field required; url: Too short");
  });

  it("accepts a string detail", async () => {
    fetchMock.mockResolvedValue(jsonResponse(400, { detail: "Bad request" }));

    await expect(apiGet("/x")).rejects.toThrow("Bad request");
  });

  it("falls back to a status message when the error body is not JSON", async () => {
    fetchMock.mockResolvedValue(invalidJsonResponse(500));

    await expect(apiGet("/boom")).rejects.toThrow("GET /boom failed with status 500");
  });

  it("throws ApiError, carrying the status for callers to branch on", async () => {
    fetchMock.mockResolvedValue(invalidJsonResponse(503));

    await expect(apiGet("/x")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("apiPost", () => {
  it("sends a JSON body with a Content-Type when one is given", async () => {
    fetchMock.mockResolvedValue(jsonResponse(201, { id: "p1" }));

    await apiPost("/projects", { name: "demo" });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(init.body).toBe(JSON.stringify({ name: "demo" }));
  });

  it("sends no body or Content-Type for the body-less pipeline endpoints", async () => {
    fetchMock.mockResolvedValue(jsonResponse(201, { repository_id: "r1" }));

    await apiPost("/parse");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
    expect(init.headers).toBeUndefined();
  });
});

describe("apiPostForm", () => {
  it("passes FormData through without setting Content-Type, so the browser sets the boundary", async () => {
    fetchMock.mockResolvedValue(jsonResponse(201, { id: "r1" }));
    const form = new FormData();
    form.append("file", new File(["x"], "repo.zip"));

    await apiPostForm("/import/zip", form);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBe(form);
    expect(init.headers).toBeUndefined();
  });
});
