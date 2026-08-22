/**
 * Graph visual vocabulary.
 *
 * Purpose:       One definition of how each node kind and relationship kind looks.
 * Responsibility: Style constants only — no React, no logic.
 * Why it exists: The canvas, the legend, and the details panel must agree on what a
 *                "file" or a "calls" edge looks like. Node styling uses Tailwind
 *                classes; edge styling needs literal colours because React Flow sets
 *                `stroke` as an SVG attribute rather than a class.
 * Depends on:    domain/graph/types.ts.
 * Depended on by: presentation/graph/{GraphNodeCard,GraphCanvas,NodeDetailsPanel}.
 */

import type { GraphNodeKind } from "@/domain/graph/types";

export type NodeStyleKey = GraphNodeKind | "unknown";

interface NodeStyle {
  label: string;
  /** Container classes for the node box and the legend swatch. */
  box: string;
  badge: string;
}

export const NODE_KIND_STYLE: Record<NodeStyleKey, NodeStyle> = {
  repository: {
    label: "repository",
    box: "border-emerald-600 bg-emerald-950/70",
    badge: "bg-emerald-900 text-emerald-200",
  },
  file: {
    label: "file",
    box: "border-sky-700 bg-sky-950/70",
    badge: "bg-sky-900 text-sky-200",
  },
  symbol: {
    label: "symbol",
    box: "border-violet-700 bg-violet-950/70",
    badge: "bg-violet-900 text-violet-200",
  },
  unknown: {
    label: "unknown",
    box: "border-neutral-700 bg-neutral-900",
    badge: "bg-neutral-800 text-neutral-300",
  },
};

export const NODE_KIND_ORDER: readonly NodeStyleKey[] = [
  "repository",
  "file",
  "symbol",
  "unknown",
];

/**
 * Edge colours. Structural containment (`contains`, `defines`) is deliberately muted
 * so the dependency edges Phase 4 resolved — imports, calls, inherits — stand out.
 */
export const RELATIONSHIP_COLOR: Record<string, string> = {
  contains: "#3f3f46",
  defines: "#52525b",
  imports: "#38bdf8",
  calls: "#fbbf24",
  inherits: "#a78bfa",
};

export const UNKNOWN_RELATIONSHIP_COLOR = "#71717a";

export function relationshipColor(kind: string): string {
  return RELATIONSHIP_COLOR[kind] ?? UNKNOWN_RELATIONSHIP_COLOR;
}
