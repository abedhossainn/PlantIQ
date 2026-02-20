"use client";

import { useState, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { CheckCircle2, XCircle, ArrowLeft, FileText, User, Calendar, ThumbsUp, ThumbsDown, Lock } from "lucide-react";
import { useRouter, useParams } from "next/navigation";
import { mockDocuments, mockQAGateReports } from "@/lib/mock";
import { useAuth } from "@/lib/auth/AuthContext";

type Decision = "approve" | "reject" | null;

export default function ApprovePage() {
  const router = useRouter();
  const params = useParams();
  const { user } = useAuth();
  const docId = params.id as string;

  const doc = mockDocuments.find((d) => d.id === docId);
  const report = mockQAGateReports?.[docId];

  const [decision, setDecision] = useState<Decision>(null);
  const [notes, setNotes] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [submittedAt, setSubmittedAt] = useState<string | null>(null);
  const [submittedBy, setSubmittedBy] = useState<string | null>(null);

  // Load persisted decision from localStorage on mount
  useEffect(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem(`approval-${docId}`);
      if (stored) {
        try {
          const parsed = JSON.parse(stored);
          setDecision(parsed.decision ?? null);
          setNotes(parsed.notes ?? "");
          setSubmitted(true);
          setSubmittedAt(parsed.submittedAt ?? null);
          setSubmittedBy(parsed.submittedBy ?? null);
        } catch { /* noop */ }
      }
    }
  }, [docId]);

  if (!doc) {
    return (
      <AppLayout>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-muted-foreground">Document not found</p>
        </div>
      </AppLayout>
    );
  }

  const isAlreadyApproved = doc.status === "approved" || (submitted && decision === "approve");
  const isAlreadyRejected = doc.status === "rejected" || (submitted && decision === "reject");
  const isFinalized = isAlreadyApproved || isAlreadyRejected;

  function handleSubmit() {
    if (!decision) return;
    const ts = new Date().toISOString();
    const reviewer = user?.fullName ?? "Unknown";
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

              {doc.qaScore !== undefined && (
                <div className="mt-4 pt-4 border-t border-border">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">QA Score</span>
                    <span
                      className={`font-bold ${
                        doc.qaScore >= 90 ? "text-green-400" : doc.qaScore >= 75 ? "text-amber-400" : "text-red-400"
                      }`}
                    >
                      {doc.qaScore}%
                    </span>
                  </div>
                </div>
              )}

              {report && (
                <div className="mt-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">QA Recommendation</span>
                    <Badge
                      variant="outline"
                      className={
                        report.recommendation === "accept"
                          ? "text-green-400 bg-green-400/10 border-green-400/20"
                          : "text-red-400 bg-red-400/10 border-red-400/20"
                      }
                    >
                      {report.recommendation === "accept" ? "Accept" : "Reject"}
                    </Badge>
                  </div>
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
                    <p className="text-xs text-muted-foreground">Ingested into RAG knowledge base</p>
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
                <h2 className="font-semibold">Approval Decision</h2>

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
                    disabled={!decision}
                    onClick={handleSubmit}
                    className={
                      decision === "reject"
                        ? "bg-red-500 hover:bg-red-600 text-white"
                        : ""
                    }
                  >
                    {decision === "approve"
                      ? "Approve Document"
                      : decision === "reject"
                      ? "Reject Document"
                      : "Select a Decision"}
                  </Button>
                </div>
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
