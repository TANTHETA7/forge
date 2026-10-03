import { createContext, useContext, useState, type ReactNode } from "react";
import type { GraphNode } from "@/domain/graph/types";

export type WorkspaceSection =
  | "overview"
  | "explorer"
  | "graph"
  | "impact"
  | "intelligence";

interface WorkspaceNavigationState {
  section: WorkspaceSection;
  selectedFilePath: string | null;
  selectedSymbolName: string | null;
  selectedNodeId: string | null;
  selectedNode: GraphNode | null;
  impactTargetNode: GraphNode | null;
  prefilledPrompt: string | null;
  commandPaletteOpen: boolean;
}

interface WorkspaceContextValue extends WorkspaceNavigationState {
  setSection: (section: WorkspaceSection) => void;
  setCommandPaletteOpen: (open: boolean) => void;
  setSelectedFilePath: (path: string | null) => void;
  setSelectedSymbolName: (symbolName: string | null) => void;
  setSelectedNodeId: (nodeId: string | null) => void;
  setSelectedNode: (node: GraphNode | null) => void;
  setImpactTargetNode: (node: GraphNode | null) => void;
  setPrefilledPrompt: (prompt: string | null) => void;

  // Cross-workspace actions
  navigateToOverview: () => void;
  navigateToExplorer: (filePath?: string | null, symbolName?: string | null) => void;
  navigateToGraph: (nodeIdOrNode?: string | GraphNode | null) => void;
  navigateToImpact: (targetNode?: GraphNode | null) => void;
  navigateToIntelligence: (initialPrompt?: string | null) => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [section, setSection] = useState<WorkspaceSection>("overview");
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [selectedSymbolName, setSelectedSymbolName] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [impactTargetNode, setImpactTargetNode] = useState<GraphNode | null>(null);
  const [prefilledPrompt, setPrefilledPrompt] = useState<string | null>(null);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

  const navigateToOverview = () => {
    setSection("overview");
  };

  const navigateToExplorer = (filePath?: string | null, symbolName?: string | null) => {
    if (filePath !== undefined) setSelectedFilePath(filePath);
    if (symbolName !== undefined) setSelectedSymbolName(symbolName);
    setSection("explorer");
  };

  const navigateToGraph = (nodeIdOrNode?: string | GraphNode | null) => {
    if (typeof nodeIdOrNode === "string") {
      setSelectedNodeId(nodeIdOrNode);
    } else if (nodeIdOrNode && typeof nodeIdOrNode === "object") {
      setSelectedNode(nodeIdOrNode);
      setSelectedNodeId(nodeIdOrNode.id);
    }
    setSection("graph");
  };

  const navigateToImpact = (targetNode?: GraphNode | null) => {
    if (targetNode !== undefined) {
      setImpactTargetNode(targetNode);
      setSelectedNode(targetNode);
      setSelectedNodeId(targetNode ? targetNode.id : null);
    }
    setSection("impact");
  };

  const navigateToIntelligence = (initialPrompt?: string | null) => {
    if (initialPrompt) {
      setPrefilledPrompt(initialPrompt);
    }
    setSection("intelligence");
  };

  return (
    <WorkspaceContext.Provider
      value={{
        section,
        selectedFilePath,
        selectedSymbolName,
        selectedNodeId,
        selectedNode,
        impactTargetNode,
        prefilledPrompt,
        commandPaletteOpen,
        setSection,
        setCommandPaletteOpen,
        setSelectedFilePath,
        setSelectedSymbolName,
        setSelectedNodeId,
        setSelectedNode,
        setImpactTargetNode,
        setPrefilledPrompt,
        navigateToOverview,
        navigateToExplorer,
        navigateToGraph,
        navigateToImpact,
        navigateToIntelligence,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useWorkspace(): WorkspaceContextValue {
  const context = useContext(WorkspaceContext);
  if (!context) {
    throw new Error("useWorkspace must be used within a WorkspaceProvider");
  }
  return context;
}
