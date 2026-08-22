/**
 * Deterministic graph layout.
 *
 * Purpose:       Assign a position to every graph node without a physics simulation.
 * Responsibility: Pure geometry — no React, no fetching, no domain rules.
 * Why it exists: The projection is layered by construction (a repository contains
 *                files, a file defines symbols), so a layered layout reflects the real
 *                structure and is stable across reloads. It is O(N log N) — one sort
 *                per kind — with no pairwise force calculation, so it cannot degrade
 *                into O(N²) as a repository grows. Identical input always yields
 *                identical output, which keeps node positions from jumping between
 *                renders.
 * Depends on:    domain/graph/types.ts.
 * Depended on by: presentation/graph/GraphCanvas.tsx.
 */

import { graphNodeLabel, type GraphNode, type GraphNodeKind } from "@/domain/graph/types";

export interface PositionedNode {
  node: GraphNode;
  x: number;
  y: number;
}

/** Column order, left to right, following containment. */
const KIND_ORDER: readonly (GraphNodeKind | "unknown")[] = [
  "repository",
  "file",
  "symbol",
  "unknown",
];

const ROW_HEIGHT = 58;
/** Width of one sub-column, including the gap to the next. */
const SUB_COLUMN_WIDTH = 250;
/** Horizontal gap between two different kinds. */
const KIND_GAP = 90;
/**
 * Rows before a column wraps into another sub-column. Without this, a repository with
 * hundreds of symbols becomes one very tall, very thin strip that is unreadable at the
 * zoom level needed to see it all.
 */
const MAX_ROWS_PER_COLUMN = 14;

/** Sort key that is total and stable: label first, id as the tiebreak. */
function compareNodes(a: GraphNode, b: GraphNode): number {
  // Symbols read best grouped by their file, then by position within it.
  if (a.kind === "symbol" && b.kind === "symbol") {
    const byFile = (a.fileId ?? "").localeCompare(b.fileId ?? "");
    if (byFile !== 0) return byFile;
    const byLine = (a.startLine ?? 0) - (b.startLine ?? 0);
    if (byLine !== 0) return byLine;
  }

  const byLabel = graphNodeLabel(a).localeCompare(graphNodeLabel(b));
  return byLabel !== 0 ? byLabel : a.id.localeCompare(b.id);
}

/**
 * Lay nodes out in kind-ordered columns, wrapping tall columns into sub-columns and
 * centring each kind vertically.
 *
 * O(N log N) — one sort per kind, then a single pass. No pairwise force calculation,
 * and identical input always produces identical output, so node positions never jump
 * between renders.
 */
export function layoutGraph(nodes: GraphNode[]): PositionedNode[] {
  const byKind = new Map<GraphNodeKind | "unknown", GraphNode[]>();
  for (const node of nodes) {
    const column = byKind.get(node.kind);
    if (column) column.push(node);
    else byKind.set(node.kind, [node]);
  }

  for (const column of byKind.values()) column.sort(compareNodes);

  // Tallest wrapped column sets the vertical centre line for every kind.
  let tallest = 0;
  for (const column of byKind.values()) {
    tallest = Math.max(tallest, Math.min(column.length, MAX_ROWS_PER_COLUMN));
  }

  const positioned: PositionedNode[] = [];
  let cursorX = 0;

  for (const kind of KIND_ORDER) {
    const column = byKind.get(kind);
    if (!column) continue;

    const rows = Math.min(column.length, MAX_ROWS_PER_COLUMN);
    const offsetY = ((tallest - rows) * ROW_HEIGHT) / 2;

    column.forEach((node, index) => {
      positioned.push({
        node,
        x: cursorX + Math.floor(index / MAX_ROWS_PER_COLUMN) * SUB_COLUMN_WIDTH,
        y: offsetY + (index % MAX_ROWS_PER_COLUMN) * ROW_HEIGHT,
      });
    });

    const subColumns = Math.ceil(column.length / MAX_ROWS_PER_COLUMN);
    cursorX += subColumns * SUB_COLUMN_WIDTH + KIND_GAP;
  }

  return positioned;
}
