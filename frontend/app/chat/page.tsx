"use client";

import { useState, useRef, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Send, Bookmark, FileText, MessageSquare, RotateCcw, X, BookmarkCheck, ExternalLink } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { useRouter } from "next/navigation";
import { getActiveConversation } from "@/lib/mock";
import type { ChatMessage, Citation, Bookmark as BookmarkType } from "@/types";
import ReactMarkdown from "react-markdown";

// ---------------------------------------------------------------------------
// Citation pool — representative citations from approved documents
// In production these come from the RAG retrieval layer
// ---------------------------------------------------------------------------
const CITATION_POOL: Citation[] = [
  {
    id: "cite-p1",
    documentId: "doc-1",
    documentTitle: "COMMON Module 3 Characteristics of LNG",
    sectionHeading: "3. Physical Properties of LNG",
    pageNumber: 12,
    excerpt: "LNG density at atmospheric pressure is approximately 450 kg/m³ at -162°C. This density varies with composition and temperature.",
    relevanceScore: 0.94,
  },
  {
    id: "cite-p2",
    documentId: "doc-2",
    documentTitle: "Cryogenic Pump System Operating Manual",
    sectionHeading: "3.1 Emergency Response",
    pageNumber: 15,
    excerpt: "In case of LNG spill: Activate emergency alarm, evacuate non-essential personnel to upwind locations, do NOT use water on LNG spills.",
    relevanceScore: 0.91,
  },
  {
    id: "cite-p3",
    documentId: "doc-2",
    documentTitle: "Cryogenic Pump System Operating Manual",
    sectionHeading: "4.2 Normal Startup Sequence",
    pageNumber: 21,
    excerpt: "Cool-down procedure: Slowly introduce LNG to pump casing. Monitor temperature differential (<50°C/hr cooling rate). Allow 4–6 hours for complete thermal stabilization.",
    relevanceScore: 0.96,
  },
  {
    id: "cite-p4",
    documentId: "doc-6",
    documentTitle: "Instrumentation Calibration Standards",
    sectionHeading: "5.2 Pressure Transmitter Calibration",
    pageNumber: 34,
    excerpt: "Pressure transmitters shall be calibrated at 0%, 25%, 50%, 75%, and 100% of span in both ascending and descending directions. Maximum allowable error: ±0.25% of span.",
    relevanceScore: 0.92,
  },
  {
    id: "cite-p5",
    documentId: "doc-1",
    documentTitle: "COMMON Module 3 Characteristics of LNG",
    sectionHeading: "2.4 Boil-Off Gas Management",
    pageNumber: 8,
    excerpt: "Normal boil-off rate for insulated LNG storage is 0.05-0.1% per day. BOG must be managed through either reliquefaction or fuel gas systems.",
    relevanceScore: 0.88,
  },
];

/** Deterministically pick 1–2 citations from the pool based on query content */
function pickCitations(query: string): Citation[] {
  // Simple hash to get a consistent index per query
  let h = 0;
  for (let i = 0; i < query.length; i++) h = (h * 31 + query.charCodeAt(i)) & 0xffffff;
  const primary = CITATION_POOL[h % CITATION_POOL.length];
  const secondary = CITATION_POOL[(h + 2) % CITATION_POOL.length];
  return primary.id === secondary.id ? [primary] : [primary, secondary];
}

