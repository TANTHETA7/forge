/**
 * GraphCanvas component.
 *
 * Purpose:       Render the graph — nodes positioned by kind, relationships as edges
 *                coloured by kind — and report node clicks.
 * Responsibility: Presentation only. It owns no data and no selection state; both are
 *                passed in.
 * Why it exists: React Flow (already a dependency) gives pan, zoom, and custom node
 *                types declaratively. Cytoscape is also installed but would need
 *                imperative mount/teardown plumbing for no benefit at this scope.
 *
 * Performance:   Layout is memoized on the node array alone, so changing selection
 *                re-maps nodes without recomputing positions, and edges are memoized
 *                separately. Nodes are not draggable, which keeps positions
 *                deterministic across renders.
 *
 * Depends on:    @xyflow/react, domain/graph/types.ts, application/graph/useRepositoryGraph.ts,
 *                presentation/graph/{graphLayout,graphStyles,GraphNodeCard}.
 * Depended on by: presentation/graph/GraphPanel.tsx.
 */

import { useMemo, useState } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { RenderableGraph } from "@/application/graph/useRepositoryGraph";
import type { GraphNode } from "@/domain/graph/types";
import { GraphNodeCard, type GraphNodeData } from "@/presentation/graph/GraphNodeCard";
import { layoutGraph } from "@/presentation/graph/graphLayout";
import { NODE_KIND_ORDER, NODE_KIND_STYLE, relationshipColor } from "@/presentation/graph/graphStyles";

// Defined at module scope: React Flow warns and re-renders if this object changes identity.
const NODE_TYPES = { graphNode: GraphNodeCard };

interface GraphCanvasProps {
  graph: RenderableGraph;
  selectedNodeId: string | null;
  onSelectNode: (node: GraphNode) => void;
  heightClass?: string;
}

