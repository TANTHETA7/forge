/**
 * GraphInsightsPanel component.
 *
 * Purpose:       Show the repository-level insights the backend computed.
 * Responsibility: Presentation only.
 * Why it exists: Insights are repository-wide rather than node-scoped, so they sit
 *                beside the graph rather than inside the selected-node panel. Every
 *                value shown is a plain count or graph fact from `/graph/insights` —
 *                nothing is scored, ranked, or inferred here.
 *
 *                Each list is empty-stated separately: "no mutual import pairs" is a
 *                real, meaningful answer, not a missing section.
 *
 * Depends on:    domain/graph/types.ts, application/shared/useAsyncData.ts,
 *                presentation/shared/{AsyncSection,SummaryStat}, graphStyles.
 * Depended on by: presentation/graph/GraphPanel.tsx.
 */

import type { AsyncDataState } from "@/application/shared/useAsyncData";
import {
  graphNodeLabel,
  type GraphInsights,
  type GraphNode,
  type NodeDegree,
} from "@/domain/graph/types";
import { AsyncSection } from "@/presentation/shared/AsyncSection";
import { SummaryStat } from "@/presentation/shared/SummaryStat";
import { NODE_KIND_STYLE } from "@/presentation/graph/graphStyles";

const SUBHEADING = "mb-1 text-xs uppercase tracking-wide text-neutral-500";

function NodeButton({ node, onSelect }: { node: GraphNode; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="flex w-full flex-wrap items-baseline gap-2 px-1 py-1 text-left text-sm hover:bg-neutral-900"
    >
      <span
        className={`rounded px-1 py-0.5 text-[10px] uppercase ${NODE_KIND_STYLE[node.kind].badge}`}
      >
        {NODE_KIND_STYLE[node.kind].label}
      </span>
      <span className="break-all font-mono text-xs text-neutral-200">{graphNodeLabel(node)}</span>
    </button>
  );
}

function DegreeList({
  title,
  entries,
  emptyMessage,
  onSelectNode,
}: {
  title: string;
  entries: NodeDegree[];
  emptyMessage: string;
  onSelectNode: (node: GraphNode) => void;
}) {
  return (
    <div>
      <h4 className={SUBHEADING}>{title}</h4>
      {entries.length === 0 ? (
        <p className="text-sm text-neutral-500">{emptyMessage}</p>
      ) : (
        <ul className="divide-y divide-neutral-800">
          {entries.map((entry) => (
            <li key={entry.node.id} className="flex items-center gap-2">
              <span className="w-12 shrink-0 text-right font-mono text-xs tabular-nums text-neutral-400">
                {entry.degree}
              </span>
              <NodeButton node={entry.node} onSelect={() => onSelectNode(entry.node)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface GraphInsightsPanelProps {
  state: AsyncDataState<GraphInsights>;
  onSelectNode: (node: GraphNode) => void;
}

export function GraphInsightsPanel({ state, onSelectNode }: GraphInsightsPanelProps) {
  return (
    <AsyncSection
      state={state}
      loadingMessage="Loading insights…"
      emptyMessage="No insights available."
      isEmpty={() => false}
    >
      {(insights) => (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <SummaryStat
              label="Unresolved deps"
              value={insights.unresolvedDependencyCount}
              tone={insights.unresolvedDependencyCount > 0 ? "warn" : "default"}
            />
            <SummaryStat label="Connected files" value={insights.mostConnectedFiles.length} />
            <SummaryStat label="Hotspots" value={insights.dependencyHotspots.length} />
            <SummaryStat
              label="Mutual imports"
              value={insights.mutualImportPairs.length}
              tone={insights.mutualImportPairs.length > 0 ? "warn" : "default"}
            />
          </div>

          <DegreeList
            title="Most connected files (imports degree)"
            entries={insights.mostConnectedFiles}
            emptyMessage="No file has any import edges."
            onSelectNode={onSelectNode}
          />

          <DegreeList
            title="Dependency hotspots (calls + inherits degree)"
            entries={insights.dependencyHotspots}
            emptyMessage="No symbol is entangled with others."
            onSelectNode={onSelectNode}
          />

          <div>
            <h4 className={SUBHEADING}>Mutual import pairs (direct A ↔ B only)</h4>
            {insights.mutualImportPairs.length === 0 ? (
              <p className="text-sm text-neutral-500">
                No direct circular imports. This check is 1-hop only, so longer cycles are not
                reported.
              </p>
            ) : (
              <ul className="space-y-1">
                {insights.mutualImportPairs.map((pair) => (
                  <li
                    key={`${pair.fileA.id}:${pair.fileB.id}`}
                    className="flex flex-wrap items-center gap-2 rounded-md bg-amber-950/40 px-2 py-1"
                  >
                    <button
                      type="button"
                      onClick={() => onSelectNode(pair.fileA)}
                      className="break-all font-mono text-xs text-amber-200 hover:underline"
                    >
                      {graphNodeLabel(pair.fileA)}
                    </button>
                    <span className="text-amber-500">↔</span>
                    <button
                      type="button"
                      onClick={() => onSelectNode(pair.fileB)}
                      className="break-all font-mono text-xs text-amber-200 hover:underline"
                    >
                      {graphNodeLabel(pair.fileB)}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h4 className={SUBHEADING}>Isolated nodes</h4>
            {insights.isolatedNodes.length === 0 ? (
              <p className="text-sm text-neutral-500">Every node has at least one edge.</p>
            ) : (
              <ul className="divide-y divide-neutral-800">
                {insights.isolatedNodes.map((node) => (
                  <li key={node.id}>
                    <NodeButton node={node} onSelect={() => onSelectNode(node)} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </AsyncSection>
  );
}
