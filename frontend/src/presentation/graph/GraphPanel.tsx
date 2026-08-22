/**
 * GraphPanel component.
 *
 * Purpose:       The graph workspace — statistics, the canvas, the selected node's
 *                intelligence tabs, and repository-level insights.
 * Responsibility: Composition and rendering only. All requests, bounds, parameters, and
 *                 selection state come from `useRepositoryGraph`.
 * Why it exists: Gives the Neo4j projection somewhere to be seen. It appears only after
 *                graph projection succeeds; before that it renders a locked state and
 *                the hook issues no requests, because none could succeed.
 *
 *                Node-scoped views (dependencies, dependents, impact, path) live in the
 *                selected-node panel; repository-scoped views (statistics, insights) sit
 *                outside it, since they do not change with selection.
 *
 * Depends on:    application/graph/useRepositoryGraph.ts,
 *                presentation/graph/{GraphCanvas,NodeIntelligencePanel,GraphInsightsPanel},
 *                presentation/shared/SummaryStat.tsx.
 * Depended on by: presentation/pipeline/PipelinePanel.tsx.
 */

import {
  MAX_IMPACT_DEPTH,
  MAX_PATH_DEPTH,
  useRepositoryGraph,
} from "@/application/graph/useRepositoryGraph";
import { GraphCanvas } from "@/presentation/graph/GraphCanvas";
import { GraphInsightsPanel } from "@/presentation/graph/GraphInsightsPanel";
import { NodeIntelligencePanel } from "@/presentation/graph/NodeIntelligencePanel";
import { SummaryStat } from "@/presentation/shared/SummaryStat";

const SECTION_CLASS = "rounded-lg border border-neutral-800 bg-neutral-900/40 p-4";
const HEADING_CLASS = "mb-3 text-sm font-medium uppercase tracking-wide text-neutral-400";

interface GraphPanelProps {
  projectId: string | null;
  repositoryId: string | null;
  /** False until graph projection has succeeded — nothing is queryable before then. */
  enabled: boolean;
}

export function GraphPanel({ projectId, repositoryId, enabled }: GraphPanelProps) {
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

  const stats = statistics.data;

  return (
    <>
      <section className={SECTION_CLASS}>
        <h2 className={HEADING_CLASS}>9 · Repository graph</h2>

        {!enabled ? (
          <p className="py-3 text-sm text-neutral-500">
            Locked — run the graph projection stage to build the graph in Neo4j.
          </p>
        ) : (
          <div className="space-y-3">
            {stats && (
              <>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <SummaryStat label="Nodes" value={stats.totalNodes} />
                  <SummaryStat label="Files" value={stats.totalFiles} />
                  <SummaryStat label="Symbols" value={stats.totalSymbols} />
                  <SummaryStat label="Relationships" value={stats.totalRelationships} />
                </div>
                <p className="text-xs text-neutral-500">
                  {stats.relationshipsByKind
                    .map((entry) => `${entry.kind} ${entry.count}`)
                    .join(" · ")}
                  {" · graph is "}
                  {stats.freshness}
                </p>
              </>
            )}

            {isLoading && <p className="py-3 text-sm text-neutral-500">Loading graph…</p>}

            {error && (
              <p role="alert" className="rounded-md bg-red-950 px-3 py-2 text-sm text-red-300">
                {error}
              </p>
            )}

            {isEmpty && (
              <p className="py-3 text-sm text-neutral-500">
                The projection contains no nodes.
              </p>
            )}

            {!isLoading && !error && !isEmpty && (
              <>
                <GraphCanvas
                  graph={graph}
                  selectedNodeId={selectedNode?.id ?? null}
                  onSelectNode={selectNode}
                />
                <p className="text-xs text-neutral-600">
                  Showing {graph.nodes.length} nodes and {graph.relationships.length}{" "}
                  relationships.
                  {isTruncated &&
                    stats &&
                    ` This view is bounded — the projection has ${stats.totalNodes} nodes in total.`}
                  {graph.omittedRelationshipCount > 0 &&
                    ` ${graph.omittedRelationshipCount} relationship(s) are hidden because an endpoint is outside this view.`}
                </p>
              </>
            )}
          </div>
        )}
      </section>

      {enabled && (
        <>
          <section className={SECTION_CLASS}>
            <h2 className={HEADING_CLASS}>10 · Selected node</h2>
            <NodeIntelligencePanel
              selectedNode={selectedNode}
              activeTab={graphState.activeTab}
              onTabChange={graphState.setActiveTab}
              onSelectNode={selectNode}
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
          </section>

          <section className={SECTION_CLASS}>
            <h2 className={HEADING_CLASS}>11 · Graph insights</h2>
            <GraphInsightsPanel state={insights} onSelectNode={selectNode} />
          </section>

          {stats && (
            <section className={SECTION_CLASS}>
              <h2 className={HEADING_CLASS}>12 · Graph statistics</h2>
              <div className="space-y-3 text-sm">
                <p className="text-xs text-neutral-500">
                  Projected {stats.projectedAt ?? "—"} · computed {stats.computedAt} · state{" "}
                  {stats.freshness}
                </p>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <h4 className="mb-1 text-xs uppercase tracking-wide text-neutral-500">
                      Highest in-degree
                    </h4>
                    {stats.highestInDegree.length === 0 ? (
                      <p className="text-sm text-neutral-500">No nodes have incoming edges.</p>
                    ) : (
                      <ul className="space-y-0.5">
                        {stats.highestInDegree.map((entry) => (
                          <li key={entry.node.id} className="font-mono text-xs text-neutral-300">
                            <span className="text-neutral-500">{entry.degree}</span>{" "}
                            {entry.node.kind === "file"
                              ? (entry.node.path ?? entry.node.id)
                              : entry.node.kind === "symbol"
                                ? (entry.node.name ?? entry.node.id)
                                : entry.node.id}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div>
                    <h4 className="mb-1 text-xs uppercase tracking-wide text-neutral-500">
                      Highest out-degree
                    </h4>
                    {stats.highestOutDegree.length === 0 ? (
                      <p className="text-sm text-neutral-500">No nodes have outgoing edges.</p>
                    ) : (
                      <ul className="space-y-0.5">
                        {stats.highestOutDegree.map((entry) => (
                          <li key={entry.node.id} className="font-mono text-xs text-neutral-300">
                            <span className="text-neutral-500">{entry.degree}</span>{" "}
                            {entry.node.kind === "file"
                              ? (entry.node.path ?? entry.node.id)
                              : entry.node.kind === "symbol"
                                ? (entry.node.name ?? entry.node.id)
                                : entry.node.id}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </div>
            </section>
          )}
        </>
      )}
    </>
  );
}
