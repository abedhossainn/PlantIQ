import type { Document } from "@/types";

/**
 * Mock document data for the ingestion pipeline
 */

export const mockDocuments: Document[] = [
  {
    id: "doc-1",
    title: "COMMON Module 3 Characteristics of LNG",
    version: "Rev 2.1",
    system: "LNG Processing",
    documentType: "Technical Manual",
    uploadedAt: "2026-02-15T10:30:00Z",
    uploadedBy: "Randy Holt",
    status: "approved",
    totalPages: 45,
    totalSections: 12,
    reviewProgress: 100,
    qaScore: 96,
    approvedAt: "2026-02-17T14:20:00Z",
    approvedBy: "Mike Chen",
    notes: "Primary reference document for LNG properties and handling procedures",
  },
  {
    id: "doc-2",
    title: "Cryogenic Pump System Operating Manual",
    version: "3.4.2",
    system: "Liquefaction Train",
    documentType: "Operating Manual",
    uploadedAt: "2026-02-18T08:15:00Z",
    uploadedBy: "Laura Garcia",
    status: "in-review",
    totalPages: 128,
    totalSections: 24,
    reviewProgress: 58,
    qaScore: undefined,
    notes: "Currently under technical review - sections 1-14 complete",
  },
  {
    id: "doc-3",
    title: "Emergency Shutdown System P&ID",
    version: "2024-A",
    system: "Safety Systems",
    documentType: "P&ID Diagram",
    uploadedAt: "2026-02-19T06:45:00Z",
    uploadedBy: "Randy Holt",
    status: "validation-complete",
    totalPages: 8,
    totalSections: 4,
    reviewProgress: 0,
    notes: "VLM validation complete, ready for engineering review",
  },
  {
    id: "doc-4",
    title: "Gas Turbine Compressor Maintenance Guide",
    version: "8.1",
    system: "Compression System",
    documentType: "Maintenance Manual",
    uploadedAt: "2026-02-19T07:00:00Z",
    uploadedBy: "Randy Holt",
    status: "vlm-validating",
    totalPages: 312,
    totalSections: 48,
    reviewProgress: 0,
    notes: "Large document - VLM processing in progress",
  },
  {
    id: "doc-5",
    title: "Heat Exchanger Troubleshooting Procedures",
    version: "1.2",
    system: "Heat Transfer",
    documentType: "Troubleshooting Guide",
    uploadedAt: "2026-02-16T13:20:00Z",
    uploadedBy: "Sarah Smith",
    status: "rejected",
    totalPages: 67,
    totalSections: 15,
    reviewProgress: 45,
    qaScore: 72,
    notes: "Rejected - QA score below threshold. Table extraction fidelity issues.",
  },
  {
    id: "doc-6",
    title: "Instrumentation Calibration Standards",
    version: "5.0",
    system: "Instrumentation",
    documentType: "Technical Standard",
    uploadedAt: "2026-02-14T11:00:00Z",
    uploadedBy: "Alex Williams",
    status: "approved",
    totalPages: 92,
    totalSections: 18,
    reviewProgress: 100,
    qaScore: 98,
    approvedAt: "2026-02-16T09:30:00Z",
    approvedBy: "Laura Garcia",
    notes: "High-quality extraction, approved for RAG ingestion",
  },
  {
    id: "doc-7",
    title: "Electrical Switchgear Specifications",
    version: "2.8",
    system: "Electrical Distribution",
    documentType: "Technical Specification",
    uploadedAt: "2026-02-19T07:10:00Z",
    uploadedBy: "Randy Holt",
    status: "review-complete",
    totalPages: 156,
    totalSections: 28,
    reviewProgress: 100,
    notes: "All sections reviewed and verified — ready for QA gate assessment",
  },
];

/**
 * Helper function to get document by ID
 */
export function getDocumentById(id: string): Document | undefined {
  return mockDocuments.find((d) => d.id === id);
}

/**
 * Helper function to get documents by status
 */
export function getDocumentsByStatus(status: Document["status"]): Document[] {
  return mockDocuments.filter((d) => d.status === status);
}

/**
 * Helper function to get documents requiring  action
 */
export function getDocumentsRequiringReview(): Document[] {
  return mockDocuments.filter(
    (d) => d.status === "validation-complete" || d.status === "in-review"
  );
}

/**
 * Helper function to get approved documents for RAG
 */
export function getApprovedDocuments(): Document[] {
  return mockDocuments.filter((d) => d.status === "approved");
}
