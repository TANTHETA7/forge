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

/** Payload React Flow carries for each node. */
export interface GraphNodeData extends Record<string, unknown> {
  node: GraphNode;
  isSelected: boolean;
  isDimmed?: boolean;
  isDirectNeighbor?: boolean;
}

function getNodeIconBadge(node: GraphNode) {
  if (node.kind === "repository") {
    return {
      text: "REPO",
      bg: "bg-forge-accent/20 text-forge-accent border-forge-accent/40",
    };
  }
  if (node.kind === "file") {
    const lang = (node.language ?? "file").slice(0, 2).toUpperCase();
    return {
      text: lang,
      bg: "bg-sky-950 text-sky-300 border-sky-800",
    };
  }
  if (node.kind === "symbol") {
    const kind = node.symbolKind ?? "sym";
    if (kind === "function") {
      return { text: "Fn", bg: "bg-purple-950 text-purple-300 border-purple-800" };
    }
    if (kind === "class") {
      return { text: "Cls", bg: "bg-cyan-950 text-cyan-300 border-cyan-800" };
    }
    if (kind === "method") {
      return { text: "Mtd", bg: "bg-emerald-950 text-emerald-300 border-emerald-800" };
    }
    return { text: kind.slice(0, 3).toUpperCase(), bg: "bg-neutral-800 text-neutral-300 border-neutral-700" };
  }
  return { text: "?", bg: "bg-neutral-800 text-neutral-400 border-neutral-700" };
}

export function GraphNodeCard({ data }: NodeProps) {
  const { node, isSelected, isDimmed, isDirectNeighbor } = data as GraphNodeData;
  const label = graphNodeLabel(node);
  const badgeInfo = getNodeIconBadge(node);

  let subtitle = "";
  if (node.kind === "file" && node.path) {
    const parts = node.path.split("/");
    subtitle = parts.length > 1 ? parts.slice(0, -1).join("/") : node.language ?? "";
  } else if (node.kind === "symbol" && node.startLine !== null && node.endLine !== null) {
    subtitle = `L${node.startLine}–L${node.endLine}`;
  }

  return (
    <div
      data-testid={`graph-node-${node.id}`}
      data-kind={node.kind}
      data-selected={isSelected}
      title={label}
      className={
        "w-60 rounded-lg border px-3 py-2 text-left transition-all duration-200 select-none " +
        (isSelected
          ? "border-forge-accent bg-[#141414] ring-1 ring-forge-accent shadow-[0_0_20px_rgba(249,115,22,0.35)] z-20"
          : isDirectNeighbor
            ? "border-[#333333] bg-[#111111] shadow-md z-10"
            : isDimmed
              ? "opacity-25 border-forge-border/40 bg-[#080808] scale-[0.98]"
              : "border-forge-border bg-[#0d0d0d] hover:border-[#2a2a2a] hover:bg-[#121212]")
      }
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-neutral-500 !w-2 !h-2 !border-none"
      />

      <div className="flex items-center gap-2">
        <span
          className={`flex h-5 w-7 items-center justify-center rounded border font-mono text-[9px] font-bold ${badgeInfo.bg}`}
        >
          {badgeInfo.text}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate font-mono text-xs font-semibold text-forge-text-primary">
            {label}
          </div>
          {subtitle && (
            <div className="truncate font-mono text-[10px] text-forge-text-muted">
              {subtitle}
            </div>
          )}
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        className="!bg-neutral-500 !w-2 !h-2 !border-none"
      />
    </div>
  );
}

