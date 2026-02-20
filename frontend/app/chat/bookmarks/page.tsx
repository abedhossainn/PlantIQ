"use client";

import { useState, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Bookmark, FileText, Trash2, Tag } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { getBookmarksByUserId } from "@/lib/mock";
import type { Bookmark as BookmarkType, Citation } from "@/types";
import ReactMarkdown from "react-markdown";

export default function BookmarksPage() {
  const { user } = useAuth();

  // Prefer localStorage bookmarks; fall back to mock data
  const mockFallback = user ? getBookmarksByUserId(user.id) : [];
  const [bookmarks, setBookmarks] = useState<BookmarkType[]>(mockFallback);

  useEffect(() => {
    if (user && typeof window !== "undefined") {
      const raw = localStorage.getItem(`plantiq-bookmarks-${user.id}`);
      if (raw) {
        try {
          const parsed: BookmarkType[] = JSON.parse(raw);
          setBookmarks(parsed.length > 0 ? parsed : mockFallback);
        } catch { /* noop */ }
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  function removeBookmark(bm: BookmarkType) {
    const updated = bookmarks.filter((b) => b.id !== bm.id);
    setBookmarks(updated);
    if (user && typeof window !== "undefined") {
      localStorage.setItem(`plantiq-bookmarks-${user.id}`, JSON.stringify(updated));
      // Also remove from saved-ids
      const raw = localStorage.getItem(`plantiq-saved-${user.id}`);
      if (raw) {
        try {
          const ids: string[] = JSON.parse(raw);
          localStorage.setItem(`plantiq-saved-${user.id}`, JSON.stringify(ids.filter((id) => id !== bm.messageId)));
        } catch { /* noop */ }
      }
    }
  }

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col h-full min-h-0">
        {/* Header */}
        <div className="border-b border-border px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
              <Bookmark className="h-6 w-6 text-primary" />
              Saved Answers
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              Bookmarked troubleshooting solutions for quick reference
            </p>
          </div>
          {bookmarks.length > 0 && (
            <Badge variant="outline" className="text-sm px-3 py-1 text-primary border-primary/30 bg-primary/10">
              {bookmarks.length} {bookmarks.length === 1 ? "bookmark" : "bookmarks"}
            </Badge>
          )}
        </div>

        {/* Bookmarks List */}
        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="p-6 max-w-4xl mx-auto">
            {bookmarks.length === 0 ? (
              <div className="text-center py-16">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted/30 mx-auto mb-4">
                  <Bookmark className="h-8 w-8 text-muted-foreground/50" />
                </div>
                <h2 className="text-lg font-semibold mb-2">No bookmarks yet</h2>
                <p className="text-sm text-muted-foreground max-w-sm mx-auto">
                  Bookmark helpful answers from the chat to save them for quick reference.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {bookmarks.map((bookmark) => (
                  <Card key={bookmark.id} className="overflow-hidden border-border">
                    {/* Query header */}
                    <div className="px-6 pt-5 pb-4 border-b border-border/60">
                      <h3 className="font-semibold text-base leading-snug border-l-4 border-primary/60 pl-3 bg-primary/5 rounded-r py-1.5 pr-3">
                        {bookmark.query}
                      </h3>
                      <p className="text-xs text-muted-foreground mt-2 pl-3">
                        Saved {new Date(bookmark.createdAt).toLocaleDateString("en-US", {
                          year: "numeric", month: "short", day: "numeric",
                        })} at {new Date(bookmark.createdAt).toLocaleTimeString("en-US", {
                          hour: "2-digit", minute: "2-digit",
                        })}
                      </p>
                    </div>

                    <div className="px-6 py-4 space-y-4">
                      {/* Answer excerpt */}
                      <div className="rounded-lg border border-border bg-muted/20 px-4 py-3 text-sm text-foreground/90 line-clamp-4">
                        <ReactMarkdown
                          components={{
                            p: ({ children }) => <span>{children} </span>,
                            strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                            ul: ({ children }) => <ul className="list-disc list-inside my-1">{children}</ul>,
                            ol: ({ children }) => <ol className="list-decimal list-inside my-1">{children}</ol>,
                            li: ({ children }) => <li className="ml-2">{children}</li>,
                            code: ({ children }) => <code className="bg-muted px-1 rounded text-xs font-mono">{children}</code>,
                          }}
                        >
                          {bookmark.answer}
                        </ReactMarkdown>
                      </div>

                      {/* Tags */}
                      {bookmark.tags && bookmark.tags.length > 0 && (
                        <div className="flex flex-wrap items-center gap-2">
                          <Tag className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                          {bookmark.tags.map((tag) => (
                            <Badge
                              key={tag}
                              variant="outline"
                              className="text-xs px-2 py-0.5 text-primary border-primary/20 bg-primary/10"
                            >
                              {tag}
                            </Badge>
                          ))}
                        </div>
                      )}

                      {/* Citations */}
                      {bookmark.citations && bookmark.citations.length > 0 && (
                        <div className="space-y-2">
                          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Sources</p>
                          {bookmark.citations.map((cite: Citation) => (
                            <div
                              key={cite.id}
                              className="rounded-lg border border-border bg-muted/20 p-2.5 text-xs"
                              style={{ borderLeft: "3px solid rgba(245,158,11,0.6)" }}
                            >
                              <div className="flex items-center gap-2">
                                <FileText className="h-3 w-3 text-primary shrink-0" />
                                <span className="font-medium truncate">{cite.documentTitle}</span>
                                <Badge variant="outline" className="ml-auto text-xs px-1.5 py-0 shrink-0">
                                  p.{cite.pageNumber}
                                </Badge>
                              </div>
                              <p className="text-muted-foreground mt-1 pl-5">{cite.sectionHeading}</p>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Notes */}
                      {bookmark.notes && (
                        <p className="text-xs text-muted-foreground italic border-l-2 border-border pl-3">
                          {bookmark.notes}
                        </p>
                      )}

                      <Separator />

                      {/* Actions */}
                      <div className="flex gap-2">
                        <Button size="sm" className="gap-1.5 text-xs font-semibold">
                          <FileText className="h-3.5 w-3.5" />
                          View Full Answer
                        </Button>
                      <Button
                          variant="outline"
                          size="sm"
                          className="gap-1.5 text-xs text-destructive border-destructive/30 hover:bg-destructive/10"
                          onClick={() => removeBookmark(bookmark)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Remove
                        </Button>
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
