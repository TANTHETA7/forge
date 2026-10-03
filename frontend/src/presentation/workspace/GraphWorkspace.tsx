import { useEffect, useState } from "react";
import { useWorkspace } from "@/presentation/workspace/WorkspaceContext";
import {
  MAX_IMPACT_DEPTH,
  MAX_PATH_DEPTH,
  useRepositoryGraph,
} from "@/application/graph/useRepositoryGraph";
import { GraphCanvas } from "@/presentation/graph/GraphCanvas";
import { NodeIntelligencePanel } from "@/presentation/graph/NodeIntelligencePanel";
import { GraphInsightsPanel } from "@/presentation/graph/GraphInsightsPanel";
import type { GraphNode } from "@/domain/graph/types";

interface GraphWorkspaceProps {
  projectId: string | null;
  repositoryId: string | null;
  enabled: boolean;
  onNodesLoaded?: (nodes: GraphNode[]) => void;
}

export function GraphWorkspace({
  projectId,
  repositoryId,
  enabled,
  onNodesLoaded,
}: GraphWorkspaceProps) {
  const {
    selectedNodeId,
    setSelectedNodeId,
    setSelectedNode: setWorkspaceSelectedNode,
    navigateToExplorer,
    navigateToImpact,
    navigateToIntelligence,
  } = useWorkspace();

  const graphState = useRepositoryGraph(projectId, repositoryId, enabled);
  const {
    graph,
    isLoading,
    error,
    isEmpty,
    isTruncated,
    statistics,
    insights,
    selectedNode,
    selectNode,
  } = graphState;

  const [sidePanelOpen, setSidePanelOpen] = useState(true);

  // Sync workspace node selection into graph state
  useEffect(() => {
    if (selectedNodeId && graph.nodes.length > 0) {
      const match = graph.nodes.find((n) => n.id === selectedNodeId);
      if (match && (!selectedNode || selectedNode.id !== match.id)) {
        selectNode(match);
      }
    }
  }, [selectedNodeId, graph.nodes, selectNode, selectedNode]);

  // Report nodes loaded to parent
  useEffect(() => {
    if (graph.nodes.length > 0 && onNodesLoaded) {
      onNodesLoaded(graph.nodes);
    }
  }, [graph.nodes, onNodesLoaded]);

  const handleSelectNode = (node: GraphNode | null) => {
    selectNode(node);
    setSelectedNodeId(node ? node.id : null);
    setWorkspaceSelectedNode(node);
    if (node) setSidePanelOpen(true);
  };

  if (!enabled) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-forge-text-muted">
        <div>
          <p className="text-sm font-medium text-forge-text-secondary">
            Graph is locked
          </p>
          <p className="mt-1 text-xs">
            Run the graph projection stage first to project AST dependencies into Neo4j.
          </p>
        </div>
      </div>
    );
  }

  const stats = statistics.data;

  return (
    <div className="flex h-[calc(100vh-85px)] overflow-hidden">
      {/* Main Canvas Area */}
      <div className="flex-1 flex flex-col bg-forge-bg overflow-hidden relative">
        {/* Top Graph Statistics Strip */}
        <div className="flex flex-wrap items-center justify-between border-b border-forge-border bg-forge-sidebar/60 px-4 py-2 text-xs">
          <div className="flex items-center gap-3">
            <span className="font-semibold text-forge-text-primary">
              Dependency Graph
            </span>
            {stats && (
              <div className="flex items-center gap-2 font-mono text-[11px] text-forge-text-muted">
                <span>
                  <strong className="text-forge-text-secondary">{stats.totalNodes}</strong>{" "}
                  nodes
                </span>
                <span>·</span>
                <span>
                  <strong className="text-forge-text-secondary">
                    {stats.totalRelationships}
                  </strong>{" "}
                  relationships
                </span>
                <span>·</span>
                <span>{stats.freshness}</span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            {isTruncated && stats && (
              <span className="rounded bg-amber-950/80 border border-amber-800 px-2 py-0.5 font-mono text-[10px] text-amber-300">
                Bounded view ({graph.nodes.length}/{stats.totalNodes})
              </span>
            )}
            <button
              type="button"
              onClick={() => setSidePanelOpen(!sidePanelOpen)}
              className="rounded border border-forge-border bg-forge-elevated px-2 py-0.5 text-xs text-forge-text-muted hover:text-forge-text-primary transition"
            >
              {sidePanelOpen ? "Hide Inspector ⇥" : "Show Inspector ⇤"}
            </button>
          </div>
        </div>

        {/* Graph Canvas */}
        <div className="flex-1 p-3 overflow-hidden flex flex-col justify-between">
          {isLoading && (
            <div className="flex-1 flex flex-col items-center justify-center space-y-4 p-8 animate-fade-in">
              <div className="relative flex items-center justify-center">
                <div className="h-16 w-16 rounded-full border border-forge-accent/20 bg-forge-accent/5 animate-pulse" />
                <svg
                  className="absolute h-8 w-8 animate-spin-slow text-forge-accent"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
              </div>
              <div className="text-center space-y-1">
                <p className="text-xs font-mono font-medium text-forge-text-primary">
                  Loading graph from Neo4j…
                </p>
                <p className="text-[11px] text-forge-text-muted">
                  Resolving AST topology and relationship weights
                </p>
              </div>
              <div className="w-64 space-y-2 pt-2">
                <div className="h-2 w-full rounded skeleton-shimmer" />
                <div className="h-2 w-4/5 mx-auto rounded skeleton-shimmer" />
              </div>
            </div>
          )}

          {error && (
            <div role="alert" className="p-4 rounded-xl border border-red-900 bg-red-950/40 text-xs text-red-300 animate-fade-in">
              {error}
            </div>
          )}

          {isEmpty && (
            <div className="flex-1 flex items-center justify-center text-xs text-forge-text-muted animate-fade-in">
              The projected graph contains no nodes.
            </div>
          )}

          {!isLoading && !error && !isEmpty && (
            <div className="flex-1 flex flex-col justify-between animate-fade-in">
              <GraphCanvas
                graph={graph}
                selectedNodeId={selectedNode?.id ?? null}
                onSelectNode={handleSelectNode}
                heightClass="h-[calc(100vh-190px)]"
              />
            </div>
          )}
        </div>
      </div>

      {/* Right Contextual Inspection Panel */}
      {sidePanelOpen && (
        <div className="w-96 flex-shrink-0 border-l border-forge-border bg-forge-sidebar/70 flex flex-col justify-between overflow-y-auto animate-fade-in">
          <div className="p-4 space-y-4">
            <div className="flex items-center justify-between border-b border-forge-border pb-2.5">
              <span className="text-xs font-semibold uppercase tracking-wider text-forge-text-muted">
                {selectedNode ? "Node Intelligence" : "Graph Insights"}
              </span>
              {selectedNode && (
                <button
                  type="button"
                  onClick={() => handleSelectNode(null)}
                  className="rounded bg-forge-elevated px-1.5 py-0.5 text-[10px] text-forge-text-muted hover:text-forge-text-primary"
                >
                  Deselect ✕
                </button>
              )}
            </div>

            {selectedNode ? (
              <div className="space-y-4">
                {/* Node Intelligence Tabs: Overview, Dependencies, Dependents, Impact, Path */}
                <NodeIntelligencePanel
                  selectedNode={selectedNode}
                  activeTab={graphState.activeTab}
                  onTabChange={graphState.setActiveTab}
                  onSelectNode={handleSelectNode}
                  neighbors={graphState.neighbors}
                  dependencies={graphState.dependencies}
                  dependents={graphState.dependents}
                  impact={graphState.impact}
                  impactDirection={graphState.impactDirection}
                  onImpactDirectionChange={graphState.setImpactDirection}
                  impactDepth={graphState.impactDepth}
                  onImpactDepthChange={graphState.setImpactDepth}
                  maxImpactDepth={MAX_IMPACT_DEPTH}
                  onRunImpact={() => void graphState.impact.run()}
                  path={graphState.path}
                  pathTarget={graphState.pathTarget}
                  onSetPathTarget={graphState.selectPathTarget}
                  pathDepth={graphState.pathDepth}
                  onPathDepthChange={graphState.setPathDepth}
                  maxPathDepth={MAX_PATH_DEPTH}
                  canRunPath={graphState.canRunPath}
                  onRunPath={() => void graphState.path.run()}
                />

                {/* Quick Cross-Workspace Jump Actions */}
                <div className="pt-3 border-t border-forge-border space-y-2">
                  <div className="text-[11px] font-semibold text-forge-text-muted uppercase tracking-wider">
                    Actions
                  </div>

                  <div className="grid grid-cols-1 gap-2">
                    {selectedNode.kind === "file" && selectedNode.path && (
                      <button
                        type="button"
                        onClick={() => navigateToExplorer(selectedNode.path)}
                        className="flex items-center justify-between rounded-lg border border-forge-border bg-forge-panel px-3 py-2 text-xs text-forge-text-primary hover:bg-forge-elevated transition"
                      >
                        <span>Open File in Explorer</span>
                        <span className="text-forge-text-muted">→</span>
                      </button>
                    )}

                    {selectedNode.kind === "symbol" && selectedNode.name && (
                      <button
                        type="button"
                        onClick={() => navigateToExplorer(null, selectedNode.name)}
                        className="flex items-center justify-between rounded-lg border border-forge-border bg-forge-panel px-3 py-2 text-xs text-forge-text-primary hover:bg-forge-elevated transition"
                      >
                        <span>Inspect Symbol in Explorer</span>
                        <span className="text-forge-text-muted">→</span>
                      </button>
                    )}

                    <button
                      type="button"
                      onClick={() => navigateToImpact(selectedNode)}
                      className="flex items-center justify-between rounded-lg border border-forge-border bg-forge-panel px-3 py-2 text-xs text-amber-300 hover:bg-forge-elevated transition"
                    >
                      <span>Multi-Hop Blast Radius</span>
                      <span className="text-forge-text-muted">→</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        const name =
                          selectedNode.kind === "symbol"
                            ? selectedNode.qualifiedName ?? selectedNode.name
                            : selectedNode.kind === "file"
                              ? selectedNode.path
                              : selectedNode.id;
                        navigateToIntelligence(
                          `What are the upstream callers and downstream dependencies of ${name}?`,
                        );
                      }}
                      className="flex items-center justify-between rounded-lg border border-forge-accent/40 bg-forge-accent/10 px-3 py-2 text-xs text-forge-accent hover:bg-forge-accent/20 transition font-medium"
                    >
                      <span>Ask Forge about this node</span>
                      <span className="text-[10px]">AI</span>
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <p className="text-xs text-forge-text-muted">
                  Click any node on the graph canvas to inspect its dependencies, callers,
                  blast radius, and shortest paths.
                </p>

                {/* Graph Insights */}
                <GraphInsightsPanel state={insights} onSelectNode={handleSelectNode} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
