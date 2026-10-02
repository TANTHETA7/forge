/**
 * RAG and code-intelligence domain types.
 *
 * Purpose:       Define domain representations for repository indexing,
 *                vector/graph retrieval, and grounded Q&A over code.
 * Responsibility: Pure TypeScript types — no fetching, no UI logic.
 * Why it exists: Decouples wire DTO models from application hooks and presentation
 *                components, matching the existing domain structure in
 *                `domain/explorer` and `domain/graph`.
 * Depended on by: infrastructure/api/ragApi.ts,
 *                 application/rag/useRepositoryRag.ts,
 *                 presentation/rag/RagPanel.tsx.
 */

export interface IndexStatus {
  repositoryId: string;
  indexed: boolean;
  chunkCount: number;
  embeddingModel: string | null;
  lastIndexedAt: string | null;
}

export interface IndexingResult {
  repositoryId: string;
  chunkCount: number;
  embeddedCount: number;
  reusedCount: number;
  filesIndexed: number;
  skippedFiles: number;
  embeddingModel: string;
  indexedAt: string;
}

export interface SourceReference {
  path: string;
  startLine: number;
  endLine: number;
  score: number;
  via: "vector" | "graph" | string;
  symbolQualifiedName: string | null;
  symbolKind: string | null;
  snippet?: string;
}

export interface GraphContextItem {
  qualifiedName: string;
  kind: string;
  relationship: string;
  direction: string;
}

export interface RagAnswer {
  question: string;
  answer: string;
  hasSufficientEvidence: boolean;
  sources: SourceReference[];
  graphContext: GraphContextItem[];
  llmProvider: string;
  llmModel: string;
  embeddingModel: string;
}

