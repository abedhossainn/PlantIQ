"use client";

import { Badge } from "@/components/ui/badge";
import { Bookmark, BookmarkCheck, ChevronDown, FileText, MessageSquare } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { stripInlineCitations } from "../_helpers";
import type { ChatMessage, Citation } from "@/types";
import type { RefObject } from "react";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  expandedCites: Set<string>;
  savedIds: Set<string>;
  bottomRef: RefObject<HTMLDivElement | null>;
  onToggleCites: (msgId: string) => void;
  onSetActiveCite: (cite: Citation) => void;
  onToggleSave: (msgId: string) => void;
}

export function MessageList({
  messages,
  isStreaming,
  expandedCites,
  savedIds,
  bottomRef,
  onToggleCites,
  onSetActiveCite,
  onToggleSave,
}: MessageListProps) {
  return (
    <div className="flex-1 overflow-y-auto min-h-0 p-4 md:p-6">
      {messages.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-full text-center px-4">
          <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10 border border-primary/20">
            <MessageSquare className="h-8 w-8 text-primary" />
          </div>
          <h2 className="text-xl font-bold tracking-tight mb-2">How can I help you today?</h2>
          <p className="text-muted-foreground mb-8 max-w-md text-sm">
            Ask questions about equipment procedures, troubleshooting steps, safety requirements, or operating parameters
          </p>
        </div>
      ) : (
        <div className="max-w-3xl mx-auto space-y-6 md:space-y-7">
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
                  className={`rounded-2xl px-4 py-3 shadow-sm ${
                    message.role === "user"
                      ? "bg-primary text-primary-foreground font-medium"
                      : "bg-card border border-border"
                  }`}
                >
                  {message.role === "assistant" ? (
                    <div className="text-sm leading-6 text-foreground/90 prose prose-sm dark:prose-invert max-w-none">
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

                {/* Citations */}
                {message.citations && message.citations.length > 0 && (
                  <div className="w-full">
                    <button
                      onClick={() => onToggleCites(message.id)}
                      className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <ChevronDown
                        className={`h-3 w-3 transition-transform duration-150 ${expandedCites.has(message.id) ? "rotate-180" : ""}`}
                      />
                      <span>{message.citations.length} source{message.citations.length !== 1 ? "s" : ""}</span>
                    </button>
                    {expandedCites.has(message.id) && (
                      <div className="flex flex-col gap-1 mt-1.5">
                        {message.citations.map((cite: Citation) => (
                          <button
                            key={cite.id}
                            className="w-full text-left rounded border border-border hover:border-primary/50 hover:bg-primary/5 px-2.5 py-1.5 text-xs transition-all"
                            style={{ borderLeft: "3px solid rgba(245,158,11,0.7)" }}
                            onClick={() => onSetActiveCite(cite)}
                          >
                            <div className="flex items-center gap-1.5 min-w-0">
                              <FileText className="h-3 w-3 text-primary shrink-0" />
                              <span className="font-medium text-foreground flex-1 truncate">{cite.documentTitle}</span>
                              {cite.workspace && (
                                <span className="text-[10px] text-muted-foreground border border-border rounded px-1 py-0.5 shrink-0 leading-none">
                                  {cite.workspace}
                                </span>
                              )}
                              {cite.documentType && (
                                <span className="text-[10px] text-muted-foreground border border-border rounded px-1 py-0.5 shrink-0 leading-none">
                                  {cite.documentType}
                                </span>
                              )}
                              <Badge variant="outline" className="text-[10px] shrink-0 px-1 py-0 h-4 text-primary border-primary/30 leading-none">
                                p.{cite.pageNumber}
                              </Badge>
                            </div>
                            {cite.sectionHeading && (
                              <p className="text-[11px] text-muted-foreground/70 pl-[18px] mt-0.5 truncate">{cite.sectionHeading}</p>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {message.role === "assistant" && (
                  <button
                    onClick={() => onToggleSave(message.id)}
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
  );
}
