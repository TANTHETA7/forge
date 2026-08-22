import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AsyncDataState } from "@/application/shared/useAsyncData";
import type { CodeSymbol, ParseError, ParsedFile } from "@/domain/explorer/types";
import { FileList } from "@/presentation/explorer/FileList";
import { ParseErrorList } from "@/presentation/explorer/ParseErrorList";
import { SymbolDetails } from "@/presentation/explorer/SymbolDetails";
import { SymbolList } from "@/presentation/explorer/SymbolList";

function loading<T>(): AsyncDataState<T> {
  return { data: null, isLoading: true, error: null };
}
function failed<T>(message: string): AsyncDataState<T> {
  return { data: null, isLoading: false, error: message };
}
function ready<T>(data: T): AsyncDataState<T> {
  return { data, isLoading: false, error: null };
}
function idle<T>(): AsyncDataState<T> {
  return { data: null, isLoading: false, error: null };
}

const FILES: ParsedFile[] = [
  {
    id: "f1",
    repositoryId: "r1",
    path: "pkg/dog.py",
    language: "Python",
    hasSyntaxErrors: false,
    symbolCount: 3,
    importCount: 1,
  },
  {
    id: "f2",
    repositoryId: "r1",
    path: "pkg/broken.py",
    language: "Python",
    hasSyntaxErrors: true,
    symbolCount: 0,
    importCount: 0,
  },
];

const SYMBOL: CodeSymbol = {
  id: "s1",
  kind: "method",
  name: "speak",
  qualifiedName: "pkg.dog.Dog.speak",
  startLine: 4,
  endLine: 5,
  startColumn: 4,
  endColumn: 24,
  parameters: [
    { name: "self", position: 0, annotation: null, defaultValue: null },
    { name: "loud", position: 1, annotation: "bool", defaultValue: "False" },
  ],
  parentSymbolId: "s0",
};

const noop = () => {};

function renderFiles(state: AsyncDataState<ParsedFile[]>, onSelectFile = noop) {
  return render(<FileList state={state} selectedFileId={null} onSelectFile={onSelectFile} />);
}

function renderSymbols(state: AsyncDataState<CodeSymbol[]>, overrides = {}) {
  return render(
    <SymbolList
      state={state}
      kindFilter="all"
      onKindChange={noop}
      selectedSymbolId={null}
      onSelectSymbol={noop}
      isFileFiltered={false}
      page={0}
      hasNextPage={false}
      onNextPage={noop}
      onPreviousPage={noop}
      {...overrides}
    />,
  );
}

describe("FileList", () => {
  it("shows a loading state", () => {
    renderFiles(loading());
    expect(screen.getByText(/Loading files/)).toBeInTheDocument();
  });

  it("shows an empty state pointing at the parse stage", () => {
    renderFiles(ready([]));
    expect(screen.getByText(/No parsed files/)).toBeInTheDocument();
  });

  it("shows the backend's error message", () => {
    renderFiles(failed("Repository abc not found"));
    expect(screen.getByRole("alert")).toHaveTextContent("Repository abc not found");
  });

  it("renders the fields the API returns, including the syntax-error state", () => {
    renderFiles(ready(FILES));

    expect(screen.getByText("pkg/dog.py")).toBeInTheDocument();
    expect(screen.getByText("pkg/broken.py")).toBeInTheDocument();
    expect(screen.getAllByText("Python")).toHaveLength(2);
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("errors")).toBeInTheDocument();
    expect(screen.getByText("clean")).toBeInTheDocument();
    expect(screen.getByText(/2 files/)).toBeInTheDocument();
  });

  it("reports the clicked file so symbols can be scoped to it", () => {
    const onSelectFile = vi.fn();
    renderFiles(ready(FILES), onSelectFile);

    screen.getByText("pkg/dog.py").click();

    expect(onSelectFile).toHaveBeenCalledWith("f1");
  });

  it("clears the filter when the selected row is clicked again", () => {
    const onSelectFile = vi.fn();
    render(<FileList state={ready(FILES)} selectedFileId="f1" onSelectFile={onSelectFile} />);

    screen.getByText("pkg/dog.py").click();

    expect(onSelectFile).toHaveBeenCalledWith(null);
  });
});

