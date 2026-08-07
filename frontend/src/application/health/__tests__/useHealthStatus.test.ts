import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useHealthStatus } from "@/application/health/useHealthStatus";
import * as healthApi from "@/infrastructure/api/healthApi";

describe("useHealthStatus", () => {
  it("exposes the fetched status once loading completes", async () => {
    vi.spyOn(healthApi, "fetchHealth").mockResolvedValue({
      state: "ok",
      appName: "Forge",
      version: "0.1.0",
    });

    const { result } = renderHook(() => useHealthStatus());

    expect(result.current.isLoading).toBe(true);

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.status).toEqual({ state: "ok", appName: "Forge", version: "0.1.0" });
    expect(result.current.error).toBeNull();
  });

  it("exposes an error message when the fetch fails", async () => {
    vi.spyOn(healthApi, "fetchHealth").mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useHealthStatus());

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.status).toBeNull();
    expect(result.current.error).toBe("network down");
  });
});
