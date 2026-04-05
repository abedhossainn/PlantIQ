"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { X } from "lucide-react";

export function EditableList({
  label,
  items,
  onChange,
  readOnly = false,
}: {
  label: string;
  items: string[];
  onChange: (next: string[]) => void;
  readOnly?: boolean;
}) {
  const [draft, setDraft] = useState("");

  function addItem() {
    const trimmed = draft.trim();
    if (!trimmed) return;
    onChange([...items, trimmed]);
    setDraft("");
  }

  function removeItem(idx: number) {
    onChange(items.filter((_, i) => i !== idx));
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      {items.length === 0 && (
        <p className="text-xs text-muted-foreground italic">None</p>
      )}
      <ul className="space-y-1">
        {items.map((item, idx) => (
          <li key={idx} className="flex items-start gap-1.5">
            <span className="flex-1 text-xs leading-snug text-foreground/80 pt-0.5 break-words">
              {item}
            </span>
            {!readOnly && (
              <button
                aria-label="Remove"
                className="text-muted-foreground hover:text-red-400 shrink-0 mt-0.5"
                onClick={() => removeItem(idx)}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </li>
        ))}
      </ul>
      {!readOnly && (
        <div className="flex gap-1.5 pt-1">
          <input
            className="flex-1 rounded border border-border bg-background px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
            placeholder="Add item…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addItem();
              }
            }}
          />
          <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={addItem}>
            Add
          </Button>
        </div>
      )}
    </div>
  );
}
