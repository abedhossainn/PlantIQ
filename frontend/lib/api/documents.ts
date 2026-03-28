/**
 * Documents API
 * Handles document metadata retrieval from the FastAPI pipeline service.
 */

import { fastapiFetch, getFastApiBaseUrl } from './client';
import type { Document, DocumentPagesResponse } from '../../types';
import { isQAQueueStatus, isReviewQueueStatus } from '../document-status';

export interface DocumentDeleteResponse {
  document_id: string;
  qdrant_chunks_deleted: boolean;
  deleted_paths: string[];
  message: string;
}


/**
 * Get all documents from the FastAPI pipeline service.
 * Falls back to empty array if the endpoint is unavailable.
 */
export async function getDocuments(filters?: {
  status?: Document['status'];
  system?: string;
  limit?: number;
  offset?: number;
}): Promise<Document[]> {
  interface FastAPIDocument {
    id: string;
    title: string;
    version: string;
    system: string;
    documentType: string;
    status: string;
    uploadedBy: string;
    uploadedAt: string | null;
    notes?: string;
    totalPages?: number | null;
    totalSections?: number | null;
    reviewProgress?: number | null;
    qaScore?: number | null;
    approvedBy?: string | null;
    approvedAt?: string | null;
  }

  const rows = await fastapiFetch<FastAPIDocument[]>('/api/v1/documents');

  let docs = rows.map((row): Document => ({
    id: row.id,
    title: row.title,
    version: row.version,
    system: row.system,
    documentType: row.documentType,
    status: row.status as Document['status'],
    totalPages: row.totalPages ?? 0,
    totalSections: row.totalSections ?? 0,
    reviewProgress: row.reviewProgress ?? 0,
    qaScore: row.qaScore ?? undefined,
    uploadedBy: row.uploadedBy,
    uploadedAt: row.uploadedAt ?? new Date().toISOString(),
    approvedBy: row.approvedBy ?? undefined,
    approvedAt: row.approvedAt ?? undefined,
    notes: row.notes,
  }));

  if (filters?.status) {
    docs = docs.filter((d) => d.status === filters.status);
  }
  if (filters?.system) {
    docs = docs.filter((d) => d.system === filters.system);
  }
  if (filters?.offset) {
    docs = docs.slice(filters.offset);
  }
  if (filters?.limit) {
    docs = docs.slice(0, filters.limit);
  }

  return docs;
}

/**
 * Get documents in review queue (validation-complete or in-review)
 */
export async function getReviewQueueDocuments(): Promise<Document[]> {
  const all = await getDocuments();
  return all.filter((d) => isReviewQueueStatus(d.status));
}

/**
 * Get documents ready for QA gates (review-complete)
 */
export async function getQAGateDocuments(): Promise<Document[]> {
  const all = await getDocuments();
  return all.filter((d) => isQAQueueStatus(d.status));
}

/**
 * Get only final-approved documents.
 */
export async function getFinalApprovedDocuments(): Promise<Document[]> {
  const all = await getDocuments();
  return all.filter((d) => d.status === "final-approved");
}

/**
 * Get all pending documents (every status except final-approved).
 */
export async function getPendingDocuments(): Promise<Document[]> {
  const all = await getDocuments();
  return all.filter((d) => d.status !== "final-approved");
}

/**
 * Get single document by ID — looks it up from the full list.
 */
export async function getDocumentById(id: string): Promise<Document> {
  const all = await getDocuments();
  const doc = all.find((d) => d.id === id);
  if (!doc) throw new Error(`Document ${id} not found`);
  return doc;
}

/**
 * Get page-based review units for a document.
 * Canonical review endpoint superseding the legacy /sections route.
 */
export async function getDocumentPages(documentId: string): Promise<DocumentPagesResponse> {
  return fastapiFetch<DocumentPagesResponse>(`/api/v1/documents/${documentId}/pages`);
}

/**
 * Permanently delete a document and all associated backend artifacts.
 */
export async function deleteDocument(documentId: string): Promise<DocumentDeleteResponse> {
  return fastapiFetch<DocumentDeleteResponse>(`/api/v1/documents/${documentId}`, {
    method: 'DELETE',
  });
}

/**
 * Build the thumbnail URL for a specific page.
 */
export function getPageThumbnailUrl(documentId: string, pageNumber: number): string {
  return `${getFastApiBaseUrl()}/api/v1/documents/${documentId}/pages/${pageNumber}/thumbnail`;
}
