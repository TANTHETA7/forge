import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AsyncActionState } from "@/application/shared/useAsyncAction";
import type { AsyncDataState } from "@/application/shared/useAsyncData";
import type {
  DependencyPath,
  FileGraphNode,
  GraphInsights,
  GraphNeighbor,
  ImpactAnalysis,
  SymbolGraphNode,
} from "@/domain/graph/types";
import { GraphInsightsPanel } from "@/presentation/graph/GraphInsightsPanel";
import { ImpactSection } from "@/presentation/graph/ImpactSection";
import { NeighborList } from "@/presentation/graph/NeighborList";
import { PathSection } from "@/presentation/graph/PathSection";

// --- async state builders -------------------------------------------------
function dataLoading<T>(): AsyncDataState<T> {
  return { data: null, isLoading: true, error: null };
}
function dataFailed<T>(message: string): AsyncDataState<T> {
  return { data: null, isLoading: false, error: message };
}
function dataReady<T>(data: T): AsyncDataState<T> {
  return { data, isLoading: false, error: null };
}
function actionIdle<T>(): AsyncActionState<T> {
  return { data: null, isPending: false, error: null };
}
function actionPending<T>(): AsyncActionState<T> {
  return { data: null, isPending: true, error: null };
}
function actionFailed<T>(message: string): AsyncActionState<T> {
  return { data: null, isPending: false, error: message };
}
function actionReady<T>(data: T): AsyncActionState<T> {
  return { data, isPending: false, error: null };
}

// --- fixtures -------------------------------------------------------------
const fileA: FileGraphNode = {
  id: "n-file-a",
  kind: "file",
  repositoryId: "r",
  path: "pkg/a.py",
  language: "python",
  hasSyntaxErrors: false,
};
const fileB: FileGraphNode = { ...fileA, id: "n-file-b", path: "pkg/b.py" };
const symbolNode: SymbolGraphNode = {
  id: "n-sym",
  kind: "symbol",
  repositoryId: "r",
  name: "bark",
  qualifiedName: "pkg.a.bark",
  symbolKind: "function",
  fileId: "n-file-a",
  startLine: 1,
  endLine: 2,
};

const NEIGHBORS: GraphNeighbor[] = [
  { node: fileB, relationshipKind: "imports", direction: "outgoing" },
];

const noop = () => {};

// --- NeighborList (shared by neighbours, dependencies, dependents) --------
describe("NeighborList", () => {
  const renderList = (state: AsyncDataState<GraphNeighbor[]>, onSelectNode = noop) =>
    render(
      <NeighborList
        state={state}
        loadingMessage="Loading dependencies…"
        emptyMessage="This node depends on nothing in the projected graph."
        onSelectNode={onSelectNode}
      />,
    );

  it("shows a loading state", () => {
    renderList(dataLoading());
    expect(screen.getByText(/Loading dependencies/)).toBeInTheDocument();
  });

  it("shows the caller's empty message", () => {
    renderList(dataReady([]));
    expect(screen.getByText(/depends on nothing/)).toBeInTheDocument();
  });

  it("shows an error state", () => {
    renderList(dataFailed("deps failed"));
    expect(screen.getByRole("alert")).toHaveTextContent("deps failed");
  });

  it("renders relationship kind, direction, and node label", () => {
    renderList(dataReady(NEIGHBORS));
    const row = screen.getByRole("button", { name: /pkg\/b\.py/ });
    expect(row).toHaveTextContent("imports");
    expect(row).toHaveTextContent("→");
  });

  it("reports the clicked node", () => {
    const onSelectNode = vi.fn();
    renderList(dataReady(NEIGHBORS), onSelectNode);
    screen.getByRole("button", { name: /pkg\/b\.py/ }).click();
    expect(onSelectNode).toHaveBeenCalledWith(fileB);
  });

  it("renders the same node twice when it arrives under two relationship kinds", () => {
    renderList(
      dataReady([
        { node: fileB, relationshipKind: "imports", direction: "outgoing" },
        { node: fileB, relationshipKind: "calls", direction: "outgoing" },
      ]),
    );
    expect(screen.getAllByRole("button", { name: /pkg\/b\.py/ })).toHaveLength(2);
  });
});

