"use client";

import { AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";
import type { ReviewPage } from "@/types";

interface PageListProps {
  pages: ReviewPage[];
  selectedIdx: number;
  pageSaveState: Record<string, "saving" | "saved" | "error">;
  onSelect: (idx: number) => void;
}

export function PageList({ pages, selectedIdx, pageSaveState, onSelect }: PageListProps) {
  return (
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
              onClick={() => onSelect(idx)}
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
  );
}
