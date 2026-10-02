/**
 * useRepositoryRag hook.
 *
 * Purpose:       Manage RAG and code-intelligence state — check index status,
 *                trigger indexing, and execute grounded natural-language queries.
 * Responsibility: React state orchestration, request lifecycle, and error bridging.
 * Depends on:    application/shared/useAsyncData.ts,
 *                application/shared/useAsyncAction.ts,
 *                infrastructure/api/ragApi.ts,
 *                domain/rag/types.ts.
 * Depended on by: presentation/rag/RagPanel.tsx.
 */

import { useCallback, useState } from "react";

import { useAsyncAction, type AsyncAction } from "@/application/shared/useAsyncAction";
import { useAsyncData, type AsyncData } from "@/application/shared/useAsyncData";
import { askQuestion, fetchIndexStatus, triggerIndex } from "@/infrastructure/api/ragApi";
import type { IndexStatus, IndexingResult, RagAnswer, SourceReference } from "@/domain/rag/types";

export interface UseRepositoryRagReturn {
  status: AsyncData<IndexStatus>;
  indexing: AsyncAction<[], IndexingResult>;
  ask: AsyncAction<[string], RagAnswer>;
  question: string;
  setQuestion: (question: string) => void;
  selectedSource: SourceReference | null;
  selectSource: (source: SourceReference | null) => void;
  isIndexed: boolean;
  isBusy: boolean;
  canAsk: boolean;
  canIndex: boolean;
  handleAsk: (overrideQuestion?: string) => Promise<RagAnswer | null>;
  handleIndex: () => Promise<IndexingResult | null>;
}

export function useRepositoryRag(
  projectId: string | null,
  repositoryId: string | null,
  enabled: boolean,
): UseRepositoryRagReturn {
  const [question, setQuestion] = useState("");
  const [selectedSource, setSelectedSource] = useState<SourceReference | null>(null);

  const scoped = enabled && projectId !== null && repositoryId !== null;
  const scopeKey = `${projectId ?? "-"}:${repositoryId ?? "-"}`;

  const status = useAsyncData(
    `rag-status:${scopeKey}`,
    () => fetchIndexStatus(projectId as string, repositoryId as string),
    scoped,
  );

  const { reload: reloadStatus } = status;

  const indexing = useAsyncAction<[], IndexingResult>(async () => {
    if (!scoped || !projectId || !repositoryId) {
      throw new Error("Repository is not selected or ready for indexing");
    }
    const result = await triggerIndex(projectId, repositoryId);
    reloadStatus();
    return result;
  });

  const ask = useAsyncAction<[string], RagAnswer>(async (q: string) => {
    if (!scoped || !projectId || !repositoryId) {
      throw new Error("Repository is not selected or ready for queries");
    }
    const trimmed = q.trim();
    if (!trimmed) {
      throw new Error("Question cannot be empty");
    }
    return askQuestion(projectId, repositoryId, trimmed);
  });

  const isIndexed = status.data?.indexed ?? false;
  const isBusy = indexing.isPending || ask.isPending;
  const canAsk = scoped && isIndexed && !isBusy && question.trim().length > 0;
  const canIndex = scoped && !isBusy;

  const handleAsk = useCallback(
    async (overrideQuestion?: string): Promise<RagAnswer | null> => {
      const q = overrideQuestion ?? question;
      if (!q.trim()) return null;
      return ask.run(q);
    },
    [ask, question],
  );

  const handleIndex = useCallback(async (): Promise<IndexingResult | null> => {
    return indexing.run();
  }, [indexing]);

  return {
    status,
    indexing,
    ask,
    question,
    setQuestion,
    selectedSource,
    selectSource: setSelectedSource,
    isIndexed,
    isBusy,
    canAsk,
    canIndex,
    handleAsk,
    handleIndex,
  };
}