// --- ImpactSection --------------------------------------------------------
describe("ImpactSection", () => {
  const IMPACT: ImpactAnalysis = {
    startingNodeId: fileA.id,
    direction: "downstream",
    maxDepth: 3,
    impactedNodes: [
      { node: fileB, depth: 1, relationshipKind: "imports" },
      { node: symbolNode, depth: 2, relationshipKind: "calls" },
    ],
  };

  const renderImpact = (
    state: AsyncActionState<ImpactAnalysis>,
    overrides: Partial<Parameters<typeof ImpactSection>[0]> = {},
  ) =>
    render(
      <ImpactSection
        state={state}
        direction="upstream"
        onDirectionChange={noop}
        depth={3}
        onDepthChange={noop}
        maxDepth={10}
        onRun={noop}
        onSelectNode={noop}
        {...overrides}
      />,
    );

  it("offers only the two directions the backend accepts", () => {
    renderImpact(actionIdle());
    const group = screen.getByRole("group", { name: "Impact direction" });
    expect(group.children).toHaveLength(2);
    expect(screen.getByRole("button", { name: "upstream" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "downstream" })).toBeInTheDocument();
  });

  it("bounds the depth input to the accepted range", () => {
    renderImpact(actionIdle());
    const input = screen.getByLabelText(/Depth/);
    expect(input).toHaveAttribute("min", "1");
    expect(input).toHaveAttribute("max", "10");
  });

  it("prompts before anything has been run", () => {
    renderImpact(actionIdle());
    expect(screen.getByText(/then run the analysis/)).toBeInTheDocument();
  });

  it("shows a real pending state, with no fabricated percentage", () => {
    renderImpact(actionPending());
    expect(screen.getByText(/Traversing the graph/)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("shows an error state", () => {
    renderImpact(actionFailed("traversal exploded"));
    expect(screen.getByRole("alert")).toHaveTextContent("traversal exploded");
  });

  it("renders the backend's direction, depth, and impacted nodes with their depths", () => {
    renderImpact(actionReady(IMPACT));

    expect(screen.getByText(/downstream · max depth 3 · 2 impacted nodes/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /pkg\/b\.py/ })).toHaveTextContent("depth 1");
    expect(screen.getByRole("button", { name: /bark/ })).toHaveTextContent("depth 2");
  });

  it("states plainly when nothing is impacted", () => {
    renderImpact(actionReady({ ...IMPACT, impactedNodes: [] }));
    expect(screen.getByText(/Nothing is impacted downstream/)).toBeInTheDocument();
  });

  it("runs on request", () => {
    const onRun = vi.fn();
    renderImpact(actionIdle(), { onRun });
    screen.getByRole("button", { name: /Run impact analysis/ }).click();
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it("reports a clicked impacted node", () => {
    const onSelectNode = vi.fn();
    renderImpact(actionReady(IMPACT), { onSelectNode });
    screen.getByRole("button", { name: /bark/ }).click();
    expect(onSelectNode).toHaveBeenCalledWith(symbolNode);
  });
});

// --- PathSection ----------------------------------------------------------
describe("PathSection", () => {
  const FOUND: DependencyPath = {
    sourceId: fileA.id,
    targetId: fileB.id,
    found: true,
    nodes: [fileA, fileB],
    relationships: [
      {
        id: "a->b:imports",
        sourceId: fileA.id,
        targetId: fileB.id,
        kind: "imports",
        dependencyEdgeId: null,
      },
    ],
    length: 1,
  };

  const NOT_FOUND: DependencyPath = {
    sourceId: fileA.id,
    targetId: fileB.id,
    found: false,
    nodes: [],
    relationships: [],
    length: null,
  };

  const renderPath = (
    state: AsyncActionState<DependencyPath>,
    overrides: Partial<Parameters<typeof PathSection>[0]> = {},
  ) =>
    render(
      <PathSection
        state={state}
        source={fileA}
        target={fileB}
        onClearTarget={noop}
        depth={6}
        onDepthChange={noop}
        maxDepth={10}
        canRun
        onRun={noop}
        onSelectNode={noop}
        {...overrides}
      />,
    );

  it("shows both endpoints", () => {
    renderPath(actionIdle());
    expect(screen.getByText("pkg/a.py")).toBeInTheDocument();
    expect(screen.getByText("pkg/b.py")).toBeInTheDocument();
  });

  it("explains what is missing and disables running when there is no target", () => {
    renderPath(actionIdle(), { target: null, canRun: false });

    expect(screen.getByText(/Set as path target/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find path" })).toBeDisabled();
    expect(screen.getByText(/both required/)).toBeInTheDocument();
  });

  it("shows a pending state", () => {
    renderPath(actionPending());
    expect(screen.getByRole("button", { name: /Searching/ })).toBeDisabled();
  });

  it("renders a found path in order, with the relationship between steps", () => {
    renderPath(actionReady(FOUND));

    expect(screen.getByText(/Path found · length 1 hop · 2 nodes/)).toBeInTheDocument();
    const steps = screen.getAllByRole("listitem");
    expect(steps[0]).toHaveTextContent("pkg/a.py");
    expect(steps[0]).toHaveTextContent("imports");
    expect(steps[1]).toHaveTextContent("pkg/b.py");
  });

  it("reports a genuine no-path answer without calling it an error", () => {
    renderPath(actionReady(NOT_FOUND));

    expect(screen.getByText(/No path found within depth 6/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error state", () => {
    renderPath(actionFailed("path exploded"));
    expect(screen.getByRole("alert")).toHaveTextContent("path exploded");
  });

  it("runs on request", () => {
    const onRun = vi.fn();
    renderPath(actionIdle(), { onRun });
    screen.getByRole("button", { name: "Find path" }).click();
    expect(onRun).toHaveBeenCalledTimes(1);
  });
});

// --- GraphInsightsPanel ---------------------------------------------------
describe("GraphInsightsPanel", () => {
  const INSIGHTS: GraphInsights = {
    repositoryId: "r",
    mostConnectedFiles: [{ node: fileA, degree: 7 }],
    dependencyHotspots: [{ node: symbolNode, degree: 4 }],
    isolatedNodes: [fileB],
    mutualImportPairs: [{ fileA, fileB }],
    unresolvedDependencyCount: 2,
    computedAt: "2026-08-22T00:00:00Z",
  };

  const renderInsights = (state: AsyncDataState<GraphInsights>, onSelectNode = noop) =>
    render(<GraphInsightsPanel state={state} onSelectNode={onSelectNode} />);

  it("shows a loading state", () => {
    renderInsights(dataLoading());
    expect(screen.getByText(/Loading insights/)).toBeInTheDocument();
  });

  it("shows an error state", () => {
    renderInsights(dataFailed("insights failed"));
    expect(screen.getByRole("alert")).toHaveTextContent("insights failed");
  });

  it("renders the real counts the backend returned", () => {
    renderInsights(dataReady(INSIGHTS));

    expect(screen.getByText("2")).toBeInTheDocument(); // unresolved dependency count
    expect(screen.getByText("7")).toBeInTheDocument(); // most-connected degree
    expect(screen.getByText("4")).toBeInTheDocument(); // hotspot degree
  });

  it("renders each insight list", () => {
    renderInsights(dataReady(INSIGHTS));

    expect(screen.getByText(/Most connected files/)).toBeInTheDocument();
    expect(screen.getByText(/Dependency hotspots/)).toBeInTheDocument();
    expect(screen.getByText(/Mutual import pairs/)).toBeInTheDocument();
    expect(screen.getByText(/Isolated nodes/)).toBeInTheDocument();
    expect(screen.getAllByText("pkg/a.py").length).toBeGreaterThan(0);
  });

  it("states each empty list separately rather than hiding the section", () => {
    renderInsights(
      dataReady({
        ...INSIGHTS,
        mostConnectedFiles: [],
        dependencyHotspots: [],
        isolatedNodes: [],
        mutualImportPairs: [],
      }),
    );

    expect(screen.getByText(/No file has any import edges/)).toBeInTheDocument();
    expect(screen.getByText(/No symbol is entangled/)).toBeInTheDocument();
    expect(screen.getByText(/No direct circular imports/)).toBeInTheDocument();
    expect(screen.getByText(/Every node has at least one edge/)).toBeInTheDocument();
  });

  it("discloses that the circular-import check is 1-hop only", () => {
    renderInsights(dataReady({ ...INSIGHTS, mutualImportPairs: [] }));
    expect(screen.getByText(/longer cycles are not\s+reported/)).toBeInTheDocument();
  });

  it("reports a clicked insight node", () => {
    const onSelectNode = vi.fn();
    renderInsights(dataReady(INSIGHTS), onSelectNode);

    screen.getByRole("button", { name: /bark/ }).click();
    expect(onSelectNode).toHaveBeenCalledWith(symbolNode);
  });
});
