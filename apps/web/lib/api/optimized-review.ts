/**
 * Optimized Review API
 * Helpers for loading and saving Stage 10 optimized chunks before QA.
 */

import { fastapiFetch } from './client';
import type { DocumentOptimizedChunksResponse, OptimizedChunkUpdate } from '@/types';

/**
 * The backend owns whether optimized review should be bypassed.
 * Frontend callers must not infer skip behavior from `source_type` alone.
 */
export function shouldSkipOptimizedReview(
  payload: DocumentOptimizedChunksResponse,
): boolean {
  return payload.skip_optimized_review;
}

/**
 * Load all optimized chunks for a document.
 * Returns the document name and the list of editable chunks
 * produced by the Stage 10 RAG optimization pipeline.
 */
export async function getDocumentOptimizedChunks(
  docId: string,
): Promise<DocumentOptimizedChunksResponse> {
  return fastapiFetch<DocumentOptimizedChunksResponse>(
    `/api/v1/documents/${docId}/optimized-chunks`,
  );
}

/**
 * Persist edits to a single optimized chunk.
 * Saving a chunk resets the document status to `optimization-complete`
 * and deletes any stale QA report — QA must be re-run after edits.
 */
export async function updateOptimizedChunk(
  docId: string,
  chunkId: string,
  payload: OptimizedChunkUpdate,
): Promise<{ chunk_id: string; status: string }> {
  return fastapiFetch<{ chunk_id: string; status: string }>(
    `/api/v1/documents/${docId}/optimized-chunks/${chunkId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
}
