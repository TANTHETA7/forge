/**
 * GraphNodeCard component.
 *
 * Purpose:       Render one node on the graph canvas, styled by its kind and marked
 *                when selected.
 * Responsibility: Presentation only — a React Flow custom node type.
 * Why it exists: Node kinds must be distinguishable at a glance, and React Flow needs
 *                explicit `Handle`s for edges to attach to.
 * Depends on:    @xyflow/react, domain/graph/types.ts, presentation/graph/graphStyles.ts.
 * Depended on by: presentation/graph/GraphCanvas.tsx.
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";

import { graphNodeLabel, type GraphNode } from "@/domain/graph/types";
import { NODE_KIND_STYLE } from "@/presentation/graph/graphStyles";

/** Payload React Flow carries for each node. */
export interface GraphNodeData extends Record<string, unknown> {
  node: GraphNode;
  isSelected: boolean;
}

export function GraphNodeCard({ data }: NodeProps) {
  const { node, isSelected } = data as GraphNodeData;
  const style = NODE_KIND_STYLE[node.kind];
  const label = graphNodeLabel(node);

  return (
    <div
      data-testid={`graph-node-${node.id}`}
      data-kind={node.kind}
      data-selected={isSelected}
      title={label}
      className={
        "w-56 rounded-md border px-2.5 py-1.5 text-left " +
        style.box +
        (isSelected ? " ring-2 ring-neutral-100" : "")
      }
    >
      <Handle type="target" position={Position.Left} className="!bg-neutral-600" />
      <div className="flex items-center gap-1.5">
        <span className={`rounded px-1 py-0.5 text-[10px] uppercase ${style.badge}`}>
          {node.kind === "symbol" ? (node.symbolKind ?? "symbol") : style.label}
        </span>
      </div>
      <div className="mt-0.5 truncate font-mono text-xs text-neutral-100">{label}</div>
      <Handle type="source" position={Position.Right} className="!bg-neutral-600" />
    </div>
  );
}
