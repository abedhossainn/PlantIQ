/**
 * Pipeline API - Shared Type Definitions
 *
 * Contains all exported interfaces and type aliases used by the pipeline
 * sub-modules (upload, ingestion SSE, optimization SSE).
 */

import type { DocumentStatus } from '@/types';

// PipelineStatus values are sourced from shared DocumentStatus union.
// Keep this alias instead of duplicating string unions to avoid drift.
//
// Lifecycle reference (common progression):
// pending -> uploading -> extracting -> vlm-validating -> validation-complete
// -> in-review -> review-complete -> approved-for-optimization -> optimizing
// -> optimization-complete -> qa-review -> qa-passed -> final-approved
//
// Terminal/error branches can include rejected/failed depending on stage outcome.
// Frontend should always treat backend-reported status as authoritative.
export type PipelineStatus = DocumentStatus;

export type ArtifactType =
  | 'validation'
  | 'manifest'
  | 'qa-report'
  | 'qa_report'
  | 'review'
  | 'table_figure'
  | 'audit';

export interface DocumentUploadRequest {
  file: File;
  title: string;
  version?: string;
  system?: string;
  documentType?: string;
  notes?: string;
}

export interface DocumentUploadResponse {
  document_id: string;
  status: PipelineStatus;
  file_path: string;
  message: string;
}

export interface PipelineStatusResponse {
  document_id: string;
  status: PipelineStatus;
  current_stage?: string;
  progress: number; // 0-100
  message?: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
}

export interface ReprocessRequest {
  document_id: string;
  reason?: string;
}

export interface ReprocessResponse {
  job_id: string;
  document_id: string;
  status: PipelineStatus;
  message: string;
}
