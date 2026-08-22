import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  SYMBOL_PAGE_SIZE,
  useRepositoryExplorer,
} from "@/application/explorer/useRepositoryExplorer";
import * as explorerApi from "@/infrastructure/api/explorerApi";
import type { CodeSymbol, ParseError, ParsedFile } from "@/domain/explorer/types";

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
const REPO_ID = "22222222-2222-2222-2222-222222222222";

const FILE: ParsedFile = {
  id: "f1",
  repositoryId: REPO_ID,
  path: "pkg/dog.py",
  language: "Python",
  hasSyntaxErrors: false,
  symbolCount: 2,
  importCount: 1,
};

function symbol(id: string, name: string, kind = "function"): CodeSymbol {
  return {
    id,
    kind,
    name,
    qualifiedName: `pkg.dog.${name}`,
    startLine: 1,
    endLine: 2,
    startColumn: 0,
    endColumn: 4,
    parameters: [],
    parentSymbolId: null,
  };
}

const PARSE_ERROR: ParseError = {
  filePath: "pkg/broken.py",
  stage: "parse",
  message: "unexpected token",
};

/** A full page, which is the only signal that another page may exist. */
const fullPage = () =>
  Array.from({ length: SYMBOL_PAGE_SIZE }, (_, i) => symbol(`s${i}`, `sym${i}`));

function render(enabled = true, projectId: string | null = PROJECT_ID) {
  return renderHook(() => useRepositoryExplorer(projectId, REPO_ID, enabled));
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(explorerApi, "fetchFiles").mockResolvedValue([FILE]);
  vi.spyOn(explorerApi, "fetchSymbols").mockResolvedValue([symbol("s1", "bark")]);
  vi.spyOn(explorerApi, "fetchParseErrors").mockResolvedValue([]);
  vi.spyOn(explorerApi, "fetchSymbol").mockResolvedValue(symbol("s1", "bark"));
});

describe("useRepositoryExplorer request budget", () => {
  it("opens with exactly three requests and none per row", async () => {
    const { result } = render();

    await waitFor(() => expect(result.current.files.data).toEqual([FILE]));
    await waitFor(() => expect(result.current.symbols.isLoading).toBe(false));
    await waitFor(() => expect(result.current.parseErrors.isLoading).toBe(false));

    expect(explorerApi.fetchFiles).toHaveBeenCalledTimes(1);
    expect(explorerApi.fetchSymbols).toHaveBeenCalledTimes(1);
    expect(explorerApi.fetchParseErrors).toHaveBeenCalledTimes(1);
    // The N+1 guard: no per-symbol detail request without a selection.
    expect(explorerApi.fetchSymbol).not.toHaveBeenCalled();
  });

  it("does not re-fetch when nothing relevant changed", async () => {
    const { result, rerender } = render();
    await waitFor(() => expect(result.current.files.data).toEqual([FILE]));

    rerender();
    rerender();

    expect(explorerApi.fetchFiles).toHaveBeenCalledTimes(1);
    expect(explorerApi.fetchSymbols).toHaveBeenCalledTimes(1);
  });
});

describe("useRepositoryExplorer repository scoping", () => {
  it("issues no requests while disabled", async () => {
    const { result } = render(false);

    await waitFor(() => expect(result.current.files.isLoading).toBe(false));

    expect(explorerApi.fetchFiles).not.toHaveBeenCalled();
    expect(explorerApi.fetchSymbols).not.toHaveBeenCalled();
    expect(explorerApi.fetchParseErrors).not.toHaveBeenCalled();
    expect(result.current.files.data).toBeNull();
  });

  it("issues no requests when no project is selected", async () => {
    const { result } = render(true, null);

    await waitFor(() => expect(result.current.files.isLoading).toBe(false));
    expect(explorerApi.fetchFiles).not.toHaveBeenCalled();
  });

  it("scopes every request to the given project and repository", async () => {
    const { result } = render();
    await waitFor(() => expect(result.current.files.data).toEqual([FILE]));

    act(() => result.current.selectSymbol("s1"));
    await waitFor(() => expect(result.current.selectedSymbol.data).not.toBeNull());

    expect(explorerApi.fetchFiles).toHaveBeenCalledWith(PROJECT_ID, REPO_ID);
    expect(explorerApi.fetchParseErrors).toHaveBeenCalledWith(PROJECT_ID, REPO_ID);
    expect(explorerApi.fetchSymbols).toHaveBeenCalledWith(
      PROJECT_ID,
      REPO_ID,
      expect.objectContaining({ limit: SYMBOL_PAGE_SIZE }),
    );
    expect(explorerApi.fetchSymbol).toHaveBeenCalledWith(PROJECT_ID, REPO_ID, "s1");
  });
});

