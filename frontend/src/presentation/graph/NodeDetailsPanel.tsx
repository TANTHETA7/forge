/**
 * NodeDetailsPanel component.
 *
 * Purpose:       Show the selected node's typed details and its neighbors, and let a
 *                neighbor be selected in turn.
 * Responsibility: Presentation only. Neighbors are fetched by the hook; this renders
 *                whatever state that read is in.
 * Why it exists: Neighbor exploration is the point of the slice — selecting a neighbor
 *                makes it the selected node, which triggers exactly one further
 *                neighbors request.
 * Depends on:    domain/graph/types.ts, application/shared/useAsyncData.ts,
 *                presentation/shared/AsyncSection.tsx, presentation/graph/graphStyles.ts.
 * Depended on by: presentation/graph/GraphPanel.tsx.
 */

import type { AsyncDataState } from "@/application/shared/useAsyncData";
import { graphNodeLabel, type GraphNeighbor, type GraphNode } from "@/domain/graph/types";
import { NeighborList } from "@/presentation/graph/NeighborList";
import { NODE_KIND_STYLE } from "@/presentation/graph/graphStyles";

const DT = "text-xs uppercase tracking-wide text-neutral-500";

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className={DT}>{label}</dt>
      <dd className="break-all font-mono text-xs text-neutral-200">{value}</dd>
    </div>
  );
}

function NodeFacts({ node }: { node: GraphNode }) {
  switch (node.kind) {
    case "repository":
      return (
        <>
          <DetailRow label="Display name" value={node.displayName ?? "—"} />
          <DetailRow label="Project id" value={node.projectId ?? "—"} />
          <DetailRow label="Projected at" value={node.projectedAt ?? "—"} />
        </>
      );
    case "file":
      return (
        <>
          <DetailRow label="Path" value={node.path ?? "—"} />
          <DetailRow label="Language" value={node.language ?? "—"} />
          <DetailRow label="Syntax errors" value={node.hasSyntaxErrors ? "yes" : "no"} />
        </>
      );
    case "symbol":
      return (
        <>
          <DetailRow label="Name" value={node.name ?? "—"} />
          <DetailRow label="Qualified name" value={node.qualifiedName ?? "—"} />
          <DetailRow label="Symbol kind" value={node.symbolKind ?? "—"} />
          <DetailRow
            label="Lines"
            value={
              node.startLine === null ? "—" : `L${node.startLine}–${node.endLine ?? node.startLine}`
            }
          />
          <DetailRow label="File id" value={node.fileId ?? "—"} />
        </>
      );
    default:
      return <DetailRow label="Unrecognized kind" value={node.rawKind} />;
  }
}

interface NodeDetailsPanelProps {
  node: GraphNode | null;
  neighbors: AsyncDataState<GraphNeighbor[]>;
  onSelectNode: (node: GraphNode) => void;
}

export function NodeDetailsPanel({ node, neighbors, onSelectNode }: NodeDetailsPanelProps) {
  if (!node) {
    return (
      <p className="py-3 text-sm text-neutral-500">
        Select a node in the graph to see its details and neighbours.
      </p>
    );
  }

  const style = NODE_KIND_STYLE[node.kind];

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-baseline gap-2">
          <span className={`rounded px-1.5 py-0.5 text-[10px] uppercase ${style.badge}`}>
            {style.label}
          </span>
          <h4 className="break-all font-medium text-neutral-100">{graphNodeLabel(node)}</h4>
        </div>
        <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <NodeFacts node={node} />
          <DetailRow label="Node id" value={node.id} />
        </dl>
      </div>

      <div>
        <h5 className={`${DT} mb-1`}>Neighbours</h5>
        <NeighborList
          state={neighbors}
          loadingMessage="Loading neighbours…"
          emptyMessage="This node has no neighbours in the projected graph."
          onSelectNode={onSelectNode}
        />
      </div>
    </div>
  );
}
