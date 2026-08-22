/**
 * NeighborList component.
 *
 * Purpose:       Render a list of related nodes — each with its relationship kind and
 *                direction — and report which one was clicked.
 * Responsibility: Presentation only.
 * Why it exists: `/graph/neighbors/{id}`, `/graph/nodes/{id}/dependencies`, and
 *                `/graph/nodes/{id}/dependents` all return the same
 *                `GraphNeighborResponse` shape, so all three render through this one
 *                component rather than three near-identical lists.
 * Depends on:    domain/graph/types.ts, application/shared/useAsyncData.ts,
 *                presentation/shared/AsyncSection.tsx, presentation/graph/graphStyles.ts.
 * Depended on by: presentation/graph/{NodeDetailsPanel,NodeIntelligencePanel}.
 */

import type { AsyncDataState } from "@/application/shared/useAsyncData";
import { graphNodeLabel, type GraphNeighbor, type GraphNode } from "@/domain/graph/types";
import { AsyncSection } from "@/presentation/shared/AsyncSection";
import { NODE_KIND_STYLE, relationshipColor } from "@/presentation/graph/graphStyles";

interface NeighborListProps {
  state: AsyncDataState<GraphNeighbor[]>;
  emptyMessage: string;
  loadingMessage: string;
  onSelectNode: (node: GraphNode) => void;
}

export function NeighborList({
  state,
  emptyMessage,
  loadingMessage,
  onSelectNode,
}: NeighborListProps) {
  return (
    <AsyncSection state={state} loadingMessage={loadingMessage} emptyMessage={emptyMessage}>
      {(list) => (
        <ul className="divide-y divide-neutral-800">
          {list.map((neighbor, index) => (
            // The same node can appear under two relationship kinds, so the key
            // includes both — and the index, since the API returns no row id.
            <li
              key={`${neighbor.direction}:${neighbor.relationshipKind}:${neighbor.node.id}:${index}`}
            >
              <button
                type="button"
                onClick={() => onSelectNode(neighbor.node)}
                className="flex w-full flex-wrap items-baseline gap-2 px-1 py-1.5 text-left text-sm hover:bg-neutral-900"
              >
                <span
                  className="font-mono text-[10px] uppercase"
                  style={{ color: relationshipColor(neighbor.relationshipKind) }}
                >
                  {neighbor.direction === "outgoing" ? "→" : "←"} {neighbor.relationshipKind}
                </span>
                <span
                  className={`rounded px-1 py-0.5 text-[10px] uppercase ${
                    NODE_KIND_STYLE[neighbor.node.kind].badge
                  }`}
                >
                  {NODE_KIND_STYLE[neighbor.node.kind].label}
                </span>
                <span className="break-all font-mono text-xs text-neutral-200">
                  {graphNodeLabel(neighbor.node)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </AsyncSection>
  );
}
