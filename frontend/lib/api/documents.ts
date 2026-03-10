/**
 * Documents API - PostgREST integration
 * Handles document metadata retrieval
 */

import { postgrestFetch, from } from './client';
import type { Document } from '@/types';

/**
 * Document summary from document_summaries view
 */
export interface DocumentSummary {
  id: string;
  title: string;
  version: string;
  system: string;
  document_type: string;
  status: Document['status'];
  total_pages: number;
  total_sections: number;
  review_progress: number;
  review_progress_percent: number;
  qa_score?: number;
  uploaded_by: string;
  uploaded_by_name: string;
  uploaded_at: string;
  approved_by?: string;
  approved_by_name?: string;
  approved_at?: string;
  notes?: string;
}

/**
 * Convert DocumentSummary to frontend Document type
 */
function toDocument(summary: DocumentSummary): Document {
  return {
    id: summary.id,
    title: summary.title,
    version: summary.version,
    system: summary.system,
    documentType: summary.document_type,
    status: summary.status,
    totalPages: summary.total_pages,
    totalSections: summary.total_sections,
    reviewProgress: summary.review_progress_percent,
    qaScore: summary.qa_score,
    uploadedBy: summary.uploaded_by_name,
    uploadedAt: summary.uploaded_at,
    approvedBy: summary.approved_by_name,
    approvedAt: summary.approved_at,
    notes: summary.notes,
  };
}

/**
 * Get all documents
 */
export async function getDocuments(filters?: {
  status?: Document['status'];
  system?: string;
  limit?: number;
  offset?: number;
}): Promise<Document[]> {
  const query = from<DocumentSummary[]>('document_summaries')
    .select('*')
    .order('uploaded_at', 'desc');
  
  if (filters?.status) {
    query.eq('status', filters.status);
  }
  
  if (filters?.system) {
    query.like('system', filters.system);
  }
  
  if (filters?.limit) {
    query.limit(filters.limit);
  }
  
  if (filters?.offset) {
    query.offset(filters.offset);
  }
  
  const summaries = await query.execute();
  return summaries.map(toDocument);
}

/**
 * Get documents in review queue (validation-complete or in-review)
 */
export async function getReviewQueueDocuments(): Promise<Document[]> {
  const summaries = await postgrestFetch<DocumentSummary[]>(
    '/document_summaries?or=(status.eq.validation-complete,status.eq.in-review)&order=uploaded_at.asc'
  );
  
  return summaries.map(toDocument);
}

/**
 * Get documents ready for QA gates (review-complete)
 */
export async function getQAGateDocuments(): Promise<Document[]> {
  const summaries = await postgrestFetch<DocumentSummary[]>(
    '/document_summaries?status=eq.review-complete&order=uploaded_at.asc'
  );
  
  return summaries.map(toDocument);
}

/**
 * Get single document by ID
 */
export async function getDocumentById(id: string): Promise<Document> {
  const summary = await from<DocumentSummary[]>('document_summaries')
    .select('*')
    .eq('id', id)
    .single();
  
  return toDocument(summary);
}

/**
 * Update document metadata (admin/reviewer only)
 */
export async function updateDocument(
  id: string,
  updates: Partial<{
    title: string;
    version: string;
    system: string;
    notes: string;
  }>
): Promise<Document> {
  // Convert camelCase to snake_case for database
  const dbUpdates: Record<string, unknown> = {};
  if (updates.title) dbUpdates.title = updates.title;
  if (updates.version) dbUpdates.version = updates.version;
  if (updates.system) dbUpdates.system = updates.system;
  if (updates.notes) dbUpdates.notes = updates.notes;
  
  const updated = await postgrestFetch<DocumentSummary[]>(
    `/documents?id=eq.${id}`,
    {
      method: 'PATCH',
      body: JSON.stringify(dbUpdates),
      headers: {
        'Prefer': 'return=representation',
      },
    }
  );
  
  if (!updated || updated.length === 0) {
    throw new Error('Document not found or update failed');
  }
  
  // Re-fetch from view to get computed fields
  return getDocumentById(id);
}

/**
 * Delete document (admin only)
 */
export async function deleteDocument(id: string): Promise<void> {
  await postgrestFetch<void>(`/documents?id=eq.${id}`, {
    method: 'DELETE',
  });
}
