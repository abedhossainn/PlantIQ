"use client";

import { useState, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { ArrowLeft, ArrowRight, CheckCircle2, Clock, AlertCircle, Edit3, Save, X, Image as ImageIcon, GitCompare, ChevronDown, ChevronUp } from "lucide-react";
import { useRouter, useParams } from "next/navigation";
import { mockDocuments, mockSections } from "@/lib/mock";
import { useAuth } from "@/lib/auth/AuthContext";
import type { DocumentSection, ReviewChecklist } from "@/types";
import ReactMarkdown from "react-markdown";

const STATUS_COLORS: Record<string, string> = {
  complete: "text-green-400 bg-green-400/10 border-green-400/20",
  "in-review": "text-amber-400 bg-amber-400/10 border-amber-400/20",
  pending: "text-zinc-400 bg-zinc-400/10 border-zinc-400/20",
};

const CHECKLIST_ITEMS: Array<{ key: keyof ReviewChecklist; label: string }> = [
  { key: "textAccuracyConfirmed", label: "Text accuracy confirmed" },
  { key: "tablesVerified", label: "Tables verified" },
  { key: "imagesDescribed", label: "Images described" },
  { key: "formattingCorrect", label: "Formatting correct" },
  { key: "technicalTermsAccurate", label: "Technical terms accurate" },
];

export default function ReviewPage() {
  const router = useRouter();
  const params = useParams();
  const docId = params.id as string;
  const { user } = useAuth();

  const doc = mockDocuments.find((d) => d.id === docId);
  const sections = mockSections.filter((s) => s.documentId === docId);

  const [selectedIdx, setSelectedIdx] = useState(0);
  const [checklists, setChecklists] = useState<Record<string, ReviewChecklist>>(() => {
    const init: Record<string, ReviewChecklist> = {};
    sections.forEach((s) => {
      init[s.id] = { ...s.checklist } as ReviewChecklist;
    });
    return init;
  });

  // Editable content state — keyed by section ID
  const [sectionContent, setSectionContent] = useState<Record<string, string>>(() => {
    const map: Record<string, string> = {};
    sections.forEach((s) => { map[s.id] = s.content; });
    return map;
  });
  const [editingSectionId, setEditingSectionId] = useState<string | null>(null);
  const [editBuffer, setEditBuffer] = useState("");
  const [saveRecord, setSaveRecord] = useState<Record<string, { timestamp: string; reviewer: string }>>({});
  const [showVersionHistory, setShowVersionHistory] = useState(false);

  // Load save records from localStorage
  useEffect(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem(`review-saves-${docId}`);
      if (stored) { try { setSaveRecord(JSON.parse(stored)); } catch { /* noop */ } }
    }
  }, [docId]);

  function startEdit(sectionId: string) {
    setEditingSectionId(sectionId);
    setEditBuffer(sectionContent[sectionId] ?? "");
  }

  function cancelEdit() {
    setEditingSectionId(null);
    setEditBuffer("");
  }

  function saveEdit(sectionId: string) {
    setSectionContent((prev) => ({ ...prev, [sectionId]: editBuffer }));
    const record = { timestamp: new Date().toISOString(), reviewer: user?.fullName ?? "Reviewer" };
    setSaveRecord((prev) => {
      const next = { ...prev, [sectionId]: record };
      if (typeof window !== "undefined") {
        localStorage.setItem(`review-saves-${docId}`, JSON.stringify(next));
      }
      return next;
    });
    setEditingSectionId(null);
    setEditBuffer("");
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

  const selectedSection: DocumentSection | undefined = sections[selectedIdx];
  const checklist = selectedSection ? checklists[selectedSection.id] : null;

  const completedSections = sections.filter((s) => {
    const cl = checklists[s.id];
    if (!cl) return false;
    return Object.values(cl).every(Boolean);
  }).length;
  const progress = sections.length > 0 ? (completedSections / sections.length) * 100 : 0;

  function toggleItem(sectionId: string, key: keyof ReviewChecklist) {
    setChecklists((prev) => ({
      ...prev,
      [sectionId]: { ...prev[sectionId], [key]: !prev[sectionId][key] },
    }));
  }

  function getSectionStatus(section: DocumentSection): string {
    const cl = checklists[section.id];
    if (!cl) return "pending";
    if (Object.values(cl).every(Boolean)) return "complete";
    if (Object.values(cl).some(Boolean)) return "in-review";
    return "pending";
  }

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
                <p className="text-xs text-muted-foreground mt-0.5">Engineering Review · {sections.length} sections</p>
              </div>
              <Badge variant="outline" className="text-xs text-primary border-primary/30 bg-primary/10">
                v{doc.version ?? "1.0"}
              </Badge>
            </div>
            <div className="flex items-center gap-4">
              <div className="text-right">
                <p className="text-xs text-muted-foreground">Sections reviewed</p>
                <p className="text-sm font-semibold">{completedSections} / {sections.length}</p>
              </div>
              <div className="w-28">
                <Progress value={progress} className="h-2" />
                <p className="text-xs text-muted-foreground mt-1 text-right">{Math.round(progress)}%</p>
              </div>
              <Button
                size="sm"
                className="gap-1.5 font-semibold"
                disabled={progress < 100}
                onClick={() => router.push(`/admin/documents/${docId}/qa-gates`)}
                title={progress < 100 ? "Complete all section checklists to submit" : "Submit for QA review"}
              >
                Submit for QA
                <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>

        {/* 3-panel layout */}
        <div className="flex-1 grid min-h-0" style={{ gridTemplateColumns: "280px 1fr 340px" }}>
          {/* LEFT — Section list */}
          <div className="flex flex-col border-r border-border overflow-y-auto min-h-0">
            <div className="p-3 border-b border-border flex items-center justify-between">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Sections</p>
              <span className="text-xs text-muted-foreground">{completedSections}/{sections.length} done</span>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0 p-2 space-y-1">
              {sections.map((section, idx) => {
                const status = getSectionStatus(section);
                const isSelected = idx === selectedIdx;
                return (
                  <button
                    key={section.id}
                    onClick={() => setSelectedIdx(idx)}
                    className={`w-full text-left p-3 text-sm transition-colors border-l-4 ${
                      isSelected
                        ? "bg-primary/12 border-l-primary"
                        : "hover:bg-muted/40 border-l-transparent"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1.5">
                      <span className={`flex items-center gap-1.5 text-xs font-medium ${
                        status === "complete" ? "text-green-400" :
                        status === "in-review" ? "text-amber-400" :
                        "text-muted-foreground"
                      }`}>
                        {status === "complete" ? (
                          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                        ) : status === "in-review" ? (
                          <Clock className="h-3.5 w-3.5 shrink-0" />
                        ) : (
                          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                        )}
                        {status === "complete" ? "Complete" : status === "in-review" ? "In Review" : "Pending"}
                      </span>
                      <span className="text-xs text-muted-foreground shrink-0">pp. {section.pageRange.start}–{section.pageRange.end}</span>
                    </div>
                    <p className={`text-xs font-medium leading-snug line-clamp-2 ${
                      isSelected ? "text-foreground" : "text-muted-foreground"
                    }`}>{section.heading}</p>
                  </button>
                );
              })}
            </div>
          </div>

          {/* MIDDLE — Section content */}
          <div className="flex flex-col min-h-0 border-r border-border overflow-hidden">
            <div className="p-3 border-b border-border">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Content</p>
            </div>
            {selectedSection ? (
              <div className="flex-1 flex flex-col overflow-hidden min-h-0">
                {/* Sticky subheader with edit controls */}
                <div className="px-4 py-3 border-b border-border bg-card/60 flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-sm leading-tight truncate">{selectedSection.heading}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">Pages {selectedSection.pageRange.start}–{selectedSection.pageRange.end}</p>
                  </div>
                  {/* Save timestamp badge */}
                  {saveRecord[selectedSection.id] && editingSectionId !== selectedSection.id && (
                    <span className="text-xs text-green-400 bg-green-400/10 border border-green-400/20 rounded px-2 py-0.5 shrink-0">
                      Saved {new Date(saveRecord[selectedSection.id].timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} by {saveRecord[selectedSection.id].reviewer}
                    </span>
                  )}
                  {editingSectionId === selectedSection.id ? (
                    <div className="flex gap-1.5 shrink-0">
                      <Button size="sm" variant="outline" className="h-7 px-2 gap-1 text-xs" onClick={cancelEdit}>
                        <X className="h-3 w-3" /> Cancel
                      </Button>
                      <Button size="sm" className="h-7 px-2 gap-1 text-xs bg-green-600 hover:bg-green-700 text-white" onClick={() => saveEdit(selectedSection.id)}>
                        <Save className="h-3 w-3" /> Save
                      </Button>
                    </div>
                  ) : (
                    <Button size="sm" variant="outline" className="h-7 px-2 gap-1 text-xs shrink-0" onClick={() => startEdit(selectedSection.id)}>
                      <Edit3 className="h-3 w-3" /> Edit
                    </Button>
                  )}
                </div>
                {editingSectionId === selectedSection.id ? (
                  <div className="flex-1 flex flex-col p-4 gap-2 min-h-0">
                    <p className="text-xs text-muted-foreground">Editing markdown — changes are saved with your name and timestamp</p>
                    <Textarea
                      className="flex-1 min-h-0 font-mono text-xs leading-relaxed resize-none bg-card border-border"
                      value={editBuffer}
                      onChange={(e) => setEditBuffer(e.target.value)}
                      autoFocus
                    />
                  </div>
                ) : (
                  <div className="flex-1 overflow-y-auto min-h-0 p-6 prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown
                    components={{
                      h1: ({ children }) => <h1 className="text-xl font-bold mt-0 mb-3">{children}</h1>,
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
                    {sectionContent[selectedSection.id] ?? selectedSection.content}
                  </ReactMarkdown>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center">
                <p className="text-muted-foreground text-sm">Select a section to review</p>
              </div>
            )}
          </div>

          {/* RIGHT — Checklist */}
          <div className="flex flex-col overflow-y-auto min-h-0">
            <div className="p-3 border-b border-border">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Review Checklist</p>
            </div>
            {selectedSection && checklist ? (
              <div className="flex-1 overflow-y-auto min-h-0 p-4">
                {/* Section name + page range */}
                <div className="mb-4">
                  <p className="text-sm font-semibold leading-snug">{selectedSection.heading}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Pages {selectedSection.pageRange.start}–{selectedSection.pageRange.end}
                  </p>
                </div>

                {/* Progress bar */}
                {(() => {
                  const checked = Object.values(checklist).filter(Boolean).length;
                  const pct = (checked / CHECKLIST_ITEMS.length) * 100;
                  return (
                    <div className="mb-4">
                      <div className="flex justify-between text-xs mb-1.5">
                        <span className="text-muted-foreground">Checklist progress</span>
                        <span className={`font-semibold ${
                          checked === CHECKLIST_ITEMS.length ? "text-green-400" : "text-amber-400"
                        }`}>
                          {checked} / {CHECKLIST_ITEMS.length}
                        </span>
                      </div>
                      <Progress value={pct} className="h-1.5" />
                    </div>
                  );
                })()}

                <Separator className="mb-3" />

                {/* Bordered checklist rows */}
                <div className="space-y-2">
                  {CHECKLIST_ITEMS.map(({ key, label }) => (
                    <div
                      key={key}
                      className={`flex items-center gap-3 rounded-lg border p-3 transition-colors ${
                        checklist[key]
                          ? "border-green-400/30 bg-green-400/5"
                          : "border-border bg-transparent hover:bg-muted/30"
                      }`}
                    >
                      <Checkbox
                        id={`${selectedSection.id}-${key}`}
                        checked={!!checklist[key]}
                        onCheckedChange={() => toggleItem(selectedSection.id, key)}
                      />
                      <Label
                        htmlFor={`${selectedSection.id}-${key}`}
                        className={`text-sm cursor-pointer leading-snug flex-1 ${
                          checklist[key] ? "text-green-400" : "text-foreground"
                        }`}
                      >
                        {label}
                      </Label>
                      {checklist[key] && (
                        <CheckCircle2 className="h-4 w-4 text-green-400 shrink-0" />
                      )}
                    </div>
                  ))}
                </div>

                <Separator className="my-4" />

                {/* Evidence images (US-1.3) */}
                <div className="mb-4">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <ImageIcon className="h-3.5 w-3.5" /> Evidence Images
                  </p>
                  {selectedSection.evidenceImages && selectedSection.evidenceImages.length > 0 ? (
                    <div className="grid grid-cols-2 gap-2">
                      {selectedSection.evidenceImages.map((img, idx) => (
                        <div
                          key={img}
                          className="relative rounded border border-border bg-muted/30 aspect-video flex items-center justify-center overflow-hidden"
                        >
                          {/* In production these are real PDF page snapshots from VLM validation */}
                          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1">
                            <ImageIcon className="h-5 w-5 text-muted-foreground/40" />
                            <span className="text-[10px] text-muted-foreground/60">
                              p.{selectedSection.pageRange.start + idx}
                            </span>
                          </div>
                          <div className="absolute bottom-0 left-0 right-0 bg-black/50 text-[9px] text-center py-0.5 text-muted-foreground">
                            Evidence screenshot
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground/60 italic">No evidence images for this section</p>
                  )}
                </div>

                <Separator className="my-3" />

                {/* Version history (US-1.5) */}
                <div className="mb-4">
                  <button
                    className="w-full flex items-center justify-between text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1 hover:text-foreground transition-colors"
                    onClick={() => setShowVersionHistory((v) => !v)}
                  >
                    <span className="flex items-center gap-1.5"><GitCompare className="h-3.5 w-3.5" /> Version History</span>
                    {showVersionHistory ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                  </button>
                  {showVersionHistory && (
                    <div className="space-y-2 mt-2">
                      {selectedSection.currentVersion && (
                        <div className="rounded border border-border bg-muted/20 p-2.5 text-xs">
                          <p className="font-semibold text-foreground mb-0.5">Current Version</p>
                          <p className="text-muted-foreground">Saved by {selectedSection.currentVersion.reviewedBy ?? "—"}</p>
                          <p className="text-muted-foreground">{new Date(selectedSection.currentVersion.timestamp).toLocaleDateString()} {new Date(selectedSection.currentVersion.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</p>
                        </div>
                      )}
                      {saveRecord[selectedSection.id] && (
                        <div className="rounded border border-green-400/30 bg-green-400/5 p-2.5 text-xs">
                          <p className="font-semibold text-green-400 mb-0.5">Latest Edit (This Session)</p>
                          <p className="text-muted-foreground">Saved by {saveRecord[selectedSection.id].reviewer}</p>
                          <p className="text-muted-foreground">{new Date(saveRecord[selectedSection.id].timestamp).toLocaleString()}</p>
                        </div>
                      )}
                      {selectedSection.lastApprovedVersion && (
                        <div className="rounded border border-primary/20 bg-primary/5 p-2.5 text-xs">
                          <p className="font-semibold text-primary mb-0.5">Last Approved Version</p>
                          <p className="text-muted-foreground">Approved by {selectedSection.lastApprovedVersion.reviewedBy ?? "—"}</p>
                          <p className="text-muted-foreground">{new Date(selectedSection.lastApprovedVersion.timestamp).toLocaleDateString()}</p>
                        </div>
                      )}
                      {!selectedSection.currentVersion && !selectedSection.lastApprovedVersion && (
                        <p className="text-xs text-muted-foreground/60 italic">No version history available</p>
                      )}
                    </div>
                  )}
                </div>

                <Separator className="my-3" />

                {/* Navigation buttons */}
                <div className="flex gap-2 mt-6">
                  {selectedIdx > 0 && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="flex-1 gap-1"
                      onClick={() => setSelectedIdx((i) => i - 1)}
                    >
                      <ArrowLeft className="h-3.5 w-3.5" />
                      Prev
                    </Button>
                  )}
                  {selectedIdx < sections.length - 1 && (
                    <Button
                      size="sm"
                      className="flex-1 gap-1"
                      onClick={() => setSelectedIdx((i) => i + 1)}
                    >
                      Next
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center p-6 text-center">
                <p className="text-muted-foreground text-sm">Select a section to see its checklist</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
