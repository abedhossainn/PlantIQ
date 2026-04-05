"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FileText, X, ExternalLink } from "lucide-react";
import { useRouter } from "next/navigation";
import type { Citation } from "@/types";

interface SourceDrawerProps {
  cite: Citation;
  onClose: () => void;
}

export function SourceDrawer({ cite, onClose }: SourceDrawerProps) {
  const router = useRouter();
  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div
        className="w-full max-w-md h-full bg-card border-l border-border shadow-2xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border bg-muted/40">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" />
            <span className="font-semibold text-sm">Source Reference</span>
          </div>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Source metadata */}
        <div className="px-5 py-4 border-b border-border bg-card">
          <p className="font-bold text-base leading-tight mb-1">{cite.documentTitle}</p>
          <div className="flex flex-wrap items-center gap-2 mt-1">
            <Badge variant="outline" className="text-xs text-primary border-primary/30">
              Page {cite.pageNumber}
            </Badge>
            <Badge variant="outline" className="text-xs text-muted-foreground">
              {Math.round(cite.relevanceScore * 100)}% relevance
            </Badge>
          </div>
          <p className="text-sm font-medium text-muted-foreground mt-2">{cite.sectionHeading}</p>
        </div>

        {/* Excerpt */}
        <div className="flex-1 overflow-y-auto p-5">
          <div
            className="rounded-lg border border-border p-4 text-sm leading-relaxed text-foreground/90 bg-muted/20"
            style={{ borderLeft: "4px solid rgba(245,158,11,0.6)" }}
          >
            <p className="italic text-muted-foreground text-xs mb-2 uppercase tracking-wider">
              Excerpt from p.{cite.pageNumber}
            </p>
            <p className="leading-relaxed">&quot;{cite.excerpt}&quot;</p>
          </div>
          <div className="mt-4 p-3 rounded-lg bg-primary/5 border border-primary/20 text-xs text-muted-foreground">
            <p className="font-medium text-primary mb-1">About this source</p>
            <p>
              This excerpt was retrieved from the approved facility document library and ranked by
              semantic relevance to your question.
            </p>
          </div>
        </div>

        <div className="p-4 border-t border-border">
          <Button
            variant="outline"
            className="w-full gap-2 text-sm"
            onClick={() => {
              onClose();
              router.push(`/admin/documents/${cite.documentId}/review`);
            }}
          >
            <ExternalLink className="h-4 w-4" />
            View Full Document Section
          </Button>
        </div>
      </div>
    </div>
  );
}