export function GraphCanvas({
  graph,
  selectedNodeId,
  onSelectNode,
  heightClass = "h-[540px]",
}: GraphCanvasProps) {
  const [focusMode, setFocusMode] = useState(true);
  const [kindFilter, setKindFilter] = useState<string>("all");

  // Filter nodes if kindFilter is active
  const filteredNodes = useMemo(() => {
    if (kindFilter === "all") return graph.nodes;
    return graph.nodes.filter((n) => n.kind === kindFilter);
  }, [graph.nodes, kindFilter]);

  // Positions depend only on the filtered nodes
  const positioned = useMemo(() => layoutGraph(filteredNodes), [filteredNodes]);

  // Compute 1-hop neighbors of selected node for Focus Mode
  const directNeighborIds = useMemo(() => {
    if (!selectedNodeId) return new Set<string>();
    const neighbors = new Set<string>();
    for (const rel of graph.relationships) {
      if (rel.sourceId === selectedNodeId) neighbors.add(rel.targetId);
      if (rel.targetId === selectedNodeId) neighbors.add(rel.sourceId);
    }
    return neighbors;
  }, [graph.relationships, selectedNodeId]);

  const rfNodes = useMemo<Node<GraphNodeData>[]>(
    () =>
      positioned.map(({ node, x, y }) => {
        const isSelected = node.id === selectedNodeId;
        const isDirectNeighbor = directNeighborIds.has(node.id);
        const isDimmed =
          focusMode &&
          selectedNodeId !== null &&
          !isSelected &&
          !isDirectNeighbor;

        return {
          id: node.id,
          type: "graphNode",
          position: { x, y },
          data: {
            node,
            isSelected,
            isDimmed,
            isDirectNeighbor,
          },
        };
      }),
    [positioned, selectedNodeId, directNeighborIds, focusMode],
  );

  const rfEdges = useMemo<Edge[]>(
    () =>
      graph.relationships.map((rel) => {
        const connectsSelected =
          rel.sourceId === selectedNodeId || rel.targetId === selectedNodeId;
        const isDimmed =
          focusMode && selectedNodeId !== null && !connectsSelected;

        const baseColor = relationshipColor(rel.kind);

        return {
          id: rel.id,
          source: rel.sourceId,
          target: rel.targetId,
          style: {
            stroke: connectsSelected ? "#f97316" : baseColor,
            strokeWidth: connectsSelected ? 2.5 : 1.2,
            opacity: isDimmed ? 0.15 : connectsSelected ? 1 : 0.65,
          },
          animated: connectsSelected || rel.kind === "calls" || rel.kind === "imports",
        };
      }),
    [graph.relationships, selectedNodeId, focusMode],
  );

  const handleNodeClick: NodeMouseHandler = (_event, rfNode) => {
    const { node } = rfNode.data as GraphNodeData;
    onSelectNode(node);
  };

  const kindsPresent = useMemo(() => {
    const present = new Set(graph.nodes.map((node) => node.kind));
    return NODE_KIND_ORDER.filter((kind) => present.has(kind));
  }, [graph.nodes]);

  return (
    <div className="space-y-2">
      {/* Interactive Graph Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-forge-border bg-forge-card/80 px-3 py-1.5 text-xs">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold uppercase text-forge-text-muted">
            Filter:
          </span>
          <button
            type="button"
            onClick={() => setKindFilter("all")}
            className={`rounded px-2 py-0.5 text-[11px] forge-btn-interactive ${
              kindFilter === "all"
                ? "bg-forge-elevated text-forge-text-primary font-medium border border-forge-border"
                : "text-forge-text-muted hover:text-forge-text-primary"
            }`}
          >
            All ({graph.nodes.length})
          </button>
          {kindsPresent.map((kind) => (
            <button
              key={kind}
              type="button"
              onClick={() => setKindFilter(kind)}
              className={`rounded px-2 py-0.5 text-[11px] forge-btn-interactive ${
                kindFilter === kind
                  ? "bg-forge-elevated text-forge-text-primary font-medium border border-forge-border"
                  : "text-forge-text-muted hover:text-forge-text-primary"
              }`}
            >
              {kind}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          {/* Focus Mode Toggle */}
          <button
            type="button"
            onClick={() => setFocusMode(!focusMode)}
            className={`flex items-center gap-1.5 rounded border px-2 py-0.5 text-[11px] font-medium forge-btn-interactive ${
              focusMode
                ? "border-forge-accent/40 bg-forge-accent/15 text-forge-accent"
                : "border-forge-border bg-forge-elevated text-forge-text-muted hover:text-forge-text-primary"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                focusMode ? "bg-forge-accent" : "bg-neutral-500"
              }`}
            />
            <span>Focus Mode (1-Hop)</span>
          </button>
        </div>
      </div>

      {/* React Flow Viewport */}
      <div
        className={`${heightClass} overflow-hidden rounded-xl border border-forge-border bg-[#050505] relative shadow-inner`}
      >
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={NODE_TYPES}
          onNodeClick={handleNodeClick}
          nodesDraggable={false}
          nodesConnectable={false}
          fitView
          fitViewOptions={{ duration: 300 }}
          minZoom={0.1}
          colorMode="dark"
        >
          <Background gap={24} color="#151515" />
          <Controls showInteractive={false} className="!border-forge-border !bg-forge-panel !text-forge-text-muted" />
        </ReactFlow>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-forge-text-muted px-1">
        <div className="flex items-center gap-3">
          {kindsPresent.map((kind) => (
            <span key={kind} className="flex items-center gap-1.5 text-[11px]">
              <span
                className={`inline-block h-2 w-2 rounded-sm border ${NODE_KIND_STYLE[kind].box}`}
              />
              <span className="capitalize">{NODE_KIND_STYLE[kind].label}</span>
            </span>
          ))}
        </div>

        <div className="flex items-center gap-3">
          {["contains", "defines", "imports", "calls", "inherits"].map((kind) => (
            <span key={kind} className="flex items-center gap-1.5 text-[11px]">
              <span
                className="inline-block h-0.5 w-3 rounded-full"
                style={{ backgroundColor: relationshipColor(kind) }}
              />
              <span className="font-mono">{kind}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
