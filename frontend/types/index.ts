/**
 * Type Definitions for PlantIQ Prototype
 * Air-Gapped Document Retrieval - Cove Point LNG
 */

export interface User {
  id: string;
  username: string;
  email: string;
  fullName: string;
  role: "admin" | "user";
  lastLogin: string | null;
  status: "active" | "disabled";
  department: string;
}

export type DocumentStatus =
  | "pending"
  | "uploading"
  | "extracting"
  | "vlm-validating"
  | "validation-complete"
  | "in-review"
  | "review-complete"
  | "approved-for-optimization"
  | "optimizing"
  | "optimization-complete"
  | "qa-review"
  | "qa-passed"
  | "final-approved"
  | "approved"
  | "rejected"
  | "failed";

export interface Document {
  id: string;
  title: string;
  version: string;
  system: string;
  documentType: string;
  uploadedAt: string;
  uploadedBy: string;
  status: DocumentStatus;
  totalPages: number;
  totalSections: number;
  reviewProgress: number;
  qaScore?: number;
  approvedAt?: string;
  approvedBy?: string;
  notes?: string;
}

export interface Citation {
  id: string;
  documentId: string;
  documentTitle: string;
  sectionHeading: string;
  pageNumber: number;
  workspace?: string;
  system?: string;
  documentType?: string;
  excerpt: string;
  relevanceScore: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  workspace?: string;
  citations?: Citation[];
}

export interface Conversation {
  id: string;
  userId: string;
  title: string;
  isPinned?: boolean;
  messageCount?: number;
  lastMessageAt?: string | null;
  lastMessagePreview?: string | null;
  workspace?: string;
  documentTypeFilters?: string[];
  preferredDocumentTypes?: string[];
  includeSharedDocuments?: boolean;
  messages: ChatMessage[];
  createdAt: string;
  updatedAt: string;
}

export interface Bookmark {
  id: string;
  userId: string;
  conversationId: string;
  messageId: string;
  query: string;
  answer: string;
  citations?: Citation[];
  tags?: string[];
  notes?: string;
  createdAt: string;
}

export interface ReviewChecklist {
  textAccuracyConfirmed: boolean;
  tablesVerified: boolean;
  imagesDescribed: boolean;
  formattingCorrect: boolean;
  technicalTermsAccurate: boolean;
}

export interface SectionVersion {
  content: string;
  timestamp: string;
  reviewedBy?: string;
}

export interface DocumentSection {
  id: string;
  documentId: string;
  sectionNumber: number;
  heading: string;
  content: string;
  status: "pending" | "draft" | "in-review" | "complete" | "needs-revision" | "flagged";
  checklist: ReviewChecklist;
  evidenceImages: string[];
  pageRange: { start: number; end: number };
  currentVersion?: SectionVersion;
  lastApprovedVersion?: SectionVersion;
  issues: ValidationIssue[];
}

export interface ValidationIssue {
  id: string;
  page: number;
  category: "missing-text" | "table-fidelity" | "image-loss" | "formatting" | "semantic-mismatch";
  severity: "critical" | "high" | "medium" | "low";
  description: string;
  evidenceImageUrl: string;
  context: string;
}

export interface ValidationReport {
  documentId: string;
  overallConfidence: number;
  totalIssues: number;
  criticalIssues: number;
  highIssues: number;
  mediumIssues: number;
  lowIssues: number;
  issues: ValidationIssue[];
  generatedAt: string;
}

export interface QAMetric {
  name: string;
  score: number;
  threshold: number;
  status: "pass" | "fail" | "warning";
  details?: string;
}

export interface QAGateReport {
  documentId: string;
  metrics: Record<string, QAMetric>;
  recommendation: "accept" | "reject" | "conditional";
  failingCriteria: string[];
  generatedAt: string;
}

// --------------- Optimized chunk types (post-optimization review unit) -----------

export interface OptimizedChunk {
  id: string;
  chunk_number: number;
  heading: string;
  markdown_content: string;
  text_preview: string;
  source_pages: number[];
  table_facts: string[];
  ambiguity_flags: string[];
}

export interface DocumentOptimizedChunksResponse {
  document_name: string;
  review_unit: "optimized_chunk";
  chunks: OptimizedChunk[];
}

export interface OptimizedChunkUpdate {
  heading: string;
  markdown_content: string;
  table_facts: string[];
  ambiguity_flags: string[];
}

// --------------- Page-based review types (canonical review unit) -----------------

export interface PageChecklistItem {
  item: string;
  checked: boolean;
  notes?: string | null;
}

export interface PageChecklist {
  question_headings: PageChecklistItem;
  table_facts_extracted: PageChecklistItem;
  figure_descriptions: PageChecklistItem;
  citations_present: PageChecklistItem;
  no_hallucinations: PageChecklistItem;
  rag_optimized: PageChecklistItem;
}

export interface PageValidationIssue {
  issue_type: string;
  severity: string;
  page_number: number;
  description: string;
  evidence: string;
  suggested_fix: string;
}

export interface PageEvidence {
  page_number: number;
  text_preview: string;
  image_count: number;
  table_count: number;
  has_figures: boolean;
  thumbnail_url?: string | null;
  thumbnail_path?: string | null;
}

export interface ReviewPage {
  id: string;
  page_number: number;
  status: string;
  markdown_content: string;
  text_preview: string;
  validation_issues: PageValidationIssue[];
  evidence_images: string[];
  evidence: PageEvidence;
  checklist: PageChecklist;
}

export interface ReviewProgress {
  total_pages: number;
  reviewed_pages: number;
  pending_pages: number;
  completion_percentage: number;
  by_status: Record<string, number>;
}

export interface DocumentPagesResponse {
  document_name: string;
  review_unit: "page";
  pages: ReviewPage[];
  progress: ReviewProgress;
}
