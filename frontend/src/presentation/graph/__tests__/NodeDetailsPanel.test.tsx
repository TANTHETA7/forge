import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AsyncDataState } from "@/application/shared/useAsyncData";
import type {
  FileGraphNode,
  GraphNeighbor,
  GraphNode,
  RepositoryGraphNode,
  SymbolGraphNode,
} from "@/domain/graph/types";
import { NodeDetailsPanel } from "@/presentation/graph/NodeDetailsPanel";

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

const REPO_NODE: RepositoryGraphNode = {
  id: "n-repo",
  kind: "repository",
  repositoryId: "r1",
  displayName: "graphrepo",
  projectId: "p1",
  projectedAt: "2026-08-21T17:54:26Z",
};

const FILE_NODE: FileGraphNode = {
  id: "n-file",
  kind: "file",
  repositoryId: "r1",
  path: "pkg/broken.py",
  language: "python",
  hasSyntaxErrors: true,
};

const SYMBOL_NODE: SymbolGraphNode = {
  id: "n-sym",
  kind: "symbol",
  repositoryId: "r1",
  name: "speak",
  qualifiedName: "pkg.dog.Dog.speak",
  symbolKind: "method",
  fileId: "f1",
  startLine: 4,
  endLine: 5,
};

const NEIGHBORS: GraphNeighbor[] = [
  { node: REPO_NODE, relationshipKind: "contains", direction: "incoming" },
  { node: SYMBOL_NODE, relationshipKind: "defines", direction: "outgoing" },
];

function renderPanel(
  node: GraphNode | null,
  neighbors: AsyncDataState<GraphNeighbor[]> = idle(),
  onSelectNode = () => {},
) {
  return render(
    <NodeDetailsPanel node={node} neighbors={neighbors} onSelectNode={onSelectNode} />,
  );
}

describe("NodeDetailsPanel selection state", () => {
  /** Detail values live in <dd>; the node's label also appears as the heading. */
  const fact = (text: string | RegExp) => screen.getByText(text, { selector: "dd" });
  const heading = () => screen.getByRole("heading", { level: 4 });

  it("prompts for a selection when no node is selected", () => {
    renderPanel(null);
    expect(screen.getByText(/Select a node in the graph/)).toBeInTheDocument();
  });

  it("shows a repository node's fields", () => {
    renderPanel(REPO_NODE, ready([]));

    expect(heading()).toHaveTextContent("graphrepo");
    expect(fact("graphrepo")).toBeInTheDocument();
    expect(fact("p1")).toBeInTheDocument();
    expect(fact("n-repo")).toBeInTheDocument();
  });

  it("shows a file node's path, language, and syntax-error flag", () => {
    renderPanel(FILE_NODE, ready([]));

    expect(heading()).toHaveTextContent("pkg/broken.py");
    expect(fact("pkg/broken.py")).toBeInTheDocument();
    expect(fact("python")).toBeInTheDocument();
    expect(fact("yes")).toBeInTheDocument();
  });

  it("shows a symbol node's qualified name, kind, and line range", () => {
    renderPanel(SYMBOL_NODE, ready([]));

    expect(fact("pkg.dog.Dog.speak")).toBeInTheDocument();
    expect(fact("method")).toBeInTheDocument();
    expect(fact("L4–5")).toBeInTheDocument();
    expect(fact("f1")).toBeInTheDocument();
  });

  it("labels an unrecognized node kind instead of guessing", () => {
    renderPanel({ id: "n-x", kind: "unknown", repositoryId: "r1", rawKind: "package" }, ready([]));

    expect(fact("package")).toBeInTheDocument();
    expect(screen.getByText(/Unrecognized kind/i)).toBeInTheDocument();
  });
});

describe("NodeDetailsPanel neighbours", () => {
  it("shows a loading state while neighbours are being fetched", () => {
    renderPanel(FILE_NODE, loading());
    expect(screen.getByText(/Loading neighbours/)).toBeInTheDocument();
  });

  it("states plainly when a node has no neighbours", () => {
    renderPanel(SYMBOL_NODE, ready([]));
    expect(screen.getByText(/has no neighbours/)).toBeInTheDocument();
  });

  it("shows an error when the neighbours request fails", () => {
    renderPanel(FILE_NODE, failed("neighbors failed"));
    expect(screen.getByRole("alert")).toHaveTextContent("neighbors failed");
  });

  it("renders each neighbour with its relationship kind and direction", () => {
    renderPanel(FILE_NODE, ready(NEIGHBORS));

    const incoming = screen.getByRole("button", { name: /graphrepo/ });
    expect(incoming).toHaveTextContent("contains");
    expect(incoming).toHaveTextContent("←");

    const outgoing = screen.getByRole("button", { name: /speak/ });
    expect(outgoing).toHaveTextContent("defines");
    expect(outgoing).toHaveTextContent("→");
  });

  it("reports the clicked neighbour so it becomes the selected node", () => {
    const onSelectNode = vi.fn();
    renderPanel(FILE_NODE, ready(NEIGHBORS), onSelectNode);

    screen.getByRole("button", { name: /speak/ }).click();

    expect(onSelectNode).toHaveBeenCalledWith(SYMBOL_NODE);
  });

  it("keys neighbours so the same node via two relationships both render", () => {
    const twice: GraphNeighbor[] = [
      { node: SYMBOL_NODE, relationshipKind: "defines", direction: "outgoing" },
      { node: SYMBOL_NODE, relationshipKind: "calls", direction: "outgoing" },
    ];
    renderPanel(FILE_NODE, ready(twice));

    expect(screen.getAllByRole("button", { name: /speak/ })).toHaveLength(2);
  });
});
