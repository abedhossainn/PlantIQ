"use client";

import { useEffect, useState } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AlertTriangle, CheckCircle2, ArrowLeft, ArrowRight, Info, Download } from "lucide-react";
import { useRouter } from "next/navigation";
import { getDocumentFromPipeline, fetchArtifactJson } from "@/lib/api";
import type { Document, ValidationIssue } from "@/types";

// ── Backend artifact schema ────────────────────────────────────────────────
interface BackendValidationIssue {
  issue_type: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  page_number: number;
  description: string;
  evidence: string;
}

interface BackendPageValidation {
  page_number: number;
  issues: BackendValidationIssue[];
  confidence_score: number;
}

interface BackendValidationReport {
  timestamp?: string;
  overall_confidence: number;
  page_validations: BackendPageValidation[];
  metadata: {
    total_pages: number;
    total_issues: number;
    critical_issues: number;
  };
}

const ISSUE_TYPE_TO_CATEGORY: Record<string, ValidationIssue['category']> = {
  image_loss: 'image-loss',
  missing_text: 'missing-text',
  table_fidelity: 'table-fidelity',
  formatting: 'formatting',
  semantic_mismatch: 'semantic-mismatch',
};

const SEVERITY_CONFIG = {
  critical: { badgeClass: "text-red-400 bg-red-400/10 border-red-400/30", icon: <AlertTriangle className="h-3 w-3" />, order: 0 },
  high:     { badgeClass: "text-orange-400 bg-orange-400/10 border-orange-400/30", icon: <AlertTriangle className="h-3 w-3" />, order: 1 },
  medium:   { badgeClass: "text-amber-400 bg-amber-400/10 border-amber-400/30", icon: <Info className="h-3 w-3" />, order: 2 },
  low:      { badgeClass: "text-blue-400 bg-blue-400/10 border-blue-400/30", icon: <Info className="h-3 w-3" />, order: 3 },
};

const CATEGORY_LABELS: Record<string, string> = {
  "table-fidelity": "Table Fidelity",
  "image-loss": "Image Loss",
  "missing-text": "Missing Text",
  formatting: "Formatting",
  "ocr-error": "OCR Error",
};

