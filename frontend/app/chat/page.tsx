"use client";

import { useState, useRef, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Send, Bookmark, FileText, MessageSquare, RotateCcw, X, BookmarkCheck, ExternalLink } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { useRouter } from "next/navigation";
import {
  getActiveConversation,
  createConversation,
  createMessage,
  getConversationMessages,
  createBookmark,
  deleteBookmark,
  isMessageBookmarked,
} from "@/lib/api";
import { streamChatQuery, getLlmStatus } from "@/lib/api/chat";
import type { Citation as ApiCitation, LlmStatus } from "@/lib/api/chat";
import type { ChatMessage, Citation, Bookmark as BookmarkType } from "@/types";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Strip inline citation references appended by the LLM, e.g. [Doc Title, Page 21]
function stripInlineCitations(content: string): string {
  return content.replace(/\s*\[[^\]]*,\s*Page[s]?\s+[\d–-]+[^\]]*\]/gi, "").trim();
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
  
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [query, setQuery] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeCite, setActiveCite] = useState<Citation | null>(null);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(true);
  const [llmStatus, setLlmStatus] = useState<LlmStatus | null>(null);
  const [showColdStartNotice, setShowColdStartNotice] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Poll LLM status every 10 seconds
  useEffect(() => {
    let cancelled = false;
    async function fetchStatus() {
      const status = await getLlmStatus();
      if (!cancelled) setLlmStatus(status);
    }
    fetchStatus();
    const id = setInterval(fetchStatus, 10_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Load active conversation and saved bookmarks on mount
  useEffect(() => {
    async function loadData() {
      if (!user) {
        setIsLoading(false);
        return;
      }
      
      setIsLoading(true);
      try {
        // Try to load active conversation
        const result = await getActiveConversation();
        if (result) {
          setConversationId(result.conversation.id);
          
          // Use messages from result
          const msgs = result.messages;
          setMessages(msgs);
          
          // Load bookmarked message IDs
          const bookmarked = new Set<string>();
          for (const msg of msgs) {
            if (msg.role === 'assistant' && await isMessageBookmarked(msg.id)) {
              bookmarked.add(msg.id);
            }
          }
          setSavedIds(bookmarked);
        }
      } catch (err) {
        console.error('Failed to load conversation:', err);
      } finally {
        setIsLoading(false);
      }
    }

    loadData();
  }, [user]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function newChat() {
    setMessages([]);
    setQuery("");
    setActiveCite(null);
    setConversationId(null);
  }

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!query.trim() || isStreaming || !user) return;

    // Show cold-start notice if LLM container is not yet reachable
    if (llmStatus !== null && !llmStatus.container_reachable) {
      setShowColdStartNotice(true);
    }

    // Create conversation if it doesn't exist
    let currentConvId = conversationId;
    if (!currentConvId) {
      try {
        const newConv = await createConversation();
        currentConvId = newConv.id;
        setConversationId(currentConvId);
      } catch (err) {
        console.error('Failed to create conversation:', err);
        return;
      }
    }

    // Add user message to UI
    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}-user`,
      role: "user",
      content: query.trim(),
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    
    // Save user message to database
    try {
      await createMessage({
        conversationId: currentConvId,
        role: 'user',
        content: userMsg.content,
      });
    } catch (err) {
      console.error('Failed to save user message:', err);
    }

    const queryText = query.trim();
    setQuery("");
    setIsStreaming(true);

    // Create assistant message placeholder
    const assistantMsgId = `msg-${Date.now()}-assistant`;
    const assistantMsg: ChatMessage = {
      id: assistantMsgId,
      role: "assistant",
      content: "",
      timestamp: new Date().toISOString(),
      citations: [],
    };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      let fullContent = "";
      const pendingCitations: Citation[] = [];
      
      // Stream typed events from RAG endpoint.
      for await (const event of streamChatQuery({
        query: queryText,
        conversation_id: currentConvId,
      })) {
        if (event.type === 'token') {
          // Dismiss cold-start notice on first token
          setShowColdStartNotice(false);
          fullContent += event.content;
          // Update message with accumulated content incrementally.
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMsgId
                ? { ...msg, content: fullContent }
                : msg
            )
          );
        } else if (event.type === 'citation') {
          // Transform snake_case API citation to camelCase UI Citation.
          const raw: ApiCitation = event.citation;
          pendingCitations.push({
            id: raw.id,
            documentId: raw.document_id,
            documentTitle: raw.document_title,
            sectionHeading: raw.section_heading ?? '',
            pageNumber: raw.page_number ?? 0,
            excerpt: raw.excerpt,
            relevanceScore: raw.relevance_score,
          });
        } else if (event.type === 'complete') {
          // Stream finished — apply collected citations to the message.
          if (pendingCitations.length > 0) {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMsgId
                  ? { ...msg, citations: pendingCitations }
                  : msg
              )
            );
          }
          break;
        } else if (event.type === 'error') {
          throw new Error(event.error);
        }
      }

      // Apply any citations that arrived before an implicit stream end
      // (no explicit complete event, e.g. connection closed).
      if (pendingCitations.length > 0) {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMsgId && (!msg.citations || msg.citations.length === 0)
              ? { ...msg, citations: pendingCitations }
              : msg
          )
        );
      }
      
      // Save assistant message to database
      try {
        const savedMsg = await createMessage({
          conversationId: currentConvId,
          role: 'assistant',
          content: fullContent,
        });
        
        // Update message ID with the one from database
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMsgId
              ? { ...msg, id: savedMsg.id }
              : msg
          )
        );
      } catch (err) {
        console.error('Failed to save assistant message:', err);
      }
      
    } catch (err) {
      console.error('Streaming failed:', err);
      
      // Show error message
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId
            ? {
                ...msg,
                content: `Error: Failed to generate response. ${err instanceof Error ? err.message : 'Unknown error'}`,
              }
            : msg
        )
      );
    } finally {
      setIsStreaming(false);
    }
  };

  async function toggleSave(msgId: string) {
    const msg = messages.find((m) => m.id === msgId);
    if (!msg || msg.role !== 'assistant' || !user) return;

    try {
      const isBookmarked = savedIds.has(msgId);
      
      if (isBookmarked) {
        // Remove bookmark
        await deleteBookmark(msgId);
        setSavedIds((prev) => {
          const next = new Set(prev);
          next.delete(msgId);
          return next;
        });
      } else {
        // Create bookmark - query/answer/citations auto-populated from message
        await createBookmark({
          messageId: msgId,
          conversationId: conversationId || 'unknown',
        });
        
        setSavedIds((prev) => new Set(prev).add(msgId));
      }
    } catch (err) {
      console.error('Failed to toggle bookmark:', err);
    }
  }

  const suggestions = [
    "What is the density of LNG at atmospheric pressure?",
    "How do I start up the cryogenic pump?",
    "What actions should I take if there is an LNG spill?",
    "What are the calibration requirements for pressure transmitters?",
  ];

  if (isLoading) {
    return (
      <AppLayout>
        <div className="flex items-center justify-center h-full">
          <div className="flex flex-col items-center gap-4">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            <p className="text-sm text-muted-foreground">Loading conversation...</p>
          </div>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col h-full min-h-0">
        {/* Chat header */}
        <div className="border-b border-border px-6 py-3 flex items-center justify-between bg-card/40">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-primary" />
            <span className="font-semibold text-sm">PlantIQ Assistant</span>
            {llmStatus === null ? (
              <Badge variant="outline" className="text-xs text-muted-foreground border-muted-foreground/30">
                LLM Offline
              </Badge>
            ) : !llmStatus.container_reachable ? (
              <Badge variant="outline" className="text-xs text-amber-400 border-amber-400/30 bg-amber-400/10 animate-pulse">
                LLM Starting...
              </Badge>
            ) : llmStatus.active_requests > 0 ? (
              <Badge variant="outline" className="text-xs text-amber-400 border-amber-400/30 bg-amber-400/10">
                Generating...
              </Badge>
            ) : (
              <Badge variant="outline" className="text-xs text-green-400 border-green-400/30 bg-green-400/10">
                LLM Ready
              </Badge>
            )}
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
                            remarkPlugins={[remarkGfm]}
                            components={{
                              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                              strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
                              ul: ({ children }) => <ul className="list-disc list-inside my-2 space-y-1">{children}</ul>,
                              ol: ({ children }) => <ol className="list-decimal list-inside my-2 space-y-1">{children}</ol>,
                              li: ({ children }) => <li className="ml-2">{children}</li>,
                              code: ({ children }) => <code className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono">{children}</code>,
                              table: ({ children }) => <div className="overflow-x-auto my-3"><table className="w-full text-xs border-collapse border border-border">{children}</table></div>,
                              thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
                              th: ({ children }) => <th className="border border-border px-2 py-1.5 text-left font-semibold">{children}</th>,
                              td: ({ children }) => <td className="border border-border px-2 py-1.5">{children}</td>,
                            }}
                          >
                            {stripInlineCitations(message.content)}
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

        {/* Cold-start notice */}
        {showColdStartNotice && (
          <div className="border-t border-amber-400/20 bg-amber-400/5 px-6 py-2 text-xs text-amber-400 flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
            Starting LLM — this may take up to 45 seconds on first request
          </div>
        )}

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
