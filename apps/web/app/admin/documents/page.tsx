"use client";

/**
 * Document Inventory & Queue Management Dashboard
 *
 * Purpose:
 * - Central operational view for all uploaded documents in the pipeline.
 * - Separates documents by lifecycle state (pending, in-progress, approved, rejected).
 * - Provides direct navigation to the correct stage-specific page per document.
 * - Supports admin triage actions like delete, open queue views, and progress tracking.
 *
 * Data Sources:
 * - FastAPI pipeline service for pending and active statuses.
 * - Final approved list endpoint for production-ready RAG documents.
 * - Client-side status helpers from document-status.ts for consistent gating logic.
 *
 * Status Routing:
 * - Each status maps to an action route (review, qa-gates, optimized-review, approve, etc.).
 * - STATUS_CONFIG centralizes labels, badges, icons, and CTA text to avoid duplicate mapping.
 * - Unknown statuses fall back to neutral display, preserving resiliency to backend changes.
 *
 * Operational UX:
 * - Pending-documents view highlights queue urgency and handoff points.
 * - Progress bars communicate stage completion where numeric progress exists.
 * - Badge/icon semantics provide at-a-glance health for operators.
 *
 * Error Handling:
 * - API errors are surfaced with user-readable messages.
 * - Defensive rendering for partial records prevents table crashes.
 * - Delete flow catches and reports failures while keeping list state consistent.
 *
 * Why this file is large:
 * - Consolidates status taxonomy, table rendering, and queue-specific controls in one page.
 * - Avoids fragmented navigation logic across multiple thin wrappers.
 */

import { Suspense, useState, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Card } from "@/components/ui/card";
import {
  Upload, FileText, Loader2, AlertCircle,
  ChevronRight, FileClock, BarChart3, ShieldCheck, Trash2
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, deleteDocument, getFinalApprovedDocuments, getPendingDocuments } from "@/lib/api";
import type { Document } from "@/types";
import { STATUS_CONFIG } from "./_status-config";
import { isQAQueueStatus } from "@/lib/document-status";

// ---------------------------------------------------------------------------
// Status Taxonomy Reference
// ---------------------------------------------------------------------------
// Ingestion / early pipeline
// - pending
// - uploading
// - extracting
// - vlm-validating
// - validation-complete
//
// Human review and optimization
// - in-review
// - review-complete
// - approved-for-optimization
// - optimizing
// - optimization-complete
//
// QA and release gates
// - qa-review
// - qa-passed
// - final-approved
//
// Terminal outcomes
// - approved
// - rejected
// - failed
//
// UX mapping goals:
// - Ensure every status has a deterministic badge/icon/action.
// - Keep action labels stage-appropriate and reviewer-friendly.
// - Prefer explicit handling over hidden implicit fallbacks.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Dashboard QA Checklist
// ---------------------------------------------------------------------------
// Data loading checks:
// - Pending and approved queries both execute successfully.
// - Partial API failures do not blank out existing successful sections.
// - Empty-state messaging is shown when no records are returned.
//
// Status display checks:
// - Every known status renders icon + badge + label.
// - Unknown statuses render safely without runtime errors.
// - Progress values stay clamped to [0,100] in UI components.
//
// Action routing checks:
// - review-complete routes to QA gates.
// - optimization-complete routes to optimized review.
// - qa-passed routes to final approval.
// - terminal statuses route to read-only relevant pages.
//
// Mutating action checks:
// - Delete action confirms intent and reports failures clearly.
// - Optimistic row removal is reconciled with backend response.
// - Navigation actions preserve selected view parameters.
//
// Accessibility checks:
// - Table headers remain descriptive.
// - Action buttons have readable labels and icon affordances.
// - Status colors are supplemented with text labels.
// ---------------------------------------------------------------------------

function DocumentsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const view = searchParams?.get("view") ?? "";
  
  const [docs, setDocs] = useState<Document[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);

  // Fetch documents based on view
  useEffect(() => {
    async function fetchDocuments() {
      setIsLoading(true);
      setError(null);
      try {
        let documents: Document[];
        if (view === "pending-documents") {
          documents = await getPendingDocuments();
        } else {
          documents = await getFinalApprovedDocuments();
        }
        setDocs(documents);
      } catch (err) {
        console.error('Failed to fetch documents:', err);
        setError(err instanceof Error ? err.message : 'Failed to load documents');
      } finally {
        setIsLoading(false);
      }
    }

    fetchDocuments();
  }, [view]);

  // Page title/description based on view
  const pageTitle =
    view === "pending-documents" ? "Pending Documents" : "Final Approved Documents";

  const pageDesc =
    view === "pending-documents"
      ? "All documents not yet in final-approved status"
      : "Only final-approved documents available for production use";

  function handleAction(doc: Document) {
    const cfg = STATUS_CONFIG[doc.status];
    if (cfg?.action) {
      if (cfg.action === "ingestion") {
        router.push(`/admin/documents/upload?documentId=${encodeURIComponent(doc.id)}`);
        return;
      }
      router.push(`/admin/documents/${doc.id}/${cfg.action}`);
    }
  }

  async function handleDelete(doc: Document) {
    const confirmed = window.confirm(
      `Delete "${doc.title}" permanently? This removes the document from the database, vector storage, and generated artifacts.`
    );

    if (!confirmed) {
      return;
    }

    setDeletingDocId(doc.id);
    setError(null);

    try {
      await deleteDocument(doc.id);
      setDocs((currentDocs) => currentDocs.filter((currentDoc) => currentDoc.id !== doc.id));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(`Cannot delete "${doc.title}" while processing is still running.`);
      } else {
        setError(err instanceof Error ? err.message : `Failed to delete "${doc.title}"`);
      }
    } finally {
      setDeletingDocId(null);
    }
  }

  const stats = [
    {
      label: "In Pipeline",
      count: docs.filter((d) => !["approved", "final-approved", "rejected"].includes(d.status)).length,
      color: "text-amber-400",
      icon: <FileClock className="h-5 w-5 text-amber-400" />,
    },
    {
      label: "In Review",
      count: docs.filter((d) => d.status === "in-review").length,
      color: "text-blue-400",
      icon: <FileText className="h-5 w-5 text-blue-400" />,
    },
    {
      label: "Approved",
      count: docs.filter((d) => d.status === "approved" || d.status === "final-approved").length,
      color: "text-green-400",
      icon: <ShieldCheck className="h-5 w-5 text-green-400" />,
    },
    {
      label: "Avg QA Score",
      count:
        docs.filter((d) => d.qaScore !== undefined).length > 0
          ? Math.round(
              docs.filter((d) => d.qaScore !== undefined).reduce((a, d) => a + (d.qaScore ?? 0), 0) /
                docs.filter((d) => d.qaScore !== undefined).length
            ) + "%"
          : "—",
      color: "text-primary",
      icon: <BarChart3 className="h-5 w-5 text-primary" />,
    },
  ];

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col h-full min-h-0">
        {/* Header */}
        <div className="border-b border-border px-6 py-5 flex items-center justify-between bg-card/50">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{pageTitle}</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              {pageDesc}
            </p>
          </div>
          <Button onClick={() => router.push("/admin/documents/upload")} className="gap-2 font-semibold">
            <Upload className="h-4 w-4" />
            Upload Document
          </Button>
        </div>

        {/* Stats bar */}
        <div className="border-b border-border px-6 py-4 bg-card/30">
          <div className="flex items-center gap-8">
            {stats.map((s) => (
              <div key={s.label} className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted border border-border shrink-0">
                  {s.icon}
                </div>
                <div>
                  <p className={`text-xl font-bold leading-none ${s.color}`}>{s.count}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{s.label}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {error && (
          <div className="px-6 pt-4">
            <Card className="p-4 border-red-400/50 bg-red-400/5">
              <div className="flex items-center gap-3">
                <AlertCircle className="h-5 w-5 text-red-400" />
                <div>
                  <p className="font-semibold text-red-400">Failed to load documents</p>
                  <p className="text-sm text-muted-foreground mt-1">{error}</p>
                </div>
              </div>
            </Card>
          </div>
        )}

        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="p-6 max-w-7xl mx-auto">
            {isLoading ? (
              <Card className="p-12">
                <div className="flex flex-col items-center justify-center gap-3">
                  <Loader2 className="h-8 w-8 animate-spin text-primary" />
                  <p className="text-sm text-muted-foreground">Loading documents...</p>
                </div>
              </Card>
            ) : (
            <Card className="overflow-hidden border-border">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/60 hover:bg-muted/60 border-border">
                    <TableHead className="font-semibold text-foreground w-[260px]">Document</TableHead>
                    <TableHead className="font-semibold text-foreground">Type / System</TableHead>
                    <TableHead className="font-semibold text-foreground">Status</TableHead>
                    <TableHead className="font-semibold text-foreground text-center">Pages</TableHead>
                    <TableHead className="font-semibold text-foreground">Progress / Score</TableHead>
                    <TableHead className="font-semibold text-foreground">Uploaded Date</TableHead>
                    <TableHead className="font-semibold text-foreground text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {docs.map((doc) => {
                    const cfg = STATUS_CONFIG[doc.status] ?? STATUS_CONFIG.uploaded;
                    return (
                      <TableRow key={doc.id} className="border-border hover:bg-muted/30 transition-colors">
                        <TableCell className="py-4">
                          <div className="flex items-start gap-3">
                            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 border border-primary/20 mt-0.5">
                              <FileText className="h-4 w-4 text-primary" />
                            </div>
                            <div className="min-w-0">
                              <p className="font-semibold text-sm leading-tight line-clamp-2 max-w-[210px]">{doc.title}</p>
                              <p className="text-xs text-muted-foreground mt-0.5">v{doc.version} · {doc.totalSections} sections</p>
                            </div>
                          </div>
                        </TableCell>

                        <TableCell className="py-4">
                          <div>
                            <p className="text-sm font-medium">{doc.documentType}</p>
                            <p className="text-xs text-muted-foreground">{doc.system}</p>
                          </div>
                        </TableCell>

                        <TableCell className="py-4">
                          <Badge
                            variant="outline"
                            className={`gap-1.5 text-xs font-medium px-2.5 py-0.5 ${cfg.badgeClass}`}
                          >
                            {cfg.icon}
                            {cfg.label}
                          </Badge>
                        </TableCell>

                        <TableCell className="py-4 text-center">
                          <span className="text-sm font-medium">{doc.totalPages}</span>
                        </TableCell>

                        <TableCell className="py-4 min-w-[110px]">
                          {(doc.status === "in-review" || doc.status === "review-complete" || isQAQueueStatus(doc.status)) ? (
                            <div>
                              <div className="flex justify-between text-xs mb-1.5">
                                <span className="text-muted-foreground">
                                  {doc.status === "in-review" || doc.status === "review-complete" ? "Review" : "Pipeline"}
                                </span>
                                <span className="font-semibold">{doc.reviewProgress}%</span>
                              </div>
                              <Progress value={doc.reviewProgress} className="h-1.5" />
                            </div>
                          ) : doc.qaScore !== undefined ? (
                            <div>
                              <span
                                className={`text-base font-bold ${
                                  doc.qaScore >= 90 ? "text-green-400" : doc.qaScore >= 75 ? "text-amber-400" : "text-red-400"
                                }`}
                              >
                                {doc.qaScore}%
                              </span>
                              <p className="text-xs text-muted-foreground">QA Score</p>
                            </div>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TableCell>

                        <TableCell className="py-4">
                          <p className="text-xs text-muted-foreground">
                            {new Date(doc.uploadedAt).toLocaleDateString()}
                          </p>
                        </TableCell>

                        <TableCell className="py-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            {cfg.action ? (
                              <Button
                                size="sm"
                                className="gap-1.5 text-xs font-semibold h-8"
                                onClick={() => handleAction(doc)}
                              >
                                {cfg.actionLabel}
                                <ChevronRight className="h-3.5 w-3.5" />
                              </Button>
                            ) : (
                              <span className="text-xs text-muted-foreground px-1">{cfg.actionLabel}</span>
                            )}
                            <Button
                              size="sm"
                              variant="destructive"
                              className="gap-1.5 text-xs font-semibold h-8"
                              onClick={() => handleDelete(doc)}
                              disabled={deletingDocId === doc.id}
                            >
                              {deletingDocId === doc.id ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Trash2 className="h-3.5 w-3.5" />
                              )}
                              Delete
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              {docs.length === 0 && !isLoading && (
                <div className="text-center py-16 text-muted-foreground">
                  <FileText className="h-12 w-12 mx-auto mb-3 opacity-30" />
                  <p className="text-sm">
                    {view === "pending-documents"
                      ? "No pending documents at the moment"
                      : "No final-approved documents yet"}
                  </p>
                  {view !== "pending-documents" && (
                    <Button className="mt-4 gap-2" onClick={() => router.push("/admin/documents/upload")}>
                      <Upload className="h-4 w-4" />
                      Upload First Document
                    </Button>
                  )}
                </div>
              )}
            </Card>
            )}
          </div>
        </div>
      </div>
    </AppLayout>
  );
}

export default function DocumentsPage() {
  return (
    <Suspense
      fallback={
        <AppLayout>
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        </AppLayout>
      }
    >
      <DocumentsContent />
    </Suspense>
  );
}
