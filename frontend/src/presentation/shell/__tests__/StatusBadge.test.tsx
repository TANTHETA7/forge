import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StatusBadge } from "@/presentation/shell/StatusBadge";
import * as healthApi from "@/infrastructure/api/healthApi";

describe("StatusBadge", () => {
  it("renders the app name, version, and state once loaded", async () => {
    vi.spyOn(healthApi, "fetchHealth").mockResolvedValue({
      state: "ok",
      appName: "Forge",
      version: "0.1.0",
    });

    render(<StatusBadge />);

    expect(await screen.findByText(/Forge v0\.1\.0 · ok/)).toBeInTheDocument();
  });

  it("renders an unreachable message when the fetch fails", async () => {
    vi.spyOn(healthApi, "fetchHealth").mockRejectedValue(new Error("network down"));

    render(<StatusBadge />);

    expect(await screen.findByText(/Backend unreachable/)).toBeInTheDocument();
  });
});
