"use client";

import { useState, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CheckCircle2, XCircle, AlertTriangle, ArrowLeft, FileText, Table as TableIcon, Image as ImageIcon, TrendingUp } from "lucide-react";
import { useRouter } from "next/navigation";
import { mockDocuments, mockQAGateReports } from "@/lib/mock";
import type { QAMetric } from "@/types";

const STATUS_CONFIG = {
  pass:    { badgeClass: "text-green-400 bg-green-400/10 border-green-400/30", icon: <CheckCircle2 className="h-4 w-4" />, label: "PASS", barClass: "[&>div]:bg-green-400" },
  warning: { badgeClass: "text-amber-400 bg-amber-400/10 border-amber-400/30", icon: <AlertTriangle className="h-4 w-4" />, label: "WARNING", barClass: "[&>div]:bg-amber-400" },
  fail:    { badgeClass: "text-red-400 bg-red-400/10 border-red-400/30", icon: <XCircle className="h-4 w-4" />, label: "FAIL", barClass: "[&>div]:bg-red-400" },
};

export default function QAGatesClient({ docId }: { docId: string }) {
  const router = useRouter();

  const doc = mockDocuments.find((d) => d.id === docId);
  const report = mockQAGateReports?.[docId];

  if (!doc) {
    return (
      <AppLayout>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-muted-foreground">Document not found</p>
        </div>
      </AppLayout>
    );
  }

  const metrics: QAMetric[] = report ? Object.values(report.metrics) : [];
  const passCount = metrics.filter((m) => m.status === "pass").length;
  const warnCount = metrics.filter((m) => m.status === "warning").length;
  const failCount = metrics.filter((m) => m.status === "fail").length;
  const hasFails = failCount > 0;
  const hasWarnings = warnCount > 0;
  const recommendation = report?.recommendation ?? "review";

  // --- User decision persistence (overrides automated recommendation) ---
  const [userDecision, setUserDecision] = useState<"accept" | "reject" | null>(null);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem(`plantiq-qa-decision-${docId}`);
      if (stored) {
        try {
          const parsed = JSON.parse(stored);
          setUserDecision(parsed.decision ?? null);
        } catch { /* noop */ }
      }
    }
  }, [docId]);

  function handleDecision(d: "accept" | "reject") {
    setUserDecision(d);
    if (typeof window !== "undefined") {
      localStorage.setItem(
        `plantiq-qa-decision-${docId}`,
        JSON.stringify({ decision: d, timestamp: new Date().toISOString() })
      );
    }
    if (d === "accept") {
      router.push(`/admin/documents/${docId}/approve`);
    } else {
      router.push("/admin/documents");
    }
  }

  // Effective recommendation: user override takes priority over automated result
  const effectiveRecommendation = userDecision ?? recommendation;

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
          <Button variant="ghost" size="sm" className="gap-1.5 mb-3 -ml-2" onClick={() => router.push(`/admin/documents/${docId}/review`)}>
            <ArrowLeft className="h-4 w-4" />
            Back
          </Button>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">QA Gate Metrics</h1>
              <p className="text-sm text-muted-foreground mt-0.5">{doc.title}</p>
            </div>
            <div className="text-sm text-muted-foreground">
              Generated<br />
              2/19/2026, 1:55:00 AM
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="p-6 max-w-7xl mx-auto space-y-6">

            {/* Recommendation banner */}
            <div className={`rounded-lg border p-5 flex items-center gap-4 ${
              effectiveRecommendation === "accept"
                ? "bg-green-400/5 border-green-400/30"
                : effectiveRecommendation === "reject"
                ? "bg-red-400/5 border-red-400/30"
                : hasFails
                ? "bg-red-400/5 border-red-400/30"
                : "bg-amber-400/5 border-amber-400/30"
            }`}>
              <div className={`flex h-10 w-10 items-center justify-center rounded-full shrink-0 ${
                effectiveRecommendation === "accept" ? "bg-green-400/15" : (effectiveRecommendation === "reject" || hasFails) ? "bg-red-400/15" : "bg-amber-400/15"
              }`}>
                {effectiveRecommendation === "accept" ? (
                  <CheckCircle2 className="h-5 w-5 text-green-400" />
                ) : (effectiveRecommendation === "reject" || hasFails) ? (
                  <XCircle className="h-5 w-5 text-red-400" />
                ) : (
                  <AlertTriangle className="h-5 w-5 text-amber-400" />
                )}
              </div>
              <div className="flex-1">
                {effectiveRecommendation === "accept" ? (
                  <>
                    <p className="font-bold text-green-400">
                      Recommendation: ACCEPT
                      {userDecision === "accept" && recommendation !== "accept" && (
                        <span className="ml-2 text-xs font-normal text-muted-foreground">(Reviewer Override)</span>
                      )}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {userDecision === "accept" && recommendation !== "accept"
                        ? "• Reviewer has manually overridden the automated recommendation and approved this document for ingestion."
                        : "• All QA metrics meet or exceed configured thresholds. This document is ready for final approval."
                      }
                    </p>
                  </>
                ) : (effectiveRecommendation === "reject" || hasFails) ? (
                  <>
                    <p className="font-bold text-red-400">Recommendation: REJECT</p>
                    <p className="text-sm text-muted-foreground">
                      {userDecision === "reject"
                        ? "• Reviewer has decided to reject this document. It will not be added to the RAG knowledge base."
                        : "• One or more quality gates failed. Document requires additional processing or re-ingestion."
                      }
                    </p>
                  </>
                ) : (
                  <>
                    <p className="font-bold text-amber-400">Recommendation: MANUAL REVIEW</p>
                    <p className="text-sm text-muted-foreground">
                      • Some metrics have warnings. Manual review is recommended before approval.
                    </p>
                  </>
                )}
              </div>
              {userDecision && (
                <Badge variant="outline" className={`shrink-0 text-xs ${
                  userDecision === "accept"
                    ? "text-green-400 border-green-400/30 bg-green-400/10"
                    : "text-red-400 border-red-400/30 bg-red-400/10"
                }`}>
                  Reviewer Decision Saved
                </Badge>
              )}
            </div>

            {/* Metric cards */}
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

            {/* Threshold Configuration */}
            <Card className="border-border overflow-hidden">
              <div className="px-6 py-4 border-b border-border">
                <h2 className="font-semibold">Threshold Configuration</h2>
                <p className="text-sm text-muted-foreground mt-0.5">
                  Adjust QA gate thresholds (changes apply to future validations)
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

            {/* Action buttons */}
            <div className="flex items-center justify-between pt-2">
              <Button
                variant="outline"
                className="gap-2"
                onClick={() => router.push(`/admin/documents/${docId}/review`)}
              >
                <ArrowLeft className="h-4 w-4" />
                Back to Review
              </Button>
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  className="gap-2 border-red-400/30 text-red-400 hover:bg-red-400/10 hover:border-red-400/50"
                  onClick={() => handleDecision("reject")}
                >
                  <XCircle className="h-4 w-4" />
                  {userDecision === "reject" ? "Rejected (click to re-reject)" : "Reject Document"}
                </Button>
                <Button
                  className="gap-2 font-semibold"
                  onClick={() => handleDecision("accept")}
                >
                  <CheckCircle2 className="h-4 w-4" />
                  {userDecision === "accept" ? "Accepted — Go to Approval" : "Accept & Proceed to Approval"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
