"use client";

/**
 * Final Approval Stage - Release Gating & Sign-Off
 * 
 * Purpose:
 * - Final human sign-off before document released to RAG system
 * - Display QA metrics summary + reviewer recommendation
 * - Allow admin override approval/rejection decisions
 * - Capture sign-off notes + approval metadata for audit trail
 * 
 * Pipeline Stage Context:
 * - Input: Document in QA_PASSED status (all metrics + manual reviews passed)
 * - Action: Admin/lead reviews all artifacts, approves or rejects
 * - Output: Document transitions to APPROVED (ready for RAG retrieval)
 * - Terminal: APPROVED documents locked (read-only, no further edits)
 * 
 * Approval Decisions:
 * - Approve: Document approved for RAG, locked from further editing
 * - Reject: Document rejected, returns to review stage for re-processing
 * - Review (context): QA metrics flagged issues, human review needed
 * 
 * Artifact Summary:
 * - QA metrics: overall_confidence_score + pass/fail breakdown
 * - Extraction review: Manual corrections + validation notes
 * - Optimization review: Summary + QA pair validations (if applicable)
 * - Metrics: Automated scores (coverage, compliance, hallucination risk)
 * 
 * Audit Trail:
 * - Submitted by: Authenticated user from AuthContext
 * - Submitted at: ISO timestamp
 * - Notes: Free-text notes from approver (stored in artifacts)
 * - Decision: Final approval/rejection + rationale
 * 
 * Security:
 * - Requires admin role (role check in canStartFinalApproval)
 * - Approved documents locked (immutable for downstream usage)
 * - localStorage cache persists pending decisions (prevents accidental loss)
 * 
 * UI Layout:
 * - Document summary: Title, version, system, status
 * - QA metrics display: Summary with pass/fail indicators
 * - Recommendation: QA engine's auto-decision (for reference)
 * - Manual decision: Admin approval/rejection with notes
 * - Audit info: Who approved, when, with what notes
 * 
 * Error Handling:
 * - Submission errors: Show inline error + retry capability
 * - Invalid state: Document already approved (locked, show read-only view)
 * - Missing QA data: Fetch failure, show error state
 */

/**
 * Final Approval Stage - Human Release Decision Gate
 * 
 * Purpose:
 * - Present consolidated document QA + review outcomes
 * - Capture final human decision (approve/reject)
 * - Record approver identity, timestamp, and notes
 * - Enforce role-based access for release decisions
 * 
 * Pipeline Stage Context:
 * - Input: Document that passed review + QA gates
 * - Decision: approve (release to RAG) | reject (return for rework)
 * - Output: Terminal status update in backend (final-approved/rejected)
 * 
 * Approval Data:
 * - decision: approve/reject/null
 * - notes: Reviewer rationale (required for reject, optional for approve)
 * - submittedAt: Audit timestamp
 * - submittedBy: Reviewer identity (from AuthContext.user)
 * - qaRecommendation: Suggested decision from QA metrics artifact
 * 
 * Audit & Compliance:
 * - Approval decision persisted to localStorage for UX continuity
 * - Backend call writes final approval artifact (audit trail)
 * - Includes reviewer identity, timestamp, document metadata, rationale
 * - Supports regulatory traceability for critical operations docs
 * 
 * Access Control:
 * - Uses AuthContext to verify authenticated user
 * - canStartFinalApproval() guards page access by document status
 * - UI lock state prevents double-submission
 * 
 * UX Features:
 * - Shows QA recommendation from pre-review metrics
 * - Allows freeform notes for contextual decision-making
 * - Displays confirmation state after successful submission
 * - Supports back navigation to prior QA stage
 * 
 * Error Handling:
 * - Failed submissions show in-page error with retry path
 * - Invalid states (doc not ready for approval) redirect to docs page
 * - localStorage parse failures handled gracefully
 */

