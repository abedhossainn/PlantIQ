"use client";

import { AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";
import type { OptimizedChunk } from "@/types";

interface ChunkListProps {
  chunks: OptimizedChunk[];
  selectedIdx: number;
  saveState: Record<string, "saving" | "saved" | "error">;
  onSelect: (idx: number) => void;
}

export function ChunkList({ chunks, selectedIdx, saveState, onSelect }: ChunkListProps) {
  return (
    <div className="flex flex-col border-r border-border min-h-0">
      <div className="p-3 border-b border-border shrink-0">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Chunks · {selectedIdx + 1} of {chunks.length}
        </p>
      </div>
      <div className="flex-1 overflow-y-auto min-h-0 p-2 space-y-1">
        {chunks.map((chunk, idx) => {
          const isSelected = idx === selectedIdx;
          const cs = saveState[chunk.id];
          return (
            <button
              key={chunk.id}
              onClick={() => onSelect(idx)}
              className={`w-full text-left p-3 rounded text-sm transition-colors border-l-4 ${
                isSelected
                  ? "bg-primary/12 border-l-primary"
                  : "hover:bg-muted/40 border-l-transparent"
              }`}
            >
              <div className="flex items-center justify-between gap-2 mb-0.5">
                <p className={`text-xs font-semibold truncate ${isSelected ? "text-foreground" : "text-muted-foreground"}`}>
                  Chunk {chunk.chunk_number}
                </p>
                <div className="flex items-center gap-1 shrink-0">
                  {cs === "saving" && <RefreshCw className="h-3 w-3 text-muted-foreground animate-spin" />}
                  {cs === "saved" && <CheckCircle2 className="h-3 w-3 text-green-400" />}
                  {cs === "error" && <AlertTriangle className="h-3 w-3 text-red-400" />}
                </div>
              </div>
              {chunk.text_preview && (
                <p className="text-[10px] text-muted-foreground/60 line-clamp-2 leading-snug">
                  {chunk.text_preview}
                </p>
              )}
              {chunk.source_pages.length > 0 && (
                <div className="flex gap-1 flex-wrap mt-1">
                  {chunk.source_pages.slice(0, 3).map((pg) => (
                    <span key={pg} className="text-[9px] bg-muted/60 text-muted-foreground rounded px-1 py-0.5">
                      p{pg}
                    </span>
                  ))}
                  {chunk.source_pages.length > 3 && (
                    <span className="text-[9px] text-muted-foreground">
                      +{chunk.source_pages.length - 3}
                    </span>
                  )}
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