describe("useRepositoryExplorer symbol filtering", () => {
  it("sends no kind parameter while the filter is 'all'", async () => {
    const { result } = render();
    await waitFor(() => expect(result.current.symbols.isLoading).toBe(false));

    expect(explorerApi.fetchSymbols).toHaveBeenLastCalledWith(PROJECT_ID, REPO_ID, {
      limit: SYMBOL_PAGE_SIZE,
      offset: 0,
    });
  });

  it("sends kind only for a real SymbolKind", async () => {
    const { result } = render();
    await waitFor(() => expect(result.current.symbols.isLoading).toBe(false));

    act(() => result.current.setKindFilter("class"));
    await waitFor(() =>
      expect(explorerApi.fetchSymbols).toHaveBeenLastCalledWith(PROJECT_ID, REPO_ID, {
        kind: "class",
        limit: SYMBOL_PAGE_SIZE,
        offset: 0,
      }),
    );
  });

  it("sends file_id when a file is selected", async () => {
    const { result } = render();
    await waitFor(() => expect(result.current.symbols.isLoading).toBe(false));

    act(() => result.current.setFileFilter("f1"));
    await waitFor(() =>
      expect(explorerApi.fetchSymbols).toHaveBeenLastCalledWith(PROJECT_ID, REPO_ID, {
        fileId: "f1",
        limit: SYMBOL_PAGE_SIZE,
        offset: 0,
      }),
    );
  });
});

describe("useRepositoryExplorer pagination", () => {
  it("advances the offset by the page size", async () => {
    vi.spyOn(explorerApi, "fetchSymbols").mockResolvedValue(fullPage());
    const { result } = render();
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));

    act(() => result.current.nextPage());
    await waitFor(() =>
      expect(explorerApi.fetchSymbols).toHaveBeenLastCalledWith(
        PROJECT_ID,
        REPO_ID,
        expect.objectContaining({ offset: SYMBOL_PAGE_SIZE }),
      ),
    );
    expect(result.current.page).toBe(1);
  });

  it("reports no next page when the page is not full", async () => {
    const { result } = render();
    await waitFor(() => expect(result.current.symbols.isLoading).toBe(false));

    expect(result.current.hasNextPage).toBe(false);
  });

  it("never pages below zero", async () => {
    const { result } = render();
    await waitFor(() => expect(result.current.symbols.isLoading).toBe(false));

    act(() => result.current.previousPage());
    expect(result.current.page).toBe(0);
  });

  it("restarts paging when a filter changes, so the offset cannot go stale", async () => {
    vi.spyOn(explorerApi, "fetchSymbols").mockResolvedValue(fullPage());
    const { result } = render();
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));

    act(() => result.current.nextPage());
    await waitFor(() => expect(result.current.page).toBe(1));

    act(() => result.current.setKindFilter("method"));
    await waitFor(() => expect(result.current.page).toBe(0));
    expect(explorerApi.fetchSymbols).toHaveBeenLastCalledWith(PROJECT_ID, REPO_ID, {
      kind: "method",
      limit: SYMBOL_PAGE_SIZE,
      offset: 0,
    });
  });
});

describe("useRepositoryExplorer symbol details", () => {
  it("fetches details only once a symbol is selected", async () => {
    const detail = symbol("s1", "bark");
    vi.spyOn(explorerApi, "fetchSymbol").mockResolvedValue(detail);
    const { result } = render();
    await waitFor(() => expect(result.current.symbols.isLoading).toBe(false));
    expect(explorerApi.fetchSymbol).not.toHaveBeenCalled();

    act(() => result.current.selectSymbol("s1"));

    await waitFor(() => expect(result.current.selectedSymbol.data).toEqual(detail));
    expect(explorerApi.fetchSymbol).toHaveBeenCalledTimes(1);
  });

  it("surfaces a not-found error from the details request", async () => {
    vi.spyOn(explorerApi, "fetchSymbol").mockRejectedValue(new Error("Symbol s9 not found"));
    const { result } = render();
    await waitFor(() => expect(result.current.symbols.isLoading).toBe(false));

    act(() => result.current.selectSymbol("s9"));

    await waitFor(() => expect(result.current.selectedSymbol.error).toBe("Symbol s9 not found"));
    expect(result.current.selectedSymbol.data).toBeNull();
  });
});

describe("useRepositoryExplorer failure handling", () => {
  it("keeps the panels independent when one read fails", async () => {
    vi.spyOn(explorerApi, "fetchFiles").mockRejectedValue(new Error("files exploded"));
    vi.spyOn(explorerApi, "fetchParseErrors").mockResolvedValue([PARSE_ERROR]);
    const { result } = render();

    await waitFor(() => expect(result.current.files.error).toBe("files exploded"));
    await waitFor(() => expect(result.current.parseErrors.data).toEqual([PARSE_ERROR]));
    expect(result.current.symbols.error).toBeNull();
  });
});
