/**
 * Type Definitions for PlantIQ Prototype
 * Air-Gapped Document Retrieval - Cove Point LNG
 */

export interface User {
  id: string;
  username: string;
  email: string;
  fullName: string;
  role: "admin" | "reviewer" | "user";
  lastLogin: string | null;
  status: "active" | "disabled";
  department: string;
}

export interface Document {
  id: string;
  title: string;
  version: string;
  system: string;
  documentType: string;
  uploadedAt: string;
  uploadedBy: string;
  status:
    | "pending"
    | "uploading"
    | "extracting"
    | "vlm-validating"
    | "validation-complete"
    | "in-review"
    | "review-complete"
    | "approved"
    | "rejected";
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
  excerpt: string;
  relevanceScore: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  citations?: Citation[];
}

export interface Conversation {
  id: string;
  userId: string;
  title: string;
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
