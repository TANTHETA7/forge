import { useEffect, useMemo, useState } from "react";
import { useWorkspace } from "@/presentation/workspace/WorkspaceContext";
import { useAsyncAction } from "@/application/shared/useAsyncAction";
import { fetchNodeImpact } from "@/infrastructure/api/graphApi";
import {
  DEFAULT_IMPACT_DEPTH,
  MAX_IMPACT_DEPTH,
  MIN_DEPTH,
} from "@/application/graph/useRepositoryGraph";
import { graphNodeLabel, type GraphNode, type ImpactDirection } from "@/domain/graph/types";

interface ImpactWorkspaceProps {
  projectId: string | null;
  repositoryId: string | null;
  enabled: boolean;
  graphNodes: GraphNode[];
}

export function ImpactWorkspace({
  projectId,
  repositoryId,
  enabled,
  graphNodes,
}: ImpactWorkspaceProps) {
  const {
    impactTargetNode,
    selectedNode,
    navigateToGraph,
    navigateToExplorer,
    navigateToIntelligence,
  } = useWorkspace();

  const [userSelectedTarget, setUserSelectedTarget] = useState<GraphNode | null>(null);
  const currentTarget = userSelectedTarget ?? impactTargetNode ?? selectedNode ?? null;

  const [direction, setDirection] = useState<ImpactDirection>("downstream");
  const [depth, setDepth] = useState<number>(DEFAULT_IMPACT_DEPTH);
  const [targetSearch, setTargetSearch] = useState("");

  // Execute impact analysis via API
  const impactAction = useAsyncAction(async () => {
    if (!projectId || !repositoryId || !currentTarget) {
      throw new Error("Select a target node before running impact analysis");
    }
    return fetchNodeImpact(projectId, repositoryId, currentTarget.id, {
      direction,
      depth,
      limit: 150,
    });
  });

  const { data: impactResult, isPending, error, run, reset } = impactAction;

  // Auto-run if a target was pre-selected when arriving at this workspace
  useEffect(() => {
    if (currentTarget && !impactResult && !isPending && !error) {
      void run();
    }
  }, [currentTarget, impactResult, isPending, error, run]);

  // Group impacted nodes into Direct (depth === 1) and Indirect (depth > 1)
  const { directNodes, indirectNodes } = useMemo(() => {
    if (!impactResult) return { directNodes: [], indirectNodes: [] };

    const direct = impactResult.impactedNodes.filter((item) => item.depth === 1);
    const indirect = impactResult.impactedNodes.filter((item) => item.depth > 1);

    return { directNodes: direct, indirectNodes: indirect };
  }, [impactResult]);

  // Filter candidate nodes for the target selector
  const candidateNodes = useMemo(() => {
    if (!targetSearch.trim()) return graphNodes.slice(0, 30);
    const q = targetSearch.toLowerCase().trim();
    return graphNodes
      .filter((n) => graphNodeLabel(n).toLowerCase().includes(q))
      .slice(0, 30);
  }, [graphNodes, targetSearch]);

  if (!enabled) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-forge-text-muted">
        <div>
          <p className="text-sm font-medium text-forge-text-secondary">
            Impact Analysis is locked
          </p>
          <p className="mt-1 text-xs">
            Run the graph projection stage first to build the Neo4j dependency network.
          </p>
        </div>
      </div>
    );
  }

  const targetLabel = currentTarget ? graphNodeLabel(currentTarget) : "None selected";

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      {/* Workspace Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-forge-border pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-amber-400" />
            <h1 className="text-lg font-bold text-forge-text-primary">
              Change Impact Analysis
            </h1>
          </div>
          <p className="text-xs text-forge-text-muted mt-0.5">
            Trace downstream blast radius and upstream dependency requirements via Neo4j
          </p>
        </div>

        {currentTarget && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => navigateToGraph(currentTarget)}
              className="rounded-lg border border-forge-border bg-forge-elevated px-3 py-1.5 text-xs text-forge-text-secondary hover:text-forge-text-primary transition"
            >
              View in Graph →
            </button>
            <button
              type="button"
              onClick={() =>
                navigateToIntelligence(
                  `What are the direct and indirect consequences if ${targetLabel} is modified or deleted?`,
                )
              }
              className="rounded-lg bg-forge-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-forge-accent-hover transition"
            >
              Ask Forge AI
            </button>
          </div>
        )}
      </div>

      {/* Control Card: Target, Direction, Depth */}
      <div className="rounded-xl border border-forge-border bg-forge-card p-5 space-y-4 shadow-sm">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {/* Target Selector */}
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-forge-text-muted">
              Target Component / Symbol
            </label>
            <div className="relative">
              <input
                type="text"
                value={targetSearch || (currentTarget ? targetLabel : "")}
                onChange={(e) => setTargetSearch(e.target.value)}
                placeholder="Search symbol or file…"
                className="w-full rounded-md border border-forge-border bg-forge-panel px-3 py-1.5 text-xs font-mono text-forge-text-primary placeholder-forge-text-muted focus:border-forge-accent focus:outline-none"
              />
              {targetSearch.trim() && candidateNodes.length > 0 && (
                <div className="absolute top-full left-0 right-0 z-30 mt-1 max-h-48 overflow-y-auto rounded-lg border border-forge-border bg-forge-elevated p-1 shadow-2xl">
                  {candidateNodes.map((n) => (
                    <button
                      key={n.id}
                      type="button"
                      onClick={() => {
                        setUserSelectedTarget(n);
                        setTargetSearch("");
                        reset();
                      }}
                      className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs hover:bg-forge-panel"
                    >
                      <span className="font-mono truncate">{graphNodeLabel(n)}</span>
                      <span className="text-[10px] text-forge-text-muted uppercase">
                        {n.kind}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Direction Toggle */}
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-forge-text-muted">
              Traversal Direction
            </label>
            <div
              className="flex rounded-md border border-forge-border bg-forge-panel p-0.5"
              role="group"
              aria-label="Impact direction"
            >
              <button
                type="button"
                onClick={() => {
                  setDirection("downstream");
                  reset();
                }}
                className={`flex-1 rounded py-1 text-xs font-medium transition ${
                  direction === "downstream"
                    ? "bg-forge-accent text-white shadow-sm"
                    : "text-forge-text-muted hover:text-forge-text-primary"
                }`}
              >
                Downstream (Blast Radius)
              </button>
              <button
                type="button"
                onClick={() => {
                  setDirection("upstream");
                  reset();
                }}
                className={`flex-1 rounded py-1 text-xs font-medium transition ${
                  direction === "upstream"
                    ? "bg-forge-accent text-white shadow-sm"
                    : "text-forge-text-muted hover:text-forge-text-primary"
                }`}
              >
                Upstream (Dependencies)
              </button>
            </div>
          </div>

          {/* Depth Slider */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label
                htmlFor="impact-depth-slider"
                className="text-xs font-semibold uppercase tracking-wider text-forge-text-muted"
              >
                Max Depth: {depth} hops
              </label>
            </div>
            <div className="flex items-center gap-3">
              <input
                id="impact-depth-slider"
                type="range"
                min={MIN_DEPTH}
                max={MAX_IMPACT_DEPTH}
                value={depth}
                onChange={(e) => {
                  setDepth(Number(e.target.value));
                  reset();
                }}
                className="flex-1 accent-forge-accent cursor-pointer"
              />
              <button
                type="button"
                onClick={() => void run()}
                disabled={isPending || !currentTarget}
                className="rounded-md bg-forge-accent px-4 py-1.5 text-xs font-medium text-white hover:bg-forge-accent-hover transition disabled:opacity-40"
              >
                {isPending ? "Traversing…" : "Analyze"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Analysis Results Display */}
      {error && (
        <div role="alert" className="p-4 rounded-xl border border-red-900 bg-red-950/40 text-xs text-red-300">
          {error}
        </div>
      )}

      {isPending && (
        <div className="rounded-xl border border-forge-border bg-forge-card p-12 text-center text-xs text-forge-text-muted">
          <div className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-forge-accent border-t-transparent mb-3" />
          <p>Traversing Neo4j dependency network up to depth {depth}…</p>
        </div>
      )}

      {impactResult && (
        <div className="space-y-6">
          {/* Summary Banner */}
          <div className="rounded-xl border border-forge-border bg-forge-card p-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <span className="text-[10px] uppercase font-semibold text-forge-accent tracking-wider">
                  Target Root
                </span>
                <div className="text-base font-bold font-mono text-forge-text-primary">
                  {targetLabel}
                </div>
              </div>

              <div className="flex items-center gap-6 font-mono text-xs">
                <div>
                  <span className="text-forge-text-muted block text-[10px] uppercase">
                    Affected Components
                  </span>
                  <span className="text-lg font-bold text-forge-text-primary">
                    {impactResult.impactedNodes.length}
                  </span>
                </div>
                <div>
                  <span className="text-forge-text-muted block text-[10px] uppercase">
                    Max Depth
                  </span>
                  <span className="text-lg font-bold text-forge-text-primary">
                    {impactResult.maxDepth}
                  </span>
                </div>
                <div>
                  <span className="text-forge-text-muted block text-[10px] uppercase">
                    Direction
                  </span>
                  <span className="text-lg font-bold text-amber-400 capitalize">
                    {impactResult.direction}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {impactResult.impactedNodes.length === 0 ? (
            <div className="rounded-xl border border-forge-border bg-forge-card p-8 text-center text-xs text-forge-text-muted">
              Nothing is impacted {impactResult.direction} from this node within depth {impactResult.maxDepth}.
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              {/* Direct Affected Components (Depth 1) */}
              <div className="rounded-xl border border-forge-border bg-forge-card p-4 space-y-3">
                <div className="flex items-center justify-between border-b border-forge-border pb-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-forge-text-primary">
                    Direct Impact (Depth 1)
                  </h3>
                  <span className="rounded bg-forge-elevated border border-forge-border px-1.5 py-0.5 font-mono text-[10px] text-forge-text-secondary">
                    {directNodes.length} components
                  </span>
                </div>

                {directNodes.length === 0 ? (
                  <p className="text-xs text-forge-text-muted py-2">
                    No direct depth-1 relationships found.
                  </p>
                ) : (
                  <ul className="space-y-1.5 max-h-80 overflow-y-auto">
                    {directNodes.map((item, idx) => (
                      <li
                        key={`${item.node.id}:${idx}`}
                        className="flex items-center justify-between rounded-lg border border-forge-border bg-forge-panel p-2.5 text-xs hover:border-neutral-700 transition"
                      >
                        <div className="min-w-0 flex-1 pr-2">
                          <div className="font-mono font-medium text-forge-text-primary truncate">
                            {graphNodeLabel(item.node)}
                          </div>
                          <div className="text-[10px] text-forge-text-muted">
                            via <strong className="text-forge-accent">{item.relationshipKind}</strong> · {item.node.kind}
                          </div>
                        </div>

                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => navigateToGraph(item.node)}
                            className="rounded border border-forge-border bg-forge-elevated px-2 py-0.5 text-[10px] text-forge-text-secondary hover:text-forge-text-primary"
                          >
                            Graph
                          </button>
                          {item.node.kind === "file" && (
                            <button
                              type="button"
                              onClick={() => {
                                if (item.node.kind === "file") {
                                  navigateToExplorer(item.node.path);
                                }
                              }}
                              className="rounded border border-forge-border bg-forge-elevated px-2 py-0.5 text-[10px] text-forge-text-secondary hover:text-forge-text-primary"
                            >
                              Code
                            </button>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Indirect Affected Components (Depth 2+) */}
              <div className="rounded-xl border border-forge-border bg-forge-card p-4 space-y-3">
                <div className="flex items-center justify-between border-b border-forge-border pb-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-forge-text-primary">
                    Indirect Impact (Depth 2+)
                  </h3>
                  <span className="rounded bg-forge-elevated border border-forge-border px-1.5 py-0.5 font-mono text-[10px] text-forge-text-secondary">
                    {indirectNodes.length} components
                  </span>
                </div>

                {indirectNodes.length === 0 ? (
                  <p className="text-xs text-forge-text-muted py-2">
                    No multi-hop downstream dependencies.
                  </p>
                ) : (
                  <ul className="space-y-1.5 max-h-80 overflow-y-auto">
                    {indirectNodes.map((item, idx) => (
                      <li
                        key={`${item.node.id}:${idx}`}
                        className="flex items-center justify-between rounded-lg border border-forge-border bg-forge-panel p-2.5 text-xs hover:border-neutral-700 transition"
                      >
                        <div className="min-w-0 flex-1 pr-2">
                          <div className="font-mono font-medium text-forge-text-primary truncate">
                            {graphNodeLabel(item.node)}
                          </div>
                          <div className="text-[10px] text-forge-text-muted">
                            depth <strong className="text-purple-400">{item.depth}</strong> · via {item.relationshipKind}
                          </div>
                        </div>

                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => navigateToGraph(item.node)}
                            className="rounded border border-forge-border bg-forge-elevated px-2 py-0.5 text-[10px] text-forge-text-secondary hover:text-forge-text-primary"
                          >
                            Graph
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
