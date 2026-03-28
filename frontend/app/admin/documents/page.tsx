"use client";

import { Suspense, useState, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Card } from "@/components/ui/card";
import {
  Upload, FileText, CheckCircle2, XCircle, Clock, Loader2, AlertCircle,
  ChevronRight, FileClock, BarChart3, ShieldCheck, Trash2
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, deleteDocument, getFinalApprovedDocuments, getPendingDocuments } from "@/lib/api";
import type { Document } from "@/types";
import { isQAQueueStatus } from "@/lib/document-status";

const STATUS_CONFIG: Record<
  string,
  { label: string; badgeClass: string; icon: React.ReactNode; action?: string; actionLabel?: string }
> = {
  approved: {
    label: "Approved",
    badgeClass: "text-green-400 bg-green-400/10 border-green-400/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
    action: "approve",
    actionLabel: "View Approval",
  },
  rejected: {
    label: "Rejected",
    badgeClass: "text-red-400 bg-red-400/10 border-red-400/30",
    icon: <XCircle className="h-3 w-3" />,
    action: "approve",
    actionLabel: "View Details",
  },
  "final-approved": {
    label: "Final Approved",
    badgeClass: "text-green-400 bg-green-400/10 border-green-400/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
    action: "approve",
    actionLabel: "View Approval",
  },
  "review-complete": {
    label: "Review Complete",
    badgeClass: "text-blue-400 bg-blue-400/10 border-blue-400/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
    action: "qa-gates",
    actionLabel: "Open QA Gates",
  },
  "approved-for-optimization": {
    label: "Approved for Optimization",
    badgeClass: "text-sky-400 bg-sky-400/10 border-sky-400/30",
    icon: <Clock className="h-3 w-3" />,
    action: "qa-gates",
    actionLabel: "Track Optimization",
  },
  optimizing: {
    label: "Optimizing",
    badgeClass: "text-purple-400 bg-purple-400/10 border-purple-400/30",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    action: "qa-gates",
    actionLabel: "Track Optimization",
  },
  "optimization-complete": {
    label: "Optimization Complete",
    badgeClass: "text-blue-400 bg-blue-400/10 border-blue-400/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
    action: "optimized-review",
    actionLabel: "Review Optimized Output",
  },
  "qa-review": {
    label: "QA Review",
    badgeClass: "text-indigo-400 bg-indigo-400/10 border-indigo-400/30",
    icon: <ShieldCheck className="h-3 w-3" />,
    action: "qa-gates",
    actionLabel: "Continue QA",
  },
  "qa-passed": {
    label: "QA Passed",
    badgeClass: "text-emerald-400 bg-emerald-400/10 border-emerald-400/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
    action: "approve",
    actionLabel: "Final Approval",
  },
  "in-review": {
    label: "In Review",
    badgeClass: "text-amber-400 bg-amber-400/10 border-amber-400/30",
    icon: <Clock className="h-3 w-3" />,
    action: "review",
    actionLabel: "Continue Review",
  },
  "validation-complete": {
    label: "Validation Complete",
    badgeClass: "text-cyan-400 bg-cyan-400/10 border-cyan-400/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
    action: "review",
    actionLabel: "Start Review",
  },
  "vlm-validating": {
    label: "Validating",
    badgeClass: "text-purple-400 bg-purple-400/10 border-purple-400/30",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    actionLabel: "Processing…",
  },
  uploaded: {
    label: "Uploaded",
    badgeClass: "text-zinc-400 bg-zinc-400/10 border-zinc-400/30",
    icon: <AlertCircle className="h-3 w-3" />,
    actionLabel: "Awaiting Validation",
  },
};

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