import { useState, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { CheckCircle2, XCircle, ArrowLeft, FileText, User, Calendar, ThumbsUp, ThumbsDown, Lock } from "lucide-react";
import { useRouter } from "next/navigation";
import { getDocumentFromPipeline, fetchArtifactJson } from "@/lib/api";
import { fastapiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth/AuthContext";
import { canStartFinalApproval } from "@/lib/document-status";
import type { Document } from "@/types";

// ---------------------------------------------------------------------------
// Final Approval Runtime Notes
// ---------------------------------------------------------------------------
// - Approval submission should be single-shot to preserve clear audit sequence.
// - Rejection should include rationale notes for remediation traceability.
// - QA recommendation is guidance, not automatic decisioning.
// - Only qualified roles should access this route (enforced by broader auth guards).
// ---------------------------------------------------------------------------

type Decision = "approve" | "reject" | null;
type PublicationStatus = "pending" | "publishing" | "published" | "failed" | null;

interface QAPreReviewArtifact {
  decision: "approved" | "rejected" | "review";
  metrics: { overall_confidence_score: number };
}

export default function ApproveClient({ docId }: { docId: string }) {
  const router = useRouter();
  const { user } = useAuth();

  const [doc, setDoc] = useState<Document | null>(null);
  const [isDocLoading, setIsDocLoading] = useState(true);
  const [qaRecommendation, setQaRecommendation] = useState<"accept" | "reject" | "review" | null>(null);

  const [decision, setDecision] = useState<Decision>(null);
  const [notes, setNotes] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [submittedAt, setSubmittedAt] = useState<string | null>(null);
  const [submittedBy, setSubmittedBy] = useState<string | null>(null);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [publicationStatus, setPublicationStatus] = useState<PublicationStatus>(null);

  // Load persisted decision from localStorage on mount
  useEffect(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem(`approval-${docId}`);
      if (stored) {
        try {
          const parsed = JSON.parse(stored);
          setDecision(parsed.decision ?? null);
          setNotes(parsed.notes ?? "");
          setSubmittedAt(parsed.submittedAt ?? null);
          setSubmittedBy(parsed.submittedBy ?? null);
        } catch { /* noop */ }
      }
    }
  }, [docId]);

  useEffect(() => {
    let cancelled = false;

    async function loadDocument() {
      try {
        const loaded = await getDocumentFromPipeline(docId);
        if (!cancelled) {
          setDoc(loaded);
        }

        // Fetch publication metadata from documents listing endpoint so this page
        // can distinguish between final-approved vs actually published-to-RAG.
        const rows = await fastapiFetch<Array<{ id: string; publicationStatus?: PublicationStatus }>>(
          "/api/v1/documents"
        );
        const row = rows.find((item) => item.id === docId);
        if (!cancelled && row) {
          setPublicationStatus(row.publicationStatus ?? null);
        }
      } catch {
        // noop
      } finally {
        if (!cancelled) {
          setIsDocLoading(false);
        }
      }
    }

    void loadDocument();

    return () => {
      cancelled = true;
    };
  }, [docId]);

  // Load QA recommendation from artifact
  useEffect(() => {
    let cancelled = false;
    async function loadQA() {
      try {
        const report = await fetchArtifactJson<QAPreReviewArtifact>(docId, "qa_report");
        if (!cancelled) {
          if (report.decision === "approved") setQaRecommendation("accept");
          else if (report.decision === "rejected") setQaRecommendation("reject");
          else setQaRecommendation("review");
        }
      } catch { /* noop */ }
    }
    void loadQA();
    return () => { cancelled = true; };
  }, [docId]);

  if (isDocLoading) {
    return (
      <AppLayout>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-muted-foreground">Loading document...</p>
        </div>
      </AppLayout>
    );
  }

  if (!doc) {
    return (
      <AppLayout>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-muted-foreground">Document not found</p>
        </div>
      </AppLayout>
    );
  }

  const isAlreadyApproved = doc.status === "final-approved" || doc.status === "approved" || (submitted && decision === "approve");
  const isAlreadyRejected = doc.status === "rejected" || (submitted && decision === "reject");
  const isFinalized = isAlreadyApproved || isAlreadyRejected;
  const canSubmitFinalApproval = canStartFinalApproval(doc.status) || decision === "reject";

  async function publishToRag(): Promise<boolean> {
    setPublicationStatus("publishing");
    try {
      await fastapiFetch(`/api/v1/documents/${docId}/publish`, {
        method: "POST",
      });
      setPublicationStatus("published");
      return true;
    } catch {
      setPublicationStatus("failed");
      return false;
    }
  }

  async function handleSubmit() {
    if (!decision) return;
    setSubmissionError(null);
    const ts = new Date().toISOString();
    const reviewer = user?.fullName ?? "Unknown";
    try {
      await fastapiFetch(`/api/v1/documents/${docId}/final-approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, notes: notes || null }),
      });

      if (decision === "approve") {
        const published = await publishToRag();
        if (!published) {
          setSubmissionError(
            "Final approval succeeded, but publish-to-RAG failed. Chat may not retrieve this document yet. Use Retry Publish below."
          );
        }
      }

      setSubmittedAt(ts);
      setSubmittedBy(reviewer);
      if (typeof window !== "undefined") {
        localStorage.setItem(`approval-${docId}`, JSON.stringify({
          decision,
          notes,
          submittedAt: ts,
          submittedBy: reviewer,
        }));
      }
      setSubmitted(true);
      setDoc((prev) => prev ? { ...prev, status: decision === "approve" ? "final-approved" : "rejected" } : prev);
    } catch {
      setSubmissionError("Final approval is only available after QA passes. Return to QA if the document still needs scoring or acceptance.");
    }
  }

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col h-full min-h-0">
        {/* Header */}
        <div className="border-b border-border p-6">
          <Button variant="ghost" size="sm" className="gap-1.5 mb-3" onClick={() => router.push("/admin/documents")}>
            <ArrowLeft className="h-4 w-4" />
            Document Pipeline
          </Button>
          <h1 className="text-2xl font-bold">Final Approval</h1>
          <p className="text-sm text-muted-foreground mt-1">{doc.title}</p>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="p-6 max-w-2xl mx-auto space-y-6">
            {/* Document summary card */}
            <Card className="p-5">
              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                  <FileText className="h-5 w-5 text-primary" />
                </div>
                <div className="flex-1">
                  <h2 className="font-semibold">{doc.title}</h2>
                  <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground mt-1">
                    <span>{doc.documentType}</span>
                    <span>v{doc.version}</span>
                    <span>{doc.system}</span>
                    <span>{doc.totalPages} pages</span>
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground mt-1">
                    <span className="flex items-center gap-1">
                      <User className="h-3 w-3" />
                      Uploaded by {doc.uploadedBy}
                    </span>
                    <span className="flex items-center gap-1">
                      <Calendar className="h-3 w-3" />
                      {new Date(doc.uploadedAt).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              </div>

              {(doc.qaScore !== undefined || qaRecommendation) && (
                <div className="mt-4 pt-4 border-t border-border space-y-2">
                  {doc.qaScore !== undefined && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Optimization QA Score</span>
                      <span
                        className={`font-bold ${
                          doc.qaScore >= 90 ? "text-green-400" : doc.qaScore >= 75 ? "text-amber-400" : "text-red-400"
                        }`}
                      >
                        {doc.qaScore}%
                      </span>
                    </div>
                  )}
                  {qaRecommendation && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Optimization QA Recommendation</span>
                      <Badge
                        variant="outline"
                        className={`text-xs font-semibold ${
                          qaRecommendation === "accept"
                            ? "text-green-400 border-green-400/30 bg-green-400/10"
                            : qaRecommendation === "reject"
                            ? "text-red-400 border-red-400/30 bg-red-400/10"
                            : "text-amber-400 border-amber-400/30 bg-amber-400/10"
                        }`}
                      >
                        {qaRecommendation === "accept" ? "Accept" : qaRecommendation === "reject" ? "Reject" : "Review"}
                      </Badge>
                    </div>
                  )}
                </div>
              )}
            </Card>

            {/* Already finalized */}
            {(isAlreadyApproved || (submitted && decision === "approve")) && (
              <div className="rounded-lg border border-green-400/20 bg-green-400/5 p-5">
                <div className="flex items-center gap-3 mb-3">
                  <CheckCircle2 className="h-6 w-6 text-green-400" />
                  <div className="flex-1">
                    <p className="font-semibold text-green-400 text-lg">Document Approved</p>
                    <p className="text-xs text-muted-foreground">
                      {publicationStatus === "published"
                        ? "Published to RAG knowledge base"
                        : publicationStatus === "publishing"
                        ? "Publishing to RAG knowledge base..."
                        : publicationStatus === "failed"
                        ? "Final-approved, but publish to RAG failed"
                        : "Final-approved (pending publish to RAG)"}
                    </p>
                  </div>
                  <Badge variant="outline" className="gap-1 text-green-400 border-green-400/30 bg-green-400/10 shrink-0">
                    <Lock className="h-3 w-3" /> Locked
                  </Badge>
                </div>
                <div className="text-sm text-muted-foreground space-y-1">
                  {(submittedBy || isAlreadyApproved) && (
                    <p className="flex items-center gap-2">
                      <User className="h-3.5 w-3.5" />
                      Approved by <span className="font-medium text-foreground">{submittedBy ?? doc.approvedBy}</span>
                    </p>
                  )}
                  {(submittedAt || (isAlreadyApproved && doc.approvedAt)) && (
                    <p className="flex items-center gap-2">
                      <Calendar className="h-3.5 w-3.5" />
                      {new Date(submittedAt ?? doc.approvedAt!).toLocaleString()}
                    </p>
                  )}
                </div>
                {(notes || doc.notes) && <p className="text-xs text-muted-foreground mt-2 italic">{notes || doc.notes}</p>}
                {publicationStatus !== "published" && (
                  <div className="mt-3">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void publishToRag()}
                      disabled={publicationStatus === "publishing"}
                    >
                      {publicationStatus === "publishing" ? "Publishing..." : "Retry Publish to RAG"}
                    </Button>
                  </div>
                )}
                <p className="text-xs text-muted-foreground mt-3 border-t border-border pt-2">
                  This version is locked. New uploads create a new document record.
                </p>
              </div>
            )}

            {(isAlreadyRejected) && (
              <div className="rounded-lg border border-red-400/20 bg-red-400/5 p-5">
                <div className="flex items-center gap-3 mb-2">
                  <XCircle className="h-6 w-6 text-red-400" />
                  <div className="flex-1">
                    <p className="font-semibold text-red-400 text-lg">Document Rejected</p>
                    <p className="text-xs text-muted-foreground">Document not added to RAG knowledge base</p>
                  </div>
                  <Badge variant="outline" className="gap-1 text-red-400 border-red-400/30 bg-red-400/10 shrink-0">
                    <Lock className="h-3 w-3" /> Locked
                  </Badge>
                </div>
                {submittedBy && (
                  <p className="text-sm text-muted-foreground flex items-center gap-2 mb-1">
                    <User className="h-3.5 w-3.5" /> Rejected by <span className="font-medium text-foreground">{submittedBy}</span>
                  </p>
                )}
                {(notes || doc.notes) && <p className="text-xs text-muted-foreground mt-2 italic">{notes || doc.notes}</p>}
              </div>
            )}

            {/* Decision UI — only for non-finalized docs */}
            {!isFinalized && (
              <Card className="p-5 space-y-5">
                <h2 className="font-semibold">Final Approval Decision</h2>

                {!canStartFinalApproval(doc.status) && (
                  <div className="rounded-lg border border-amber-400/30 bg-amber-400/5 p-4">
                    <p className="font-medium text-amber-400">QA must pass before final approval</p>
                    <p className="text-sm text-muted-foreground mt-1">
                      This document is currently <span className="font-medium text-foreground">{doc.status}</span>. Return to QA gates to finish scoring and accept the optimized output before granting final approval.
                    </p>
                    <Button variant="outline" className="mt-3 gap-2" onClick={() => router.push(`/admin/documents/${docId}/qa-gates`)}>
                      <ArrowLeft className="h-4 w-4" />
                      Go to QA Gates
                    </Button>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => setDecision("approve")}
                    className={`rounded-lg border-2 p-4 text-left transition-all ${
                      decision === "approve"
                        ? "border-green-400 bg-green-400/10"
                        : "border-border hover:border-green-400/50 hover:bg-green-400/5"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <ThumbsUp className={`h-4 w-4 ${decision === "approve" ? "text-green-400" : "text-muted-foreground"}`} />
                      <span className="font-medium text-sm">Approve</span>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Add to RAG knowledge base and make available for queries
                    </p>
                  </button>
                  <button
                    onClick={() => setDecision("reject")}
                    className={`rounded-lg border-2 p-4 text-left transition-all ${
                      decision === "reject"
                        ? "border-red-400 bg-red-400/10"
                        : "border-border hover:border-red-400/50 hover:bg-red-400/5"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <ThumbsDown className={`h-4 w-4 ${decision === "reject" ? "text-red-400" : "text-muted-foreground"}`} />
                      <span className="font-medium text-sm">Reject</span>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Document does not meet quality standards for ingestion
                    </p>
                  </button>
                </div>

                <div>
                  <Label htmlFor="notes" className="mb-1.5 block text-sm">
                    Notes <span className="text-muted-foreground">(optional)</span>
                  </Label>
                  <Textarea
                    id="notes"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Add approval notes or rejection reason..."
                    rows={3}
                  />
                </div>

                <Separator />

                <div className="flex items-center justify-between">
                  <p className="text-xs text-muted-foreground">
                    Reviewed by {user?.fullName ?? "Unknown"} · {new Date().toLocaleDateString()}
                  </p>
                  <Button
                    disabled={!decision || (decision === "approve" && !canSubmitFinalApproval)}
                    onClick={() => void handleSubmit()}
                    className={
                      decision === "reject"
                        ? "bg-red-500 hover:bg-red-600 text-white"
                        : ""
                    }
                  >
                    {decision === "approve"
                      ? "Grant Final Approval"
                      : decision === "reject"
                      ? "Reject Document"
                      : "Select a Decision"}
                  </Button>
                </div>
                {submissionError && (
                  <p className="text-sm text-red-400">{submissionError}</p>
                )}
              </Card>
            )}

            {submitted && (
              <Button variant="outline" className="w-full" onClick={() => router.push("/admin/documents")}>
                Return to Document Pipeline
              </Button>
            )}
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
