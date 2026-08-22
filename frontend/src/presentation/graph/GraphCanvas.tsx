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

import { useMemo } from "react";
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
}

export function GraphCanvas({ graph, selectedNodeId, onSelectNode }: GraphCanvasProps) {
  // Positions depend only on the nodes, never on selection.
  const positioned = useMemo(() => layoutGraph(graph.nodes), [graph.nodes]);

  const rfNodes = useMemo<Node<GraphNodeData>[]>(
    () =>
      positioned.map(({ node, x, y }) => ({
        id: node.id,
        type: "graphNode",
        position: { x, y },
        data: { node, isSelected: node.id === selectedNodeId },
      })),
    [positioned, selectedNodeId],
  );

  const rfEdges = useMemo<Edge[]>(
    () =>
      graph.relationships.map((rel) => ({
        id: rel.id,
        source: rel.sourceId,
        target: rel.targetId,
        style: { stroke: relationshipColor(rel.kind), strokeWidth: 1.5 },
        // Structural containment is background context; dependency edges are the signal.
        animated: rel.kind === "calls" || rel.kind === "imports",
      })),
    [graph.relationships],
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
    <div>
      <div className="h-[460px] overflow-hidden rounded-md border border-neutral-800 bg-neutral-950">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={NODE_TYPES}
          onNodeClick={handleNodeClick}
          nodesDraggable={false}
          nodesConnectable={false}
          fitView
          minZoom={0.1}
          colorMode="dark"
        >
          <Background gap={20} color="#27272a" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-neutral-500">
        {kindsPresent.map((kind) => (
          <span key={kind} className="flex items-center gap-1.5">
            <span
              className={`inline-block h-2.5 w-2.5 rounded-sm border ${NODE_KIND_STYLE[kind].box}`}
            />
            {NODE_KIND_STYLE[kind].label}
          </span>
        ))}
        <span className="text-neutral-700">|</span>
        {["contains", "defines", "imports", "calls", "inherits"].map((kind) => (
          <span key={kind} className="flex items-center gap-1.5">
            <span
              className="inline-block h-0.5 w-4"
              style={{ backgroundColor: relationshipColor(kind) }}
            />
            {kind}
          </span>
        ))}
      </div>
    </div>
  );
}
