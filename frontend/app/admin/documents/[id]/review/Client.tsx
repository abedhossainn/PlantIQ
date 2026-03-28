"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Edit3,
  Image as ImageIcon,
  Info,
  RefreshCw,
  Save,
  X,
} from "lucide-react";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "text-red-400 bg-red-400/10 border-red-400/30",
  high: "text-orange-400 bg-orange-400/10 border-orange-400/30",
  medium: "text-amber-400 bg-amber-400/10 border-amber-400/30",
  low: "text-zinc-400 bg-zinc-400/10 border-zinc-400/20",
};
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { AppLayout } from "@/components/shared/AppLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { fastapiFetch, getDocumentFromPipeline } from "@/lib/api";
import { isOptimizationPendingStatus } from "@/lib/document-status";
import type { Document, DocumentPagesResponse, ReviewPage } from "@/types";

/** Remove HTML comments embedded by the pipeline before rendering */
function stripHtmlComments(content: string): string {
  return content.replace(/<!--[\s\S]*?-->/g, "").trim();
}

export default function ReviewClient({ docId }: { docId: string }) {
  const router = useRouter();

  const [doc, setDoc] = useState<Document | null>(null);
  const [isDocLoading, setIsDocLoading] = useState(true);
  const [pages, setPages] = useState<ReviewPage[]>([]);
  const [pagesLoading, setPagesLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [pageContent, setPageContent] = useState<Record<string, string>>({});
  const [editingPageId, setEditingPageId] = useState<string | null>(null);
  const [editBuffer, setEditBuffer] = useState("");
  // Backend save state per page: undefined=untouched, saving, saved, error
  const [pageSaveState, setPageSaveState] = useState<Record<string, "saving" | "saved" | "error">>({}); 

  async function approveForOptimization() {
    setIsSubmitting(true);
    setApproveError(null);
    try {
      await fastapiFetch(`/api/v1/documents/${docId}/approve-for-optimization`, { method: "POST" });
      router.push(`/admin/documents/${docId}/optimizing`);
    } catch (err) {
      setApproveError(err instanceof Error ? err.message : "Failed to approve document for optimization.");
    } finally {
      setIsSubmitting(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function loadDocument() {
      try {
        const loaded = await getDocumentFromPipeline(docId);
        if (!cancelled) setDoc(loaded);
      } catch { /* noop */ } finally {
        if (!cancelled) setIsDocLoading(false);
      }
    }

    void loadDocument();
    return () => { cancelled = true; };
  }, [docId]);

  useEffect(() => {
    let cancelled = false;

    async function loadPages() {
      try {
        const data = await fastapiFetch<DocumentPagesResponse>(`/api/v1/documents/${docId}/pages`);
        if (!cancelled) setPages(data.pages ?? []);
      } catch { /* noop */ } finally {
        if (!cancelled) setPagesLoading(false);
      }
    }

    void loadPages();
    return () => { cancelled = true; };
  }, [docId]);

  // Backfill editable content when pages arrive
  useEffect(() => {
    if (pages.length === 0) return;
    setPageContent((prev) => {
      const next = { ...prev };
      pages.forEach((p) => {
        if (!next[p.id]) next[p.id] = p.markdown_content;
      });
      return next;
    });
  }, [pages]);

  function startEdit(pageId: string) {
    setEditingPageId(pageId);
    setEditBuffer(pageContent[pageId] ?? "");
  }

  function cancelEdit() {
    setEditingPageId(null);
    setEditBuffer("");
  }

  async function saveEdit(pageId: string) {
    const content = editBuffer; // capture before state reset
    setPageContent((prev) => ({ ...prev, [pageId]: content })); // optimistic
    setEditingPageId(null);
    setEditBuffer("");
    setPageSaveState((prev) => ({ ...prev, [pageId]: "saving" }));
    try {
      await fastapiFetch(`/api/v1/documents/${docId}/pages/${pageId}/content`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ markdown_content: content }),
      });
      setPageSaveState((prev) => ({ ...prev, [pageId]: "saved" }));
    } catch {
      setPageSaveState((prev) => ({ ...prev, [pageId]: "error" }));
    }
  }

  // ---------- loading / error states ----------

  if (isDocLoading || pagesLoading) {
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

  if (isOptimizationPendingStatus(doc.status)) {
    return (
      <AppLayout>
        <div className="flex-1 flex flex-col h-full min-h-0">
          <div className="border-b border-border px-6 py-5 bg-card/50">
            <Button variant="ghost" size="sm" className="gap-1.5 mb-3 -ml-2" onClick={() => router.push("/admin/documents")}>
              <ArrowLeft className="h-4 w-4" />
              Document Pipeline
            </Button>
            <h1 className="text-2xl font-bold tracking-tight">Optimization in Progress</h1>
            <p className="text-sm text-muted-foreground mt-0.5">{doc.title}</p>
          </div>
          <div className="flex-1 flex items-center justify-center p-8">
            <div className="max-w-md text-center space-y-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 mx-auto">
                <RefreshCw className="h-6 w-6 text-primary animate-spin" />
              </div>
              <div>
                <p className="font-semibold text-foreground">This document has already been approved for optimization</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Review is complete. The backend is generating optimized output before QA can begin.
                </p>
              </div>
              <div className="flex flex-col gap-2 pt-2">
                <Button className="gap-2 font-semibold" onClick={() => router.push(`/admin/documents/${docId}/optimizing`)}>
                  View Optimization Status
                  <ArrowRight className="h-4 w-4" />
                </Button>
                <Button variant="outline" className="gap-2" onClick={() => router.push("/admin/documents")}>
                  <ArrowLeft className="h-4 w-4" />
                  Back to Documents
                </Button>
              </div>
            </div>
          </div>
        </div>
      </AppLayout>
    );
  }

  if (["uploading", "extracting", "vlm-validating"].includes(doc.status)) {
    const statusLabel =
      doc.status === "uploading"
        ? "Uploading"
        : doc.status === "extracting"
        ? "Extracting"
        : "Validating";

    return (
      <AppLayout>
        <div className="flex-1 flex flex-col h-full min-h-0">
          <div className="border-b border-border px-6 py-5 bg-card/50">
            <Button variant="ghost" size="sm" className="gap-1.5 mb-3 -ml-2" onClick={() => router.push("/admin/documents")}>
              <ArrowLeft className="h-4 w-4" />
              Document Pipeline
            </Button>
            <h1 className="text-2xl font-bold tracking-tight">Processing in Progress</h1>
            <p className="text-sm text-muted-foreground mt-0.5">{doc.title}</p>
          </div>
          <div className="flex-1 flex items-center justify-center p-8">
            <div className="max-w-md text-center space-y-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 mx-auto">
                <RefreshCw className="h-6 w-6 text-primary animate-spin" />
              </div>
              <div>
                <p className="font-semibold text-foreground">{statusLabel} document content</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Page review data is generated only after validation completes. Please wait until the document reaches
                  <strong className="text-foreground/80"> Validation Complete</strong> status.
                </p>
              </div>
              <div className="flex flex-col gap-2 pt-2">
                <Button variant="outline" className="gap-2" onClick={() => router.push("/admin/documents") }>
                  <ArrowLeft className="h-4 w-4" />
                  Back to Documents
                </Button>
              </div>
            </div>
          </div>
        </div>
      </AppLayout>
    );
  }

  // ---------- empty state (no pages generated yet) ----------

  if (pages.length === 0) {
    return (
      <AppLayout>
        <div className="flex-1 flex flex-col h-full min-h-0">
          <div className="border-b border-border px-6 py-5 bg-card/50">
            <Button variant="ghost" size="sm" className="gap-1.5 mb-3 -ml-2" onClick={() => router.push("/admin/documents")}>
              <ArrowLeft className="h-4 w-4" />
              Document Pipeline
            </Button>
            <h1 className="text-2xl font-bold tracking-tight">{doc.title}</h1>
            <p className="text-sm text-muted-foreground mt-0.5">Fidelity &amp; Safety Review · v{doc.version}</p>
          </div>
          <div className="flex-1 flex items-center justify-center p-8">
            <div className="max-w-sm text-center space-y-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted/50 mx-auto">
                <Info className="h-6 w-6 text-muted-foreground" />
              </div>
              <div>
                <p className="font-semibold text-foreground">Page extraction data not available</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Page-level extraction has not been generated yet.
                  You can skip fidelity review and approve for optimization directly, or return to the document list.
                </p>
              </div>
              <div className="flex flex-col gap-2 pt-2">
                <Button
                  className="gap-2 font-semibold"
                  disabled={isSubmitting}
                  onClick={async () => {
                    await approveForOptimization();
                  }}
                >
                  {isSubmitting ? "Approving…" : "Approve for Optimization"}
                  <ArrowRight className="h-4 w-4" />
                </Button>
                <Button variant="outline" className="gap-2" onClick={() => router.push("/admin/documents")}>
                  <ArrowLeft className="h-4 w-4" />
                  Back to Documents
                </Button>
                {approveError && (
                  <p className="text-xs text-red-400">{approveError}</p>
                )}
              </div>
            </div>
          </div>
        </div>
      </AppLayout>
    );
  }

  // ---------- main review layout ----------

  const selectedPage: ReviewPage | undefined = pages[selectedIdx];

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col h-full min-h-0">

        {/* Header */}
        <div className="border-b border-border px-6 py-4">
          <Button variant="ghost" size="sm" className="gap-1.5 mb-2" onClick={() => router.push("/admin/documents")}>
            <ArrowLeft className="h-4 w-4" />
            Document Pipeline
          </Button>
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div>
                <h1 className="font-bold text-lg leading-tight">{doc.title}</h1>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Fidelity &amp; Safety Review · {pages.length} page{pages.length !== 1 ? "s" : ""}
                </p>
              </div>
              <Badge variant="outline" className="text-xs text-primary border-primary/30 bg-primary/10">
                v{doc.version ?? "1.0"}
              </Badge>
            </div>
            <Button
              size="sm"
              className="gap-1.5 font-semibold"
              disabled={isSubmitting}
              onClick={async () => {
                await approveForOptimization();
              }}
            >
              {isSubmitting ? "Approving…" : "Approve for Optimization"}
              <ArrowRight className="h-4 w-4" />
            </Button>
            {approveError && (
              <p className="text-xs text-red-400 mt-1 px-1">{approveError}</p>
            )}
          </div>
        </div>

        {/* Save notice */}
        <div className="px-5 py-2 bg-primary/5 border-b border-primary/10 flex items-center gap-2 shrink-0">
          <Info className="h-3.5 w-3.5 text-primary/60 shrink-0" />
          <p className="text-xs text-muted-foreground">
            Review each page for fidelity to the source PDF. <strong className="text-foreground/70">Edit</strong> and <strong className="text-foreground/70">Save</strong> to correct extraction errors or dangerous omissions. When all pages are verified, use <strong className="text-foreground/70">Approve for Optimization</strong> above.
          </p>
        </div>

        {/* 2-panel layout */}
        <div className="flex-1 grid min-h-0" style={{ gridTemplateColumns: "220px 1fr" }}>

          {/* LEFT — page list */}
          <div className="flex flex-col border-r border-border min-h-0">
            <div className="p-3 border-b border-border">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Pages · {selectedIdx + 1} of {pages.length}
              </p>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0 p-2 space-y-1">
              {pages.map((page, idx) => {
                const isSelected = idx === selectedIdx;
                const saveState = pageSaveState[page.id];
                return (
                  <button
                    key={page.id}
                    onClick={() => setSelectedIdx(idx)}
                    className={`w-full text-left p-3 rounded text-sm transition-colors border-l-4 ${
                      isSelected
                        ? "bg-primary/12 border-l-primary"
                        : "hover:bg-muted/40 border-l-transparent"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-0.5">
                      <p className={`text-xs font-semibold ${isSelected ? "text-foreground" : "text-muted-foreground"}`}>
                        Page {page.page_number}
                      </p>
                      <div className="flex items-center gap-1 shrink-0">
                        {(page.validation_issues?.length ?? 0) > 0 && (
                          <span className="text-[10px] text-amber-400 bg-amber-400/10 border border-amber-400/20 rounded px-1 py-0.5">
                            {page.validation_issues.length}
                          </span>
                        )}
                        {saveState === "saving" && (
                          <RefreshCw className="h-3 w-3 text-muted-foreground animate-spin" />
                        )}
                        {saveState === "saved" && (
                          <CheckCircle2 className="h-3 w-3 text-green-400" />
                        )}
                        {saveState === "error" && (
                          <AlertTriangle className="h-3 w-3 text-red-400" />
                        )}
                      </div>
                    </div>
                    {page.evidence?.text_preview && (
                      <p className="text-[10px] text-muted-foreground/60 line-clamp-2 leading-snug">
                        {page.evidence.text_preview}
                      </p>
                    )}
                  </button>
                );
              })}
            </div>

            {/* Scoring criteria reference */}
            <div className="border-t border-border p-3 shrink-0 bg-muted/20">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">Fidelity Review</p>
              <div className="space-y-1.5">
                <div className="text-[10px] text-muted-foreground"><span className="font-medium text-foreground/70">Faithful?</span> — is extracted content materially true to the source PDF?</div>
                <div className="text-[10px] text-muted-foreground"><span className="font-medium text-foreground/70">Preserved?</span> — are key tables, figures, and technical statements intact?</div>
                <div className="text-[10px] text-muted-foreground"><span className="font-medium text-foreground/70">No hallucinations?</span> — verify no fabricated facts or dangerous omissions</div>
                <div className="text-[10px] text-muted-foreground"><span className="font-medium text-foreground/70">Safe to optimize?</span> — is this page ready to enter downstream optimization?</div>
              </div>
            </div>
          </div>

          {/* RIGHT — content editor */}
          <div className="flex flex-col min-h-0 overflow-hidden">
            {selectedPage ? (
              <>
                {/* Content subheader */}
                <div className="px-5 py-3 border-b border-border bg-card/60 flex items-center gap-3 shrink-0">
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-sm">Page {selectedPage.page_number}</p>
                    {(selectedPage.evidence?.image_count > 0 || selectedPage.evidence?.table_count > 0) && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {[
                          selectedPage.evidence.image_count > 0 &&
                            `${selectedPage.evidence.image_count} image${selectedPage.evidence.image_count !== 1 ? "s" : ""}`,
                          selectedPage.evidence.table_count > 0 &&
                            `${selectedPage.evidence.table_count} table${selectedPage.evidence.table_count !== 1 ? "s" : ""}`,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    )}
                  </div>

                  {pageSaveState[selectedPage.id] === "saving" && editingPageId !== selectedPage.id && (
                    <span className="text-xs text-muted-foreground bg-muted/50 border border-border rounded px-2 py-0.5 shrink-0 flex items-center gap-1">
                      <RefreshCw className="h-2.5 w-2.5 animate-spin" /> Saving…
                    </span>
                  )}
                  {pageSaveState[selectedPage.id] === "saved" && editingPageId !== selectedPage.id && (
                    <span className="text-xs text-green-400 bg-green-400/10 border border-green-400/20 rounded px-2 py-0.5 shrink-0">
                      Saved
                    </span>
                  )}
                  {pageSaveState[selectedPage.id] === "error" && editingPageId !== selectedPage.id && (
                    <span className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded px-2 py-0.5 shrink-0">
                      Save failed
                    </span>
                  )}

                  {editingPageId === selectedPage.id ? (
                    <div className="flex gap-1.5 shrink-0">
                      <Button size="sm" variant="outline" className="h-7 px-2 gap-1 text-xs" onClick={cancelEdit}>
                        <X className="h-3 w-3" /> Cancel
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 px-2 gap-1 text-xs"
                        disabled={pageSaveState[editingPageId ?? ""] === "saving"}
                        onClick={() => void saveEdit(selectedPage.id)}
                      >
                        <Save className="h-3 w-3" /> Save
                      </Button>
                    </div>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 px-2 gap-1 text-xs shrink-0"
                      onClick={() => startEdit(selectedPage.id)}
                    >
                      <Edit3 className="h-3 w-3" /> Edit
                    </Button>
                  )}
                </div>

                {/* Content area */}
                {editingPageId === selectedPage.id ? (
                  <div className="flex-1 flex flex-col p-4 gap-2 min-h-0">
                    <p className="text-xs text-muted-foreground shrink-0">
                      Editing markdown — press Save when done
                    </p>
                    <Textarea
                      className="flex-1 min-h-0 font-mono text-xs leading-relaxed resize-none bg-card border-border"
                      value={editBuffer}
                      onChange={(e) => setEditBuffer(e.target.value)}
                      autoFocus
                    />
                  </div>
                ) : (
                  <div className="flex-1 overflow-y-auto min-h-0 p-6 prose prose-invert prose-sm max-w-none">
                    {pageContent[selectedPage.id] || selectedPage.markdown_content ? (
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          h1: ({ children }) => <h1 className="text-xl font-bold mt-0 mb-3 text-foreground">{children}</h1>,
                          h2: ({ children }) => <h2 className="text-base font-semibold mt-4 mb-2">{children}</h2>,
                          h3: ({ children }) => <h3 className="text-sm font-semibold mt-3 mb-1">{children}</h3>,
                          p: ({ children }) => <p className="text-sm leading-relaxed mb-3 text-foreground/90">{children}</p>,
                          ul: ({ children }) => <ul className="list-disc list-inside text-sm mb-3 space-y-1">{children}</ul>,
                          ol: ({ children }) => <ol className="list-decimal list-inside text-sm mb-3 space-y-1">{children}</ol>,
                          li: ({ children }) => <li className="text-sm text-foreground/90">{children}</li>,
                          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
                          table: ({ children }) => (
                            <div className="overflow-x-auto my-4">
                              <table className="w-full text-xs border-collapse border border-border">{children}</table>
                            </div>
                          ),
                          th: ({ children }) => <th className="border border-border px-3 py-1.5 bg-muted text-left font-medium">{children}</th>,
                          td: ({ children }) => <td className="border border-border px-3 py-1.5">{children}</td>,
                          blockquote: ({ children }) => (
                            <blockquote className="border-l-4 border-amber-400/50 pl-4 my-3 text-muted-foreground italic text-sm">
                              {children}
                            </blockquote>
                          ),
                          code: ({ children }) => (
                            <code className="bg-muted px-1 rounded text-xs font-mono">{children}</code>
                          ),
                        }}
                      >
                        {stripHtmlComments(pageContent[selectedPage.id] ?? selectedPage.markdown_content)}
                      </ReactMarkdown>
                    ) : (
                      <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
                        <ImageIcon className="h-8 w-8 text-muted-foreground/30" />
                        <div>
                          <p className="text-sm font-medium text-muted-foreground">No extracted text for this page</p>
                          {selectedPage.evidence?.text_preview && (
                            <p className="text-xs text-muted-foreground/60 mt-1 max-w-xs">
                              {selectedPage.evidence.text_preview}
                            </p>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Validation issues — shown below content in read mode */}
                    {selectedPage.validation_issues?.length > 0 && (
                      <div className="mt-6 pt-5 border-t border-border">
                        <p className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                          <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                          Validation Issues ({selectedPage.validation_issues.length})
                        </p>
                        <div className="space-y-2">
                          {selectedPage.validation_issues.map((issue, i) => (
                            <div
                              key={i}
                              className={`rounded-lg border p-3 text-xs ${
                                SEVERITY_COLORS[issue.severity] ?? SEVERITY_COLORS.low
                              }`}
                            >
                              <div className="flex items-center gap-1.5 mb-1">
                                <span className="font-semibold capitalize">{issue.severity}</span>
                                <span className="opacity-50">·</span>
                                <span className="opacity-70 capitalize">{issue.issue_type.replace(/_/g, " ")}</span>
                              </div>
                              <p className="leading-snug">{issue.description}</p>
                              {issue.suggested_fix && (
                                <p className="mt-1 opacity-60 italic">Fix: {issue.suggested_fix}</p>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Prev / Next navigation */}
                <div className="shrink-0 flex items-center justify-between gap-3 px-5 py-3 border-t border-border bg-card/40">
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1.5"
                    disabled={selectedIdx === 0}
                    onClick={() => setSelectedIdx((i) => i - 1)}
                  >
                    <ArrowLeft className="h-3.5 w-3.5" />
                    Previous
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    {selectedIdx + 1} / {pages.length}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1.5"
                    disabled={selectedIdx === pages.length - 1}
                    onClick={() => setSelectedIdx((i) => i + 1)}
                  >
                    Next
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </>
            ) : (
              <div className="flex-1 flex items-center justify-center">
                <p className="text-muted-foreground text-sm">Select a page to review</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </AppLayout>
  );
}