describe("SymbolList", () => {
  it("offers only the kinds the backend accepts", () => {
    renderSymbols(ready([SYMBOL]));

    ["all", "function", "class", "method"].forEach((kind) => {
      expect(screen.getByRole("button", { name: kind })).toBeInTheDocument();
    });
    // Nothing beyond "all" plus the three real kinds.
    expect(screen.getByRole("group", { name: "Filter by kind" }).children).toHaveLength(4);
  });

  it("shows a loading state", () => {
    renderSymbols(loading());
    expect(screen.getByText(/Loading symbols/)).toBeInTheDocument();
  });

  it("shows an empty state that names the active scope", () => {
    renderSymbols(ready([]), { isFileFiltered: true });
    expect(screen.getByText(/No symbols of this kind in the selected file/)).toBeInTheDocument();
  });

  it("shows an error state", () => {
    renderSymbols(failed("boom"));
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });

  it("renders each symbol's kind, name, and line range", () => {
    renderSymbols(ready([SYMBOL]));

    // Scoped to the row: "method" is also the name of a filter button.
    const row = screen.getByRole("button", { name: /speak/ });
    expect(row).toHaveTextContent("speak");
    expect(row).toHaveTextContent("method");
    expect(row).toHaveTextContent("L4–5");
  });

  it("disables paging controls at the ends", () => {
    renderSymbols(ready([SYMBOL]));

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("enables Next only when another page may exist", () => {
    renderSymbols(ready([SYMBOL]), { hasNextPage: true, page: 1 });

    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
    expect(screen.getByText("page 2")).toBeInTheDocument();
  });

  it("reports the clicked symbol", () => {
    const onSelectSymbol = vi.fn();
    renderSymbols(ready([SYMBOL]), { onSelectSymbol });

    screen.getByText("speak").click();

    expect(onSelectSymbol).toHaveBeenCalledWith("s1");
  });
});

describe("SymbolDetails", () => {
  it("prompts for a selection before anything is chosen", () => {
    render(<SymbolDetails state={idle()} />);
    expect(screen.getByText(/Select a symbol/)).toBeInTheDocument();
  });

  it("shows a loading state", () => {
    render(<SymbolDetails state={loading()} />);
    expect(screen.getByText(/Loading symbol/)).toBeInTheDocument();
  });

  it("shows a not-found error from the API", () => {
    render(<SymbolDetails state={failed("Symbol s9 not found")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Symbol s9 not found");
  });

  it("renders the detail fields and parameters in position order", () => {
    render(<SymbolDetails state={ready(SYMBOL)} />);

    expect(screen.getByText("pkg.dog.Dog.speak")).toBeInTheDocument();
    expect(screen.getByText("L4:4 – L5:24")).toBeInTheDocument();
    expect(screen.getByText("s0")).toBeInTheDocument();
    expect(screen.getByText(/self/)).toBeInTheDocument();
    expect(screen.getByText(/bool/)).toBeInTheDocument();
    expect(screen.getByText(/False/)).toBeInTheDocument();
  });

  it("states plainly when a symbol takes no parameters", () => {
    render(<SymbolDetails state={ready({ ...SYMBOL, parameters: [] })} />);
    expect(screen.getByText("No parameters.")).toBeInTheDocument();
  });
});

describe("ParseErrorList", () => {
  it("states explicitly that there were no parse errors", () => {
    render(<ParseErrorList state={ready([])} />);
    expect(screen.getByText(/No parse errors/)).toBeInTheDocument();
  });

  it("shows each recorded error with its file and stage", () => {
    const errors: ParseError[] = [
      { filePath: "pkg/broken.py", stage: "parse", message: "unexpected token" },
    ];
    render(<ParseErrorList state={ready(errors)} />);

    expect(screen.getByText("pkg/broken.py")).toBeInTheDocument();
    expect(screen.getByText("parse")).toBeInTheDocument();
    expect(screen.getByText("unexpected token")).toBeInTheDocument();
  });

  it("shows an error state when the panel itself fails to load", () => {
    render(<ParseErrorList state={failed("network down")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("network down");
  });
});
