/**
 * RAG and code-intelligence API client.
 *
 * Purpose:       Perform RAG operations — check index status, index/re-index a
 *                repository, and ask grounded questions over indexed code.
 * Responsibility: Translation between wire DTOs and domain models.
 * Depends on:    infrastructure/api/client.ts, wire.ts, domain/rag/types.ts.
 * Depended on by: application/rag/useRepositoryRag.ts.
 */

import { apiGet, apiPost } from "@/infrastructure/api/client";
import { repositoryPath } from "@/infrastructure/api/wire";
import type {
  GraphContextItem,
  IndexStatus,
  IndexingResult,
  RagAnswer,
  SourceReference,
} from "@/domain/rag/types";

interface IndexStatusDto {
  repository_id: string;
  indexed: boolean;
  chunk_count: number;
  embedding_model: string | null;
  last_indexed_at: string | null;
}

interface IndexingResponseDto {
  repository_id: string;
  chunk_count: number;
  embedded_count: number;
  reused_count: number;
  files_indexed: number;
  skipped_files: number;
  embedding_model: string;
  indexed_at: string;
}

interface SourceReferenceDto {
  path: string;
  start_line: number;
  end_line: number;
  score: number;
  via: string;
  symbol_qualified_name: string | null;
  symbol_kind: string | null;
  snippet?: string;
}

interface GraphContextItemDto {
  qualified_name: string;
  kind: string;
  relationship: string;
  direction: string;
}

interface AskResponseDto {
  question: string;
  answer: string;
  has_sufficient_evidence: boolean;
  sources: SourceReferenceDto[];
  graph_context: GraphContextItemDto[];
  llm_provider: string;
  llm_model: string;
  embedding_model: string;
}

function toIndexStatus(dto: IndexStatusDto): IndexStatus {
  return {
    repositoryId: dto.repository_id,
    indexed: dto.indexed,
    chunkCount: dto.chunk_count,
    embeddingModel: dto.embedding_model,
    lastIndexedAt: dto.last_indexed_at,
  };
}

function toIndexingResult(dto: IndexingResponseDto): IndexingResult {
  return {
    repositoryId: dto.repository_id,
    chunkCount: dto.chunk_count,
    embeddedCount: dto.embedded_count,
    reusedCount: dto.reused_count,
    filesIndexed: dto.files_indexed,
    skippedFiles: dto.skipped_files,
    embeddingModel: dto.embedding_model,
    indexedAt: dto.indexed_at,
  };
}

function toSourceReference(dto: SourceReferenceDto): SourceReference {
  return {
    path: dto.path,
    startLine: dto.start_line,
    endLine: dto.end_line,
    score: dto.score,
    via: dto.via,
    symbolQualifiedName: dto.symbol_qualified_name,
    symbolKind: dto.symbol_kind,
    snippet: dto.snippet,
  };
}

function toGraphContextItem(dto: GraphContextItemDto): GraphContextItem {
  return {
    qualifiedName: dto.qualified_name,
    kind: dto.kind,
    relationship: dto.relationship,
    direction: dto.direction,
  };
}

function toRagAnswer(dto: AskResponseDto): RagAnswer {
  return {
    question: dto.question,
    answer: dto.answer,
    hasSufficientEvidence: dto.has_sufficient_evidence,
    sources: dto.sources.map(toSourceReference),
    graphContext: dto.graph_context.map(toGraphContextItem),
    llmProvider: dto.llm_provider,
    llmModel: dto.llm_model,
    embeddingModel: dto.embedding_model,
  };
}

/**
 * Fetch the current index status for a repository.
 */
export async function fetchIndexStatus(
  projectId: string,
  repositoryId: string,
): Promise<IndexStatus> {
  const path = `${repositoryPath(projectId, repositoryId)}/rag/status`;
  const dto = await apiGet<IndexStatusDto>(path);
  return toIndexStatus(dto);
}

/**
 * Trigger repository chunking, embedding generation, and vector index update.
 */
export async function triggerIndex(
  projectId: string,
  repositoryId: string,
): Promise<IndexingResult> {
  const path = `${repositoryPath(projectId, repositoryId)}/rag/index`;
  const dto = await apiPost<IndexingResponseDto>(path);
  return toIndexingResult(dto);
}

/**
 * Ask a grounded natural-language question about this repository's code.
 */
export async function askQuestion(
  projectId: string,
  repositoryId: string,
  question: string,
): Promise<RagAnswer> {
  const path = `${repositoryPath(projectId, repositoryId)}/rag/ask`;
  const dto = await apiPost<AskResponseDto>(path, { question });
  return toRagAnswer(dto);
}

