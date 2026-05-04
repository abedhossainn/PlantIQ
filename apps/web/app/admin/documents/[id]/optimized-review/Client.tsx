"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, Edit3, FileText, RefreshCw, Save, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AppLayout } from "@/components/shared/AppLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { getDocumentOptimizedChunks, shouldSkipOptimizedReview, updateOptimizedChunk } from "@/lib/api/optimized-review";
import type { OptimizedChunk, DocumentOptimizedChunksResponse } from "@/types";
import { EditableList } from "./_components/EditableList";
import { ChunkList } from "./_components/ChunkList";

type ChunkSaveState = "saving" | "saved" | "error";

export default function OptimizedReviewClient({ docId }: { docId: string }) {
  const router = useRouter();

  const [documentName, setDocumentName] = useState<string>("");
  const [chunks, setChunks] = useState<OptimizedChunk[]>([]);
  const [chunksLoading, setChunksLoading] = useState(true);
  const [chunksError, setChunksError] = useState<string | null>(null);

  const [selectedIdx, setSelectedIdx] = useState(0);

  const [headingDraft, setHeadingDraft] = useState<Record<string, string>>({});
  const [contentDraft, setContentDraft] = useState<Record<string, string>>({});
  const [tableFacts, setTableFacts] = useState<Record<string, string[]>>({});
  const [ambiguityFlags, setAmbiguityFlags] = useState<Record<string, string[]>>({});

  const [saveState, setSaveState] = useState<Record<string, ChunkSaveState>>({});
  const [editingChunkId, setEditingChunkId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadChunks() {
      setChunksLoading(true);
      setChunksError(null);
      try {
        const data: DocumentOptimizedChunksResponse = await getDocumentOptimizedChunks(docId);
        if (cancelled) return;

        if (shouldSkipOptimizedReview(data)) {
          const targetRoute = data.next_route ?? `/admin/documents/${docId}/qa-gates`;
          router.replace(targetRoute);
          return;
        }

        setDocumentName(data.document_name ?? "");
        setChunks(data.chunks ?? []);
        const headings: Record<string, string> = {};
        const contents: Record<string, string> = {};
        const facts: Record<string, string[]> = {};
        const flags: Record<string, string[]> = {};
        for (const c of data.chunks) {
          headings[c.id] = c.heading;
          contents[c.id] = c.markdown_content;
          facts[c.id] = [...c.table_facts];
          flags[c.id] = [...c.ambiguity_flags];
        }
        setHeadingDraft(headings);
        setContentDraft(contents);
        setTableFacts(facts);
        setAmbiguityFlags(flags);
      } catch (err) {
        if (!cancelled) {
          setChunksError(err instanceof Error ? err.message : "Failed to load optimized chunks.");
        }
      } finally {
        if (!cancelled) setChunksLoading(false);
      }
    }

    void loadChunks();
    return () => { cancelled = true; };
  }, [docId, router]);

  const saveChunk = useCallback(
    async (chunkId: string) => {
      setSaveState((prev) => ({ ...prev, [chunkId]: "saving" }));
      setEditingChunkId(null);
      try {
        await updateOptimizedChunk(docId, chunkId, {
          heading: headingDraft[chunkId] ?? "",
          markdown_content: contentDraft[chunkId] ?? "",
          table_facts: tableFacts[chunkId] ?? [],
          ambiguity_flags: ambiguityFlags[chunkId] ?? [],
        });
        setChunks((prev) =>
          prev.map((c) =>
            c.id === chunkId
              ? {
                  ...c,
                  heading: headingDraft[chunkId] ?? c.heading,
                  markdown_content: contentDraft[chunkId] ?? c.markdown_content,
                  table_facts: tableFacts[chunkId] ?? c.table_facts,
                  ambiguity_flags: ambiguityFlags[chunkId] ?? c.ambiguity_flags,
                }
              : c
          )
        );
        setSaveState((prev) => ({ ...prev, [chunkId]: "saved" }));
      } catch {
        setSaveState((prev) => ({ ...prev, [chunkId]: "error" }));
      }
    },
    [docId, headingDraft, contentDraft, tableFacts, ambiguityFlags]
  );

  function cancelEdit(chunkId: string) {
    const chunk = chunks.find((c) => c.id === chunkId);
    if (chunk) {
      setHeadingDraft((prev) => ({ ...prev, [chunkId]: chunk.heading }));
      setContentDraft((prev) => ({ ...prev, [chunkId]: chunk.markdown_content }));
      setTableFacts((prev) => ({ ...prev, [chunkId]: [...chunk.table_facts] }));
      setAmbiguityFlags((prev) => ({ ...prev, [chunkId]: [...chunk.ambiguity_flags] }));
    }
    setEditingChunkId(null);
  }

  const selectedChunk: OptimizedChunk | undefined = chunks[selectedIdx];
  const isEditing = selectedChunk ? editingChunkId === selectedChunk.id : false;
  const hasAnyEdits = chunks.some((c) => saveState[c.id] === "saved");

  if (chunksLoading) {
    return (
      <AppLayout>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-muted-foreground">Loading optimized chunks…</p>
        </div>
      </AppLayout>
    );
  }

  if (chunksError) {
    return (
      <AppLayout>
        <div className="flex-1 flex flex-col items-center justify-center gap-4 p-8">
          <AlertTriangle className="h-8 w-8 text-red-400" />
          <p className="text-muted-foreground text-sm">{chunksError}</p>
          <Button variant="outline" className="gap-2" onClick={() => router.push("/admin/documents")}>
            <ArrowLeft className="h-4 w-4" />
            Back to Document Pipeline
          </Button>
        </div>
      </AppLayout>
    );
  }

  if (chunks.length === 0) {
    return (
      <AppLayout>
        <div className="flex-1 flex flex-col items-center justify-center gap-4 p-8">
          <FileText className="h-8 w-8 text-muted-foreground/40" />
          <div className="text-center space-y-1">
            <p className="font-semibold text-foreground">No optimized chunks available</p>
            <p className="text-sm text-muted-foreground">
              Optimization has not yet produced output for this document.
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" className="gap-2" onClick={() => router.push(`/admin/documents/${docId}/optimizing`)}>
              <RefreshCw className="h-4 w-4" />
              View Optimization Status
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => router.push("/admin/documents")}>
              <ArrowLeft className="h-4 w-4" />
              Back to Pipeline
            </Button>
          </div>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col h-full min-h-0">

        {/* Header */}
        <div className="border-b border-border px-6 py-4 bg-card/50 shrink-0">
          <Button variant="ghost" size="sm" className="gap-1.5 mb-2 -ml-2" onClick={() => router.push("/admin/documents")}>
            <ArrowLeft className="h-4 w-4" />
            Document Pipeline
          </Button>
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className="min-w-0">
                <h1 className="font-bold text-lg leading-tight truncate">
                  {documentName || "Optimized Output Review"}
                </h1>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Post-optimization editor · {chunks.length} chunk{chunks.length !== 1 ? "s" : ""}
                </p>
              </div>
            </div>
            <Button size="sm" className="gap-1.5 font-semibold shrink-0" onClick={() => router.push(`/admin/documents/${docId}/qa-gates`)}>
              Proceed to QA
              <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Info banner */}
        <div className="px-5 py-2 bg-primary/5 border-b border-primary/10 flex items-center gap-2 shrink-0">
          <CheckCircle2 className="h-3.5 w-3.5 text-primary/60 shrink-0" />
          <p className="text-xs text-muted-foreground">
            Review and edit Stage 10 optimized output before running QA.{" "}
            <strong className="text-foreground/70">Saving any chunk resets QA scores</strong> — re-run
            QA scoring on the next page to generate fresh metrics.
          </p>
        </div>

        {/* 3-pane layout */}
        <div className="flex-1 grid min-h-0" style={{ gridTemplateColumns: "220px 1fr 280px" }}>

          <ChunkList
            chunks={chunks}
            selectedIdx={selectedIdx}
            saveState={saveState}
            onSelect={setSelectedIdx}
          />

          {/* CENTER: main editor pane */}
          <div className="flex flex-col min-h-0 overflow-hidden">
            {selectedChunk && (
              <>
                {/* Subheader */}
                <div className="px-5 py-3 border-b border-border bg-card/60 flex items-center gap-3 shrink-0">
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-sm">Chunk {selectedChunk.chunk_number}</p>
                    {selectedChunk.source_pages.length > 0 && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Source pages: {selectedChunk.source_pages.join(", ")}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {saveState[selectedChunk.id] === "saving" && !isEditing && (
                      <span className="text-xs text-muted-foreground bg-muted/50 border border-border rounded px-2 py-0.5 flex items-center gap-1">
                        <RefreshCw className="h-2.5 w-2.5 animate-spin" /> Saving…
                      </span>
                    )}
                    {saveState[selectedChunk.id] === "saved" && !isEditing && (
                      <span className="text-xs text-green-400 bg-green-400/10 border border-green-400/20 rounded px-2 py-0.5 flex items-center gap-1">
                        <CheckCircle2 className="h-2.5 w-2.5" /> Saved
                      </span>
                    )}
                    {saveState[selectedChunk.id] === "error" && !isEditing && (
                      <span className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded px-2 py-0.5 flex items-center gap-1">
                        <AlertTriangle className="h-2.5 w-2.5" /> Save failed
                      </span>
                    )}
                    {isEditing ? (
                      <>
                        <Button size="sm" variant="ghost" className="h-7 gap-1.5 text-xs" onClick={() => cancelEdit(selectedChunk.id)}>
                          <X className="h-3.5 w-3.5" />
                          Cancel
                        </Button>
                        <Button size="sm" className="h-7 gap-1.5 text-xs" onClick={() => void saveChunk(selectedChunk.id)}>
                          <Save className="h-3.5 w-3.5" />
                          Save
                        </Button>
                      </>
                    ) : (
                      <Button size="sm" variant="outline" className="h-7 gap-1.5 text-xs" onClick={() => setEditingChunkId(selectedChunk.id)}>
                        <Edit3 className="h-3.5 w-3.5" />
                        Edit
                      </Button>
                    )}
                  </div>
                </div>

                {/* Editor area */}
                <div className="flex-1 overflow-y-auto min-h-0 p-5 space-y-4">
                  {/* Heading */}
                  <div>
                    <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1.5 block">
                      Heading
                    </label>
                    {isEditing ? (
                      <input
                        className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm font-semibold text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
                        value={headingDraft[selectedChunk.id] ?? ""}
                        onChange={(e) =>
                          setHeadingDraft((prev) => ({ ...prev, [selectedChunk.id]: e.target.value }))
                        }
                      />
                    ) : (
                      <p className="text-sm font-semibold text-foreground">
                        {headingDraft[selectedChunk.id] ?? selectedChunk.heading}
                      </p>
                    )}
                  </div>

                  {/* Markdown content */}
                  <div>
                    <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1.5 block">
                      Content
                    </label>
                    {isEditing ? (
                      <Textarea
                        className="w-full font-mono text-xs min-h-[320px] resize-y bg-background"
                        value={contentDraft[selectedChunk.id] ?? ""}
                        onChange={(e) =>
                          setContentDraft((prev) => ({ ...prev, [selectedChunk.id]: e.target.value }))
                        }
                      />
                    ) : (
                      <div className="prose prose-sm prose-invert max-w-none text-sm text-foreground/90 border border-border rounded p-4 bg-muted/10">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {contentDraft[selectedChunk.id] ?? selectedChunk.markdown_content}
                        </ReactMarkdown>
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* RIGHT: context pane */}
          <div className="flex flex-col border-l border-border min-h-0 overflow-y-auto">
            <div className="p-3 border-b border-border shrink-0">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Chunk Context
              </p>
            </div>

            {selectedChunk && (
              <div className="flex-1 p-4 space-y-5">
                {/* Source pages (read-only) */}
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                    Source Pages
                  </p>
                  {selectedChunk.source_pages.length === 0 ? (
                    <p className="text-xs text-muted-foreground italic">None</p>
                  ) : (
                    <div className="flex flex-wrap gap-1.5">
                      {selectedChunk.source_pages.map((pg) => (
                        <Badge key={pg} variant="outline" className="text-[10px] text-muted-foreground">
                          Page {pg}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>

                <EditableList
                  label="Table Facts"
                  items={tableFacts[selectedChunk.id] ?? []}
                  readOnly={!isEditing}
                  onChange={(next) =>
                    setTableFacts((prev) => ({ ...prev, [selectedChunk.id]: next }))
                  }
                />

                <EditableList
                  label="Ambiguity Flags"
                  items={ambiguityFlags[selectedChunk.id] ?? []}
                  readOnly={!isEditing}
                  onChange={(next) =>
                    setAmbiguityFlags((prev) => ({ ...prev, [selectedChunk.id]: next }))
                  }
                />

                {hasAnyEdits && (
                  <div className="rounded border border-amber-400/30 bg-amber-400/5 p-3 text-xs text-amber-300 space-y-1">
                    <p className="font-semibold">QA scores invalidated</p>
                    <p className="text-muted-foreground">
                      Edits have been saved. The previous QA report has been cleared.
                      Use <strong className="text-foreground/70">Proceed to QA</strong> to re-run scoring with the updated content.
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>

        </div>

        {/* Footer CTA */}
        <div className="border-t border-border px-6 py-4 bg-card/50 shrink-0 flex items-center justify-between gap-4">
          <Button variant="outline" className="gap-2" onClick={() => router.push(`/admin/documents/${docId}/optimizing`)}>
            <ArrowLeft className="h-4 w-4" />
            Back to Optimization
          </Button>
          <Button className="gap-2 font-semibold" onClick={() => router.push(`/admin/documents/${docId}/qa-gates`)}>
            Proceed to QA
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>

      </div>
    </AppLayout>
  );
}
