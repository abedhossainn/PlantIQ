"use client";

import { useState, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CheckCircle2, XCircle, AlertTriangle, ArrowLeft, FileText, Table as TableIcon, Image as ImageIcon, TrendingUp, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { getDocumentFromPipeline, fetchArtifactJson, fastapiFetch, ApiError } from "@/lib/api";
import {
  canStartFinalApproval,
  canOpenOptimizedReview,
  isFinalizedDocumentStatus,
  isOptimizationPendingStatus,
  isQAReadyStatus,
} from "@/lib/document-status";
import type { Document, QAMetric } from "@/types";
import {
  type QAPreReviewArtifact,
  type QARescoreResponse,
  mapBackendMetrics,
  decisionToRecommendation,
  STATUS_CONFIG,
} from "./_helpers";

export default function QAGatesClient({ docId }: { docId: string }) {
  const router = useRouter();

  const [doc, setDoc] = useState<Document | null>(null);
  const [isDocLoading, setIsDocLoading] = useState(true);
  const [isRefreshingStatus, setIsRefreshingStatus] = useState(false);

  // QA artifact state
  const [metrics, setMetrics] = useState<QAMetric[]>([]);
  const [recommendation, setRecommendation] = useState<"accept" | "reject" | "review">("review");
  const [qaReport, setQaReport] = useState<QAPreReviewArtifact | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadDocument(showRefreshState = false) {
      if (showRefreshState) {
        setIsRefreshingStatus(true);
      }
      try {
        const loaded = await getDocumentFromPipeline(docId);
        if (!cancelled) {
          setDoc(loaded);
        }
      } catch {
        // noop
      } finally {
        if (!cancelled) {
          setIsDocLoading(false);
          setIsRefreshingStatus(false);
        }
      }
    }

    void loadDocument();

    const poller = window.setInterval(() => {
      void loadDocument(true);
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(poller);
    };
  }, [docId]);

  // Fetch QA artifact once document ID is set
  useEffect(() => {
    let cancelled = false;

    async function loadQAReport() {
      try {
        const report = await fetchArtifactJson<QAPreReviewArtifact>(docId, "qa_report");
        if (!cancelled) {
          setQaReport(report);
          setMetrics(mapBackendMetrics(report));
          setRecommendation(decisionToRecommendation(report.decision));
        }
      } catch {
        if (!cancelled) {
          setQaReport(null);
          setMetrics([]);
          setRecommendation("review");
        }
      }
    }

    void loadQAReport();

    return () => {
      cancelled = true;
    };
  }, [docId]);

  // --- Re-score and decision state ---
  const [isRescoring, setIsRescoring] = useState(false);
  const [rescoreError, setRescoreError] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);

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

  const hasFails = metrics.some((m) => m.status === "fail");
  const isOptimizationPending = doc ? isOptimizationPendingStatus(doc.status) : false;
  const isFinalized = doc ? isFinalizedDocumentStatus(doc.status) : false;
  const canRunQAScoring = doc ? isQAReadyStatus(doc.status) && !isFinalizedDocumentStatus(doc.status) : false;
  const canProceedToFinalApproval = doc ? canStartFinalApproval(doc.status) : false;

  async function handleDecision(d: "accept" | "reject") {
    setDecisionError(null);
    try {
      await fastapiFetch(`/api/v1/documents/${docId}/qa-decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: d }),
      });
      if (d === "accept") {
        router.push(`/admin/documents/${docId}/approve`);
      } else {
        router.push("/admin/documents");
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setDecisionError("QA criteria not yet met. Re-score the document first, or go back and improve the content.");
      } else {
        setDecisionError("An unexpected error occurred. Please try again.");
      }
    }
  }

  async function handleRescore() {
    setIsRescoring(true);
    setRescoreError(null);
    setDecisionError(null);
    try {
      const result = await fastapiFetch<QARescoreResponse>(`/api/v1/documents/${docId}/qa-rescore`, {
        method: "POST",
      });
      const newMetrics = mapBackendMetrics({
        timestamp: result.timestamp,
        decision: result.decision as QAPreReviewArtifact["decision"],
        metrics: result.metrics,
        passed_criteria: result.passed_criteria,
        failed_criteria: result.failed_criteria,
        recommendations: result.recommendations,
      });
      setMetrics(newMetrics);
      setRecommendation(decisionToRecommendation(result.decision));
      setQaReport((prev) =>
        prev
          ? {
              ...prev,
              timestamp: result.timestamp,
              decision: result.decision as QAPreReviewArtifact["decision"],
              passed_criteria: result.passed_criteria,
              failed_criteria: result.failed_criteria,
            }
          : {
              timestamp: result.timestamp,
              decision: result.decision as QAPreReviewArtifact["decision"],
              metrics: result.metrics,
              passed_criteria: result.passed_criteria,
              failed_criteria: result.failed_criteria,
              recommendations: result.recommendations,
            }
      );
      setDoc((prev) =>
        prev
          ? {
              ...prev,
              status:
                result.decision === "approved" || result.decision === "conditional_approval"
                  ? "qa-review"
                  : prev.status,
            }
          : prev
      );
    } catch {
      setRescoreError("Re-score failed. Please try again or contact support.");
    } finally {
      setIsRescoring(false);
    }
  }

  const metricIcons: Record<string, React.ReactNode> = {
    "Text Accuracy": <FileText className="h-5 w-5" />,
    "Table Structure Preservation": <TableIcon className="h-5 w-5" />,
    "Image Description Coverage": <ImageIcon className="h-5 w-5" />,
    "Overall Quality Score": <TrendingUp className="h-5 w-5" />,
  };

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col h-full min-h-0">
        {/* Header */}
        <div className="border-b border-border px-6 py-5 bg-card/50">
          <Button variant="ghost" size="sm" className="gap-1.5 mb-3 -ml-2" onClick={() => router.push(`/admin/documents/${docId}/optimized-review`)}>
            <ArrowLeft className="h-4 w-4" />
            Optimized Output Review
          </Button>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Optimization QA</h1>
              <p className="text-sm text-muted-foreground mt-0.5">Post-optimization quality scoring · {doc.title}</p>
            </div>
            <div className="text-sm text-muted-foreground">
              {qaReport?.timestamp ? (
                <>Generated {new Date(qaReport.timestamp).toLocaleString()}</>
              ) : doc.uploadedAt ? new Date(doc.uploadedAt).toLocaleString() : "—"}
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="p-6 max-w-7xl mx-auto space-y-6">

            {/* Recommendation banner */}
            <div className={`rounded-lg border p-5 flex items-center gap-4 ${
              recommendation === "accept"
                ? "bg-green-400/5 border-green-400/30"
                : (recommendation === "reject" || hasFails)
                ? "bg-red-400/5 border-red-400/30"
                : "bg-amber-400/5 border-amber-400/30"
            }`}>
              <div className={`flex h-10 w-10 items-center justify-center rounded-full shrink-0 ${
                recommendation === "accept" ? "bg-green-400/15" : (recommendation === "reject" || hasFails) ? "bg-red-400/15" : "bg-amber-400/15"
              }`}>
                {recommendation === "accept" ? (
                  <CheckCircle2 className="h-5 w-5 text-green-400" />
                ) : (recommendation === "reject" || hasFails) ? (
                  <XCircle className="h-5 w-5 text-red-400" />
                ) : (
                  <AlertTriangle className="h-5 w-5 text-amber-400" />
                )}
              </div>
              <div className="flex-1">
                {recommendation === "accept" ? (
                  <>
                    <p className="font-bold text-green-400">Recommendation: ACCEPT</p>
                    <p className="text-sm text-muted-foreground">
                      • All optimization QA metrics meet or exceed configured thresholds. This document is ready for final approval.
                    </p>
                  </>
                ) : (recommendation === "reject" || hasFails) ? (
                  <>
                    <p className="font-bold text-red-400">Recommendation: REJECT</p>
                    <p className="text-sm text-muted-foreground">
                      • One or more optimization QA gates failed. Return to fidelity review to correct source content, then re-submit for optimization and use <strong className="text-foreground/70">Re-score Document</strong> to recompute metrics.
                    </p>
                  </>
                ) : (
                  <>
                    <p className="font-bold text-amber-400">Recommendation: MANUAL REVIEW</p>
                    <p className="text-sm text-muted-foreground">
                      • Some optimization QA metrics have warnings. Re-score after reviewing content to confirm status.
                    </p>
                  </>
                )}
              </div>
            </div>

            {isOptimizationPending && (
              <div className="rounded-lg border border-sky-400/30 bg-sky-400/5 p-5 flex items-start justify-between gap-4">
                <div>
                  <p className="font-semibold text-sky-400">Optimization is still running</p>
                  <p className="text-sm text-muted-foreground mt-1">
                    QA gates will unlock once the optimized artifact is ready. This page refreshes status automatically every few seconds.
                  </p>
                </div>
                <Button variant="outline" className="gap-2 shrink-0" disabled={isRefreshingStatus} onClick={() => window.location.reload()}>
                  <RefreshCw className={`h-4 w-4 ${isRefreshingStatus ? "animate-spin" : ""}`} />
                  Refresh Status
                </Button>
              </div>
            )}

            {!isOptimizationPending && !canRunQAScoring && !canProceedToFinalApproval && (
              <div className="rounded-lg border border-amber-400/30 bg-amber-400/5 p-5">
                <p className="font-semibold text-amber-400">Return to review before QA</p>
                <p className="text-sm text-muted-foreground mt-1">
                  This document has not completed the review → optimization handoff yet. Finish fidelity review first, then approve it for optimization.
                </p>
              </div>
            )}

            {/* Stale-report notice — shown when no QA report is present but doc is in a scoreable state */}
            {!isOptimizationPending && canRunQAScoring && metrics.length === 0 && (
              <div className="rounded-lg border border-sky-400/30 bg-sky-400/5 p-5 flex items-start justify-between gap-4">
                <div className="flex-1">
                  <p className="font-semibold text-sky-400">QA report unavailable — rescore required</p>
                  <p className="text-sm text-muted-foreground mt-1">
                    No QA report exists for this document. This may be because optimized content was
                    edited after the last score run. Use <strong className="text-foreground/70">Re-score Document</strong> below to generate fresh metrics.
                  </p>
                </div>
                {doc && canOpenOptimizedReview(doc.status) && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2 shrink-0"
                    onClick={() => router.push(`/admin/documents/${docId}/optimized-review`)}
                  >
                    <ArrowLeft className="h-4 w-4" />
                    Edit Optimized Output
                  </Button>
                )}
              </div>
            )}

            {/* Metric cards */}
            {metrics.length === 0 ? (
              <div className="rounded-lg border border-border bg-muted/20 p-6 text-center">
                <AlertTriangle className="h-8 w-8 text-muted-foreground/40 mx-auto mb-3" />
                <p className="font-medium text-muted-foreground">Automated QA metrics not available</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Run QA scoring after optimization completes to generate the metric report used for acceptance and final approval.
                </p>
              </div>
            ) : (
            <div className="grid grid-cols-2 gap-6">
              {metrics.map((metric) => {
                const cfg = STATUS_CONFIG[metric.status] ?? STATUS_CONFIG.pass;
                const icon = metricIcons[metric.name];
                return (
                  <Card key={metric.name} className={`border-2 p-6 ${
                    metric.status === "pass" ? "border-green-400/20" :
                    metric.status === "warning" ? "border-amber-400/20" : "border-red-400/20"
                  }`}>
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <div className="text-muted-foreground">{icon}</div>
                        <h3 className="font-semibold">{metric.name}</h3>
                      </div>
                      {cfg.icon}
                    </div>
                    <div className="mb-4">
                      <div className={`text-5xl font-bold ${
                        metric.status === "pass" ? "text-green-400" :
                        metric.status === "warning" ? "text-amber-400" : "text-red-400"
                      }`}>
                        {metric.score}
                        <span className="text-2xl text-muted-foreground"> /100</span>
                      </div>
                    </div>
                    <div className="mb-3">
                      <Progress value={metric.score} className={`h-3 ${cfg.barClass}`} />
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-sm text-muted-foreground">
                        Threshold: {metric.threshold}%
                      </div>
                      <Badge variant="outline" className={`text-xs font-bold ${cfg.badgeClass}`}>
                        {cfg.label}
                      </Badge>
                    </div>
                    {metric.details && (
                      <p className="text-xs text-muted-foreground mt-3">{metric.details}</p>
                    )}
                  </Card>
                );
              })}
            </div>
            )}

            {/* Threshold Configuration */}
            <Card className="border-border overflow-hidden">
              <div className="px-6 py-4 border-b border-border">
                <h2 className="font-semibold">Threshold Configuration</h2>
                <p className="text-sm text-muted-foreground mt-0.5">
                  Adjust optimization QA thresholds (changes apply to future scoring runs)
                </p>
              </div>
              <div className="p-6 grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="text-threshold" className="text-sm">Text Accuracy Threshold (%)</Label>
                  <Input
                    id="text-threshold"
                    type="number"
                    defaultValue="95"
                    className="bg-background"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="table-threshold" className="text-sm">Table Structure Threshold (%)</Label>
                  <Input
                    id="table-threshold"
                    type="number"
                    defaultValue="92"
                    className="bg-background"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="image-threshold" className="text-sm">Image Coverage Threshold (%)</Label>
                  <Input
                    id="image-threshold"
                    type="number"
                    defaultValue="85"
                    className="bg-background"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="overall-threshold" className="text-sm">Overall Score Threshold (%)</Label>
                  <Input
                    id="overall-threshold"
                    type="number"
                    defaultValue="90"
                    className="bg-background"
                  />
                </div>
              </div>
            </Card>

            {/* Error messages */}
            {(decisionError || rescoreError) && (
              <div className="rounded-lg border border-red-400/30 bg-red-400/5 px-4 py-3 text-sm text-red-400">
                {decisionError ?? rescoreError}
              </div>
            )}

            {/* Action buttons */}
            <div className="flex items-center justify-between pt-2">
              <Button
                variant="outline"
                className="gap-2"
                onClick={() => router.push(`/admin/documents/${docId}/optimized-review`)}
              >
                <ArrowLeft className="h-4 w-4" />
                Edit Optimized Output
              </Button>
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  className="gap-2"
                  disabled={isRescoring || !canRunQAScoring}
                  onClick={() => void handleRescore()}
                >
                  <RefreshCw className={`h-4 w-4 ${isRescoring ? "animate-spin" : ""}`} />
                  {isOptimizationPending ? "Waiting for Optimization" : isRescoring ? "Re-scoring…" : "Re-score Document"}
                </Button>
                <Button
                  variant="outline"
                  className="gap-2 border-red-400/30 text-red-400 hover:bg-red-400/10 hover:border-red-400/50"
                  disabled={isFinalized || (!canRunQAScoring && !canProceedToFinalApproval)}
                  onClick={() => void handleDecision("reject")}
                >
                  <XCircle className="h-4 w-4" />
                  Reject Document
                </Button>
                <Button
                  className="gap-2 font-semibold"
                  disabled={recommendation !== "accept" || (!canRunQAScoring && !canProceedToFinalApproval)}
                  onClick={() => {
                    if (canProceedToFinalApproval) {
                      router.push(`/admin/documents/${docId}/approve`);
                      return;
                    }
                    void handleDecision("accept");
                  }}
                >
                  <CheckCircle2 className="h-4 w-4" />
                  {canProceedToFinalApproval ? "Proceed to Final Approval" : "Accept & Proceed to Final Approval"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
