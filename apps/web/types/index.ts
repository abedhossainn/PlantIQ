/**
/**
 * Type Definitions for PlantIQ Frontend
 * Air-Gapped RAG System for Cove Point LNG Facility Operations
 * 
 * Core Entities:
 * - User: Authenticated user profile from FastAPI /auth/me endpoint
 * - Document: PDF document in ingestion pipeline with lifecycle stages
 * - Citation: Reference source (document chunk) cited in RAG response
 * - ChatMessage: Single message in conversation (user query or assistant response)
 * - Conversation: Thread of chat messages with scope filters (workspace, doc types)
 * - Bookmark: Saved Q&A pair for later review or knowledge base building
 * 
 * Data Flow:
 * 1. User logs in → User profile fetched from FastAPI
 * 2. User uploads document → Document created in PENDING status
 * 3. Document processed through pipeline → Status progresses through stages
 * 4. User starts conversation → Conversation created, messages appended
 * 5. User submits query → FastAPI returns Citations from vector search
 * 6. LLM generates response → Response streamed with interleaved Citations
 * 7. User bookmarks Q&A → Bookmark saved to PostgREST for knowledge base
 * 
 * Domain glossary:
 * - Workspace: Plant area used as retrieval filter (e.g., Liquefaction, Electrical).
 * - Document Type: Operational classification used for retrieval narrowing.
 * - Citation: Source chunk metadata paired with generated answer content.
 * - Review Progress: Percent completion of human document review process.
 * - QA Score: Composite quality signal produced in QA stage.
 * - Final Approved: Document is eligible for retrieval in production chat context.
 * 
 * Modeling conventions:
 * - Backend payloads often use snake_case; frontend domain models use camelCase.
 * - Optional fields represent stage-dependent availability.
 * - Timestamps are ISO-8601 strings for stable serialization.
 * - IDs are treated as opaque strings (UUID-compatible).
 * - Keep type changes synchronized with backend schema evolution.
 * - Prefer additive changes to preserve backward compatibility.
 */

export interface User {
   // Authenticated user profile from POST /auth/login → GET /auth/me
   // Includes role-based access control (admin vs user)
   // department field supports workspace-level filtering + audit logging
  id: string;
  username: string;
  email: string;
  fullName: string;
  role: "admin" | "reviewer" | "plantig_admin" | "plantig_reviewer" | "user";
  lastLogin: string | null;
  status: "active" | "disabled";
  department: string;
}

export type DocumentStatus =
   // Pipeline stages for document ingestion:
   // UPST REAM: pending → uploading → extracting (Docling text/table/figure extraction)
   // REVIEW: vlm-validating → validation-complete (Vision-Language Model checks fidelity)
   // OPTIMIZATION: approved-for-optimization → optimizing → optimization-complete (LLM-powered)
   // QA: qa-review → qa-passed (Automated metrics + human sign-off)
   // TERMINAL: approved (ready for RAG) | rejected (human review failed) | failed (error)
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
   // Document in database: combines pipeline metadata + user metadata
   // Lifecycle: User uploads PDF → goes through HITL stages → approved for RAG
   // totalPages/totalSections: Extracted by Docling, displayed in inventory
   // qaScore: Relevance/quality metric from metrics.json (optional, only if QA passed)
   // status: Maps to DocumentStatus enum for UI rendering
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
   // Result from RAG vector search: document chunk returned by Qdrant + metadata
   // Used in two contexts:
   //   1. Embedded in ChatMessage.citations (parsed from _citations field in database)
   //   2. Emitted as CitationSSEEvent during streaming (sent separately from tokens)
   // relevanceScore: Semantic similarity from Qdrant distance metric (cosine similarity)
   // excerpts + pageNumber: Allow users to jump to source in document detail view
  id: string;
  documentId: string;
  documentTitle: string;
  sectionHeading: string;
  pageNumber: number;
  workspace?: string;
  system?: string;
  /** @deprecated Document type scope is removed from UI (Candidate 5). Field retained for backward compat only. */
  documentType?: string;
  excerpt: string;
  relevanceScore: number;
}

export interface ChatMessage {
   // Single message in conversation thread
   // role: "user" (Query from user input) | "assistant" (Response from LLM)
   // content: Plain text (markdown supported for assistant messages)
   // citations: Sources cited in response (populated by backend or SSE stream)
   // workspace: Optional filter applied during query (for context/audit)
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  workspace?: string;
  citations?: Citation[];
}

export interface Conversation {
   // Conversation thread: collection of ChatMessages + metadata
   // Scope filters (workspace, documentTypeFilters): Applied to all queries in this conversation
   // isPinned: User-selected persistence (pinned first in UI list)
   // messageCount/lastMessageAt: From PostgREST view for efficient discovery
   // includeSharedDocuments: Boolean flag to include/exclude shared document scope
   // createdAt/updatedAt: Timestamps for auditing + freshness detection
  id: string;
  userId: string;
  title: string;
  isPinned?: boolean;
  messageCount?: number;
  lastMessageAt?: string | null;
  lastMessagePreview?: string | null;
  workspace?: string;
  /** @deprecated Document type filters removed from UI (Candidate 5). Retained for reading legacy conversations only. */
  documentTypeFilters?: string[];
  /** @deprecated Preferred document types removed from UI (Candidate 5). Retained for reading legacy conversations only. */
  preferredDocumentTypes?: string[];
  includeSharedDocuments?: boolean;
  messages: ChatMessage[];
  createdAt: string;
  updatedAt: string;
}

export interface Bookmark {
   // Saved Q&A pair: user-curated knowledge base entry
   // Can be tagged for organization + discovery
   // Links to original message in conversation (for context retrieval)
   // Can be exported/shared for training or knowledge base seeding
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
  source_type: "pdf" | "xlsx";
  skip_optimized_review: boolean;
  next_route?: string | null;
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