export default function ValidationClient({ docId }: { docId: string }) {
  const router = useRouter();
  const [doc, setDoc] = useState<Document | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [overallConfidence, setOverallConfidence] = useState(0);
  const [validationTimestamp, setValidationTimestamp] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [rawReport, setRawReport] = useState<BackendValidationReport | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadDocument() {
      try {
        const loaded = await getDocumentFromPipeline(docId);
        if (!cancelled) {
          setDoc(loaded);
        }
      } catch {
        // noop — null state shows "Document not found"
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadDocument();

    return () => {
      cancelled = true;
    };
  }, [docId]);

  // Fetch validation artifact once the document record is available.
  useEffect(() => {
    if (!doc) return;
    let cancelled = false;
    setReportLoading(true);

    async function loadValidationReport() {
      try {
        const report = await fetchArtifactJson<BackendValidationReport>(docId, 'validation');
        if (cancelled) return;

        const mappedIssues: ValidationIssue[] = report.page_validations.flatMap(
          (pv, pvIdx) =>
            pv.issues.map((issue, iIdx) => ({
              id: `issue-${pvIdx}-${iIdx}`,
              page: issue.page_number,
              category: ISSUE_TYPE_TO_CATEGORY[issue.issue_type] ?? 'formatting',
              severity: issue.severity,
              description: issue.description,
              evidenceImageUrl: '',
              context: issue.evidence ?? '',
            }))
        );

        setIssues(mappedIssues);
        setOverallConfidence(Math.round(report.overall_confidence * 100));
        if (report.timestamp) setValidationTimestamp(report.timestamp);
        setRawReport(report);
      } catch {
        // Artifact not yet available — keep empty defaults
      } finally {
        if (!cancelled) setReportLoading(false);
      }
    }

    void loadValidationReport();
    return () => { cancelled = true; };
  }, [doc, docId]);

  if (isLoading) {
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

  function handleDownloadReport() {
    if (!rawReport) return;
    const blob = new Blob([JSON.stringify(rawReport, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `validation-report-${docId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // issues and overallConfidence are populated from artifact API
  const criticalCount = issues.filter((i) => i.severity === "critical").length;
  const highCount = issues.filter((i) => i.severity === "high").length;
  const mediumCount = issues.filter((i) => i.severity === "medium").length;
  const lowCount = issues.filter((i) => i.severity === "low").length;
  const hasBlockers = criticalCount > 0 || highCount > 0;

  // Sort by severity
  const sortedIssues = [...issues].sort((a, b) => {
    const ao = SEVERITY_CONFIG[a.severity]?.order ?? 99;
    const bo = SEVERITY_CONFIG[b.severity]?.order ?? 99;
    return ao - bo;
  });

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col h-full min-h-0">
        {/* Header */}
        <div className="border-b border-border px-6 py-5 bg-card/50">
          <Button variant="ghost" size="sm" className="gap-1.5 mb-3 -ml-2" onClick={() => router.push("/admin/documents")}>
            <ArrowLeft className="h-4 w-4" />
            Document Pipeline
          </Button>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">VLM Validation Report</h1>
              <p className="text-sm text-muted-foreground mt-0.5">Pre-review fidelity findings for {doc.title}</p>
            </div>
            <Button variant="outline" size="sm" className="gap-2" onClick={handleDownloadReport} disabled={!rawReport}>
              <Download className="h-4 w-4" />
              Download Report
            </Button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="p-6 max-w-7xl mx-auto space-y-6">
            {/* Stat Cards */}
            <div className={`grid grid-cols-5 gap-4 transition-opacity ${reportLoading ? 'opacity-50' : ''}`}>
              <Card className="border-border bg-card p-6">
                <div className="text-4xl font-bold">{issues.length}</div>
                <div className="text-sm text-muted-foreground mt-2">{reportLoading ? 'Loading…' : 'Total Issues'}</div>
              </Card>
              <Card className="border-border bg-card p-6">
                <div className="text-4xl font-bold text-red-400">{criticalCount}</div>
                <div className="text-sm text-muted-foreground mt-2">Critical</div>
              </Card>
              <Card className="border-border bg-card p-6">
                <div className="text-4xl font-bold text-orange-400">{highCount}</div>
                <div className="text-sm text-muted-foreground mt-2">High</div>
              </Card>
              <Card className="border-border bg-card p-6">
                <div className="text-4xl font-bold text-amber-400">{mediumCount}</div>
                <div className="text-sm text-muted-foreground mt-2">Medium</div>
              </Card>
              <Card className="border-border bg-card p-6">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-6 w-6 text-green-400" />
                  <div className="text-4xl font-bold text-green-400">
                    {overallConfidence}%
                  </div>
                </div>
                <div className="text-sm text-muted-foreground mt-2">Confidence</div>
              </Card>
            </div>

            {/* Issues table */}
            <Card className="overflow-hidden border-border">
              <div className="px-6 py-4 border-b border-border">
                <h2 className="text-base font-semibold">Validation Issues</h2>
                <p className="text-sm text-muted-foreground mt-0.5">
                  Issues identified during VLM validation
                  {validationTimestamp && (
                    <> &bull; Generated {new Date(validationTimestamp).toLocaleString()}</>
                  )}
                </p>
              </div>
              {sortedIssues.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/20 hover:bg-muted/20 border-border">
                      <TableHead className="font-medium text-foreground/80 w-20">Page</TableHead>
                      <TableHead className="font-medium text-foreground/80 w-40">Category</TableHead>
                      <TableHead className="font-medium text-foreground/80 w-28">Severity</TableHead>
                      <TableHead className="font-medium text-foreground/80">Description</TableHead>
                      <TableHead className="font-medium text-foreground/80">Context</TableHead>
                      <TableHead className="font-medium text-foreground/80 w-28">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sortedIssues.map((issue) => {
                      const cfg = SEVERITY_CONFIG[issue.severity] ?? SEVERITY_CONFIG.low;
                      return (
                        <TableRow key={issue.id} className="border-border hover:bg-muted/10 transition-colors">
                          <TableCell className="py-4">
                            <div className="flex items-center gap-2">
                              <Info className="h-4 w-4 text-muted-foreground" />
                              <span className="font-medium">{issue.page}</span>
                            </div>
                          </TableCell>
                          <TableCell className="py-4">
                            <div className="flex items-center gap-2">
                              <Info className="h-4 w-4 text-muted-foreground" />
                              <span className="text-sm">{CATEGORY_LABELS[issue.category] ?? issue.category}</span>
                            </div>
                          </TableCell>
                          <TableCell className="py-4">
                            <Badge variant="outline" className={`text-xs font-medium uppercase ${cfg.badgeClass}`}>
                              {issue.severity}
                            </Badge>
                          </TableCell>
                          <TableCell className="py-4">
                            <p className="text-sm">{issue.description}</p>
                          </TableCell>
                          <TableCell className="py-4">
                            <p className="text-sm text-muted-foreground">{issue.context || "—"}</p>
                          </TableCell>
                          <TableCell className="py-4">
                            <Button variant="ghost" size="sm" className="gap-2 h-8 text-xs">
                              <AlertTriangle className="h-3 w-3" />
                              Evidence
                            </Button>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              ) : (
                <div className="text-center py-12">
                  <CheckCircle2 className="h-12 w-12 text-green-400/40 mx-auto mb-3" />
                  <p className="text-muted-foreground">No issues found during validation</p>
                </div>
              )}
            </Card>

            {/* Action buttons */}
            <div className="flex items-center justify-between pt-2">
              <Button
                variant="outline"
                className="gap-2"
                onClick={() => router.push("/admin/documents")}
              >
                <ArrowLeft className="h-4 w-4" />
                Back to Documents
              </Button>
              <Button
                  className="gap-2 font-semibold bg-amber-500 hover:bg-amber-600 text-black"
                  onClick={() => router.push(`/admin/documents/${docId}/review`)}
                >
                  Start Fidelity Review
                  <ArrowRight className="h-4 w-4" />
                </Button>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