// Source view drawer
function SourceDrawer({ cite, onClose }: { cite: Citation; onClose: () => void }) {
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
            <p className="italic text-muted-foreground text-xs mb-2 uppercase tracking-wider">Excerpt from p.{cite.pageNumber}</p>
            <p className="leading-relaxed">&quot;{cite.excerpt}&quot;</p>
          </div>
          <div className="mt-4 p-3 rounded-lg bg-primary/5 border border-primary/20 text-xs text-muted-foreground">
            <p className="font-medium text-primary mb-1">About this source</p>
            <p>This excerpt was retrieved from the approved facility document library and ranked by semantic relevance to your question.</p>
          </div>
        </div>

        <div className="p-4 border-t border-border">
          <Button variant="outline" className="w-full gap-2 text-sm" onClick={() => {
            onClose();
            router.push(`/admin/documents/${cite.documentId}/review`);
          }}>
            <ExternalLink className="h-4 w-4" />
            View Full Document Section
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function ChatPage() {
  const { user } = useAuth();
  const router = useRouter();
  const initialConv = user ? getActiveConversation(user.id) : null;
  const [messages, setMessages] = useState<ChatMessage[]>(initialConv?.messages ?? []);
  const [query, setQuery] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeCite, setActiveCite] = useState<Citation | null>(null);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load persisted saved-answer IDs from localStorage (US-2.5)
  useEffect(() => {
    if (user && typeof window !== "undefined") {
      const raw = localStorage.getItem(`plantiq-saved-${user.id}`);
      if (raw) { try { setSavedIds(new Set(JSON.parse(raw))); } catch { /* noop */ } }
    }
  }, [user]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function newChat() {
    setMessages([]);
    setQuery("");
    setActiveCite(null);
  }

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!query.trim() || isStreaming) return;

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: query.trim(),
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setQuery("");
    setIsStreaming(true);

    await new Promise((r) => setTimeout(r, 1200));

    const citations = pickCitations(query.trim());
    const assistantMsg: ChatMessage = {
      id: `msg-${Date.now() + 1}`,
      role: "assistant",
      content:
        "This response is retrieved from your approved facility documents via the PlantIQ RAG system. In production this queries the vector database and returns information from indexed technical documents.\n\nThe system uses **Retrieval-Augmented Generation (RAG)** to:\n- Search indexed facility documents\n- Retrieve the most relevant sections\n- Generate a precise, cited answer",
      timestamp: new Date().toISOString(),
      citations,
    };
    setMessages((prev) => [...prev, assistantMsg]);
    setIsStreaming(false);
  };

  function toggleSave(msgId: string) {
    setSavedIds((prev) => {
      const next = new Set(prev);
      if (next.has(msgId)) {
        next.delete(msgId);
        // Remove from localStorage bookmarks
        if (user && typeof window !== "undefined") {
          const stored: BookmarkType[] = JSON.parse(localStorage.getItem(`plantiq-bookmarks-${user.id}`) ?? "[]");
          const filtered = stored.filter((b) => b.messageId !== msgId);
          localStorage.setItem(`plantiq-bookmarks-${user.id}`, JSON.stringify(filtered));
        }
      } else {
        next.add(msgId);
        // Persist to localStorage as a bookmark (US-2.5)
        if (user && typeof window !== "undefined") {
          const msg = messages.find((m) => m.id === msgId);
          const userMsgIdx = msg ? messages.indexOf(msg) - 1 : -1;
          const userMsg = userMsgIdx >= 0 ? messages[userMsgIdx] : null;
          if (msg) {
            const bookmark: BookmarkType = {
              id: `bm-${msgId}`,
              userId: user.id,
              conversationId: "current-session",
              messageId: msgId,
              query: userMsg?.content ?? "Question",
              answer: msg.content,
              citations: msg.citations,
              createdAt: new Date().toISOString(),
              tags: [],
            };
            const stored: BookmarkType[] = JSON.parse(localStorage.getItem(`plantiq-bookmarks-${user.id}`) ?? "[]");
            if (!stored.some((b) => b.messageId === msgId)) {
              stored.unshift(bookmark);
              localStorage.setItem(`plantiq-bookmarks-${user.id}`, JSON.stringify(stored));
            }
          }
        }
      }
      if (user && typeof window !== "undefined") {
        localStorage.setItem(`plantiq-saved-${user.id}`, JSON.stringify([...next]));
      }
      return next;
    });
  }

  const suggestions = [
    "What is the density of LNG at atmospheric pressure?",
    "How do I start up the cryogenic pump?",
    "What actions should I take if there is an LNG spill?",
    "What are the calibration requirements for pressure transmitters?",
  ];

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col h-full min-h-0">
        {/* Chat header */}
        <div className="border-b border-border px-6 py-3 flex items-center justify-between bg-card/40">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-primary" />
            <span className="font-semibold text-sm">PlantIQ Assistant</span>
            <Badge variant="outline" className="text-xs text-green-400 border-green-400/30 bg-green-400/10">
              Online
            </Badge>
          </div>
          {messages.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 text-xs"
              onClick={newChat}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              New Chat
            </Button>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto min-h-0 p-6">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center px-4">
              <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10 border border-primary/20">
                <MessageSquare className="h-8 w-8 text-primary" />
              </div>
              <h2 className="text-xl font-bold mb-2">How can I help you today?</h2>
              <p className="text-muted-foreground mb-8 max-w-md text-sm">
                Ask questions about equipment procedures, troubleshooting steps, safety requirements, or operating parameters
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-2xl w-full">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    className="text-left rounded-lg border border-border bg-card hover:border-primary/50 hover:bg-primary/5 p-4 text-sm transition-all leading-snug text-muted-foreground hover:text-foreground"
                    onClick={() => setQuery(s)}
                  >
                    <FileText className="h-3.5 w-3.5 text-primary mb-2" />
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto space-y-6">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex gap-4 ${message.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  {message.role === "assistant" && (
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/15 border border-primary/20 mt-1">
                      <MessageSquare className="h-4 w-4 text-primary" />
                    </div>
                  )}
                  <div className={`max-w-[80%] space-y-3 ${message.role === "user" ? "items-end" : "items-start"} flex flex-col`}>
                    <div
                      className={`rounded-2xl px-4 py-3 ${
                        message.role === "user"
                          ? "bg-primary text-primary-foreground font-medium"
                          : "bg-card border border-border"
                      }`}
                    >
                      {message.role === "assistant" ? (
                        <div className="text-sm text-foreground/90 prose prose-sm dark:prose-invert max-w-none">
                          <ReactMarkdown
                            components={{
                              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                              strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
                              ul: ({ children }) => <ul className="list-disc list-inside my-2 space-y-1">{children}</ul>,
                              ol: ({ children }) => <ol className="list-decimal list-inside my-2 space-y-1">{children}</ol>,
                              li: ({ children }) => <li className="ml-2">{children}</li>,
                              code: ({ children }) => <code className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono">{children}</code>,
                            }}
                          >
                            {message.content}
                          </ReactMarkdown>
                        </div>
                      ) : (
                        <p className="text-sm">{message.content}</p>
                      )}
                    </div>

                    {/* Citations — clickable (US-2.3) */}
                    {message.citations && message.citations.length > 0 && (
                      <div className="space-y-2 w-full">
                        <p className="text-xs text-muted-foreground font-semibold uppercase tracking-wider">Sources:</p>
                        {message.citations.map((cite: Citation) => (
                          <button
                            key={cite.id}
                            className="w-full text-left rounded-lg bg-card border border-border hover:border-primary/50 hover:bg-primary/5 p-3 text-xs transition-all"
                            style={{ borderLeft: "3px solid rgba(245,158,11,0.7)" }}
                            onClick={() => setActiveCite(cite)}
                          >
                            <div className="flex items-start gap-2 mb-1">
                              <FileText className="h-3 w-3 text-primary shrink-0 mt-0.5" />
                              <span className="font-semibold text-foreground flex-1">{cite.documentTitle}</span>
                              <Badge variant="outline" className="ml-auto text-xs shrink-0 px-1.5 py-0 text-primary border-primary/30">
                                p.{cite.pageNumber}
                              </Badge>
                            </div>
                            <p className="text-muted-foreground pl-5 mb-1">{cite.sectionHeading}</p>
                            <p className="text-muted-foreground/75 italic pl-5 line-clamp-2">&quot;{cite.excerpt}&quot;</p>
                            <p className="text-primary/70 text-xs pl-5 mt-1.5">Click to view source →</p>
                          </button>
                        ))}
                      </div>
                    )}

                    {message.role === "assistant" && (
                      <button
                        onClick={() => toggleSave(message.id)}
                        className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border transition-all ${
                          savedIds.has(message.id)
                            ? "border-primary/40 bg-primary/10 text-primary"
                            : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground"
                        }`}
                      >
                        {savedIds.has(message.id) ? (
                          <BookmarkCheck className="h-3 w-3" />
                        ) : (
                          <Bookmark className="h-3 w-3" />
                        )}
                        {savedIds.has(message.id) ? "Saved" : "Save Answer"}
                      </button>
                    )}
                  </div>
                </div>
              ))}

              {isStreaming && (
                <div className="flex gap-4">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/15 border border-primary/20 mt-1">
                    <MessageSquare className="h-4 w-4 text-primary" />
                  </div>
                  <div className="bg-card border border-border rounded-2xl px-4 py-3">
                    <div className="flex gap-1">
                      <span className="h-2 w-2 rounded-full bg-muted-foreground animate-bounce [animation-delay:0ms]" />
                      <span className="h-2 w-2 rounded-full bg-muted-foreground animate-bounce [animation-delay:150ms]" />
                      <span className="h-2 w-2 rounded-full bg-muted-foreground animate-bounce [animation-delay:300ms]" />
                    </div>
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t border-border p-4 bg-card/30">
          <form onSubmit={handleSubmit} className="max-w-3xl mx-auto">
            <div className="flex gap-2 items-end">
              <Textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ask about equipment, procedures, or safety..."
                className="min-h-[52px] max-h-[200px] resize-none bg-card border-border"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSubmit();
                  }
                }}
              />
              <Button type="submit" size="icon" disabled={!query.trim() || isStreaming} className="shrink-0 h-12 w-12">
                <Send className="h-4 w-4" />
              </Button>
            </div>
            <p className="text-xs text-muted-foreground mt-2 text-center">
              Responses generated from approved facility documents only · Press Enter to send
            </p>
          </form>
        </div>
      </div>

      {/* Source drawer overlay (US-2.3) */}
      {activeCite && <SourceDrawer cite={activeCite} onClose={() => setActiveCite(null)} />}
    </AppLayout>
  );
}
