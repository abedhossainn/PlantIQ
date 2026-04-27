"use client";

import { useState, useRef, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Send, MessageSquare, RotateCcw, Pin, PinOff, LogOut, ChevronDown, PanelLeft, Plus, Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useRouter } from "next/navigation";
import {
  ApiError,
  createBookmark,
  deleteBookmark,
  formatScopeDeniedMessage,
  getConversationById,
  parseScopeAccessDeniedPayload,
} from "@/lib/api";
import { canAccessFeedbackMetrics, getChatFeedbackMetrics, streamChatQuery, getLlmStatus, submitChatFeedback } from "@/lib/api/chat";
import type { ChatQualityMetricsResponse, Citation as ApiCitation, LlmStatus } from "@/lib/api/chat";
import type { ChatMessage, Citation, Conversation } from "@/types";
import { DEFAULT_CONVERSATION_WORKSPACE_FILTER, WORKSPACE_OPTIONS } from "./_constants";
import { getInitials, getConversationDisplayTitle } from "./_helpers";
import { SourceDrawer } from "./_components/SourceDrawer";
import { ConversationSidebar } from "./_components/ConversationSidebar";
import { MessageList, type AssistantFeedbackSubmitInput } from "./_components/MessageList";
import { useConversations } from "./_hooks/useConversations";
import { ProfileDialog } from "@/components/shared/ProfileDialog";

interface ScopeDeniedState {
  lockKey: string;
  message: string;
  reasonCode?: string;
}

function getConversationScopeKey(input: {
  workspace: string;
  includeSharedDocuments: boolean;
}): string {
  return [
    `workspace=${input.workspace.trim().toLowerCase()}`,
    `shared=${input.includeSharedDocuments ? "1" : "0"}`,
  ].join("|");
}

export default function ChatPage() {
  const { user, isAdmin, logout } = useAuth();
  const router = useRouter();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeCite, setActiveCite] = useState<Citation | null>(null);
  const [expandedCites, setExpandedCites] = useState<Set<string>>(new Set());
  const [llmStatus, setLlmStatus] = useState<LlmStatus | null>(null);
  const [showColdStartNotice, setShowColdStartNotice] = useState(false);
  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const [scopeDeniedState, setScopeDeniedState] = useState<ScopeDeniedState | null>(null);
  const [showConversationSidebar, setShowConversationSidebar] = useState(true);
  const [showProfileDialog, setShowProfileDialog] = useState(false);
  const [showFeedbackMetrics, setShowFeedbackMetrics] = useState(false);
  const [feedbackMetricsWindowDays, setFeedbackMetricsWindowDays] = useState<7 | 30 | 90>(30);
  const [feedbackMetricsScopeMode, setFeedbackMetricsScopeMode] = useState<"all" | "current">("all");
  const [feedbackMetrics, setFeedbackMetrics] = useState<ChatQualityMetricsResponse | null>(null);
  const [feedbackMetricsError, setFeedbackMetricsError] = useState<string | null>(null);
  const [isFeedbackMetricsLoading, setIsFeedbackMetricsLoading] = useState(false);
  const [feedbackMetricsRefreshKey, setFeedbackMetricsRefreshKey] = useState(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  const toggleCites = (msgId: string) =>
    setExpandedCites((prev) => {
      const next = new Set(prev);
      next.has(msgId) ? next.delete(msgId) : next.add(msgId);
      return next;
    });

  function clearChat() {
    setMessages([]);
    setQuery("");
    setActiveCite(null);
    setSavedIds(new Set());
  }

  const conv = useConversations({
    user,
    onClearChat: clearChat,
    onSetMessages: setMessages,
    onSetSavedIds: setSavedIds,
  });

  const currentScopeKey = getConversationScopeKey({
    workspace: conv.selectedWorkspace,
    includeSharedDocuments: conv.includeSharedDocuments,
  });
  const isScopeRetryBlocked = Boolean(scopeDeniedState && scopeDeniedState.lockKey === currentScopeKey);
  const canViewFeedbackMetrics = canAccessFeedbackMetrics(user?.role);

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

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

  // Close profile menu when clicking outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (!target.closest("[data-profile-menu]")) setShowProfileMenu(false);
    }
    if (showProfileMenu) {
      document.addEventListener("click", handleClickOutside);
      return () => document.removeEventListener("click", handleClickOutside);
    }
  }, [showProfileMenu]);

  // Close profile menu with Escape for keyboard users
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setShowProfileMenu(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Keyboard shortcuts:
  // - Ctrl/Cmd + B: toggle conversations sidebar
  // - Ctrl/Cmd + Shift + N: start a new thread
  useEffect(() => {
    function isTypingTarget(target: EventTarget | null) {
      const el = target as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName?.toLowerCase();
      return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
    }

    function onKeyDown(event: KeyboardEvent) {
      if (isTypingTarget(event.target)) return;

      const isModifier = event.metaKey || event.ctrlKey;
      if (!isModifier) return;

      if (event.key.toLowerCase() === "b" && !event.shiftKey) {
        event.preventDefault();
        setShowConversationSidebar((prev) => !prev);
      }

      if (event.key.toLowerCase() === "n" && event.shiftKey) {
        event.preventDefault();
        newChat();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [messages.length]);

  useEffect(() => {
    if (!scopeDeniedState) {
      return;
    }

    if (scopeDeniedState.lockKey !== currentScopeKey) {
      setScopeDeniedState(null);
    }
  }, [currentScopeKey, scopeDeniedState]);

  useEffect(() => {
    if (!canViewFeedbackMetrics || !showFeedbackMetrics) {
      return;
    }

    let cancelled = false;

    async function loadFeedbackMetrics() {
      setIsFeedbackMetricsLoading(true);
      setFeedbackMetricsError(null);

      try {
        const metrics = await getChatFeedbackMetrics({
          window_days: feedbackMetricsWindowDays,
          area_scope: feedbackMetricsScopeMode === "current" ? conv.selectedWorkspace : undefined,
        });

        if (!cancelled) {
          setFeedbackMetrics(metrics);
        }
      } catch (error) {
        if (!cancelled) {
          setFeedbackMetricsError(
            error instanceof Error ? error.message : "Failed to retrieve answer-quality metrics.",
          );
        }
      } finally {
        if (!cancelled) {
          setIsFeedbackMetricsLoading(false);
        }
      }
    }

    void loadFeedbackMetrics();

    return () => {
      cancelled = true;
    };
  }, [
    canViewFeedbackMetrics,
    conv.selectedWorkspace,
    feedbackMetricsRefreshKey,
    feedbackMetricsScopeMode,
    feedbackMetricsWindowDays,
    showFeedbackMetrics,
  ]);

  async function submitAssistantFeedback(input: AssistantFeedbackSubmitInput): Promise<void> {
    try {
      await submitChatFeedback({
        answer_message_id: input.answerMessageId,
        conversation_id: conv.conversationId || undefined,
        sentiment: input.sentiment,
        reason_code: input.reasonCode,
        comment: input.comment,
        area_scope: conv.selectedWorkspace,
      });

      if (canViewFeedbackMetrics) {
        setFeedbackMetricsRefreshKey((prev) => prev + 1);
      }
    } catch (error) {
      throw error instanceof Error
        ? error
        : new Error("Failed to submit answer feedback.");
    }
  }

  function newChat() {
    clearChat();
    conv.setConversationId(null);
    conv.setSelectedWorkspace("Liquefaction");
    conv.setIncludeSharedDocuments(true);
  }

  const handleSubmit = async (e?: { preventDefault: () => void }) => {
    e?.preventDefault();
    if (isScopeRetryBlocked) return;
    if (!query.trim() || isStreaming || !user) return;

    if (llmStatus !== null && !llmStatus.container_reachable) {
      setShowColdStartNotice(true);
    }

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}-user`,
      role: "user",
      content: query.trim(),
      timestamp: new Date().toISOString(),
      workspace: conv.selectedWorkspace,
    };
    setMessages((prev) => [...prev, userMsg]);

    const queryText = query.trim();
    setQuery("");
    setIsStreaming(true);
    setScopeDeniedState(null);

    const assistantMsgId = `msg-${Date.now()}-assistant`;
    setMessages((prev) => [
      ...prev,
      { id: assistantMsgId, role: "assistant", content: "", timestamp: new Date().toISOString(), workspace: conv.selectedWorkspace, citations: [] },
    ]);

    let activeAssistantMessageId = assistantMsgId;
    try {
      let fullContent = "";
      const pendingCitations: Citation[] = [];
      let resolvedConversationId = conv.conversationId;

      for await (const event of streamChatQuery({
        query: queryText,
        conversation_id: conv.conversationId || undefined,
        workspace: conv.selectedWorkspace,
        include_shared_documents: conv.includeSharedDocuments,
      })) {
        if (event.conversation_id) {
          resolvedConversationId = event.conversation_id;
          conv.setConversationId(event.conversation_id);
        }

        if (event.message_id && event.message_id !== activeAssistantMessageId) {
          const prev = activeAssistantMessageId;
          activeAssistantMessageId = event.message_id;
          setMessages((msgs) => msgs.map((m) => (m.id === prev ? { ...m, id: activeAssistantMessageId } : m)));
        }

        if (event.type === "token") {
          setShowColdStartNotice(false);
          fullContent += event.content;
          setMessages((msgs) => msgs.map((m) => (m.id === activeAssistantMessageId ? { ...m, content: fullContent } : m)));
        } else if (event.type === "citation") {
          const raw: ApiCitation = event.citation;
          pendingCitations.push({
            id: raw.id, documentId: raw.document_id, documentTitle: raw.document_title,
            sectionHeading: raw.section_heading ?? "", pageNumber: raw.page_number ?? 0,
            workspace: raw.workspace, system: raw.system, documentType: raw.document_type,
            excerpt: raw.excerpt, relevanceScore: raw.relevance_score,
          });
        } else if (event.type === "complete") {
          if (pendingCitations.length > 0) {
            setMessages((msgs) => msgs.map((m) => (m.id === activeAssistantMessageId ? { ...m, citations: pendingCitations } : m)));
          }
          break;
        } else if (event.type === "error") {
          if (event.code === "SCOPE_ACCESS_DENIED") {
            throw new ApiError(event.error, 403, {
              code: event.code,
              reason_code: event.reason_code,
              requested_scope: event.requested_scope,
              message: event.error,
            });
          }
          throw new Error(event.error);
        }
      }

      if (pendingCitations.length > 0) {
        setMessages((msgs) => msgs.map((m) =>
          m.id === activeAssistantMessageId && (!m.citations || m.citations.length === 0)
            ? { ...m, citations: pendingCitations } : m
        ));
      }

      if (resolvedConversationId) {
        try {
          const refreshed = await getConversationById(resolvedConversationId);
          conv.setConversationId(refreshed.id);
          conv.applyConversationScope(refreshed);
          setMessages(refreshed.messages);
          await conv.loadConversationIndex(refreshed.id);
        } catch (err) {
          console.error("Failed to refresh conversation after streaming:", err);
        }
      }
    } catch (err) {
      console.error("Streaming failed:", err);

      if (err instanceof ApiError && err.status === 403) {
        const denied = parseScopeAccessDeniedPayload(err.data);
        if (denied) {
          const requestedWorkspace = typeof denied.requested_scope?.workspace === "string"
            ? denied.requested_scope.workspace
            : conv.selectedWorkspace;
          const requestedIncludeShared = typeof denied.requested_scope?.include_shared_documents === "boolean"
            ? denied.requested_scope.include_shared_documents
            : conv.includeSharedDocuments;

          setScopeDeniedState({
            lockKey: getConversationScopeKey({
              workspace: requestedWorkspace,
              includeSharedDocuments: requestedIncludeShared,
            }),
            message: formatScopeDeniedMessage(denied),
            reasonCode: denied.reason_code,
          });

          setMessages((msgs) => msgs.map((m) =>
            m.id === activeAssistantMessageId
              ? {
                ...m,
                content: `Scope access denied. ${formatScopeDeniedMessage(denied)} Update scope settings and retry.`,
              }
              : m
          ));
          return;
        }
      }

      setMessages((msgs) => msgs.map((m) =>
        m.id === activeAssistantMessageId
          ? { ...m, content: `Error: Failed to generate response. ${err instanceof Error ? err.message : "Unknown error"}` }
          : m
      ));
    } finally {
      setIsStreaming(false);
    }
  };

  async function toggleSave(msgId: string) {
    const msg = messages.find((m) => m.id === msgId);
    if (!msg || msg.role !== "assistant" || !user) return;

    try {
      if (savedIds.has(msgId)) {
        await deleteBookmark(msgId);
        setSavedIds((prev) => { const next = new Set(prev); next.delete(msgId); return next; });
      } else {
        await createBookmark({ messageId: msgId, conversationId: conv.conversationId || "unknown" });
        setSavedIds((prev) => new Set(prev).add(msgId));
      }
    } catch (err) {
      console.error("Failed to toggle bookmark:", err);
    }
  }

  if (conv.isLoading) {
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

  const sidebarProps = {
    conversationId: conv.conversationId,
    filteredConversations: conv.filteredConversations,
    conversationCount: conv.conversations.length,
    pinnedConversationCount: conv.pinnedConversationCount,
    conversationSearch: conv.conversationSearch,
    conversationWorkspaceFilter: conv.conversationWorkspaceFilter,
    showPinnedOnly: conv.showPinnedOnly,
    hasActiveConversationDiscoveryFilters: conv.hasActiveConversationDiscoveryFilters,
    editingConversationId: conv.editingConversationId,
    editingConversationTitle: conv.editingConversationTitle,
    onSearchChange: conv.setConversationSearch,
    onWorkspaceFilterChange: conv.setConversationWorkspaceFilter,
    onTogglePinnedOnly: () => conv.setShowPinnedOnly((prev) => !prev),
    onResetFilters: conv.resetConversationDiscoveryFilters,
    onSelectConversation: (conversation: Conversation) => { void conv.handleSelectConversation(conversation); },
    onStartEdit: conv.startConversationTitleEdit,
    onSaveTitle: (id: string) => { void conv.saveConversationTitle(id); },
    onCancelEdit: conv.cancelConversationTitleEdit,
    onTogglePin: (conversation: Conversation) => { void conv.handleToggleConversationPin(conversation); },
    onDeleteConversation: (id: string) => { void conv.handleDeleteConversation(id); },
    onTitleEditChange: conv.setEditingConversationTitle,
    onStartNewConversation: newChat,
  };

  return (
    <AppLayout
      sidebarContent={!isAdmin && showConversationSidebar ? <ConversationSidebar {...sidebarProps} /> : undefined}
      hideSidebar={!isAdmin && !showConversationSidebar}
    >
      <div className="flex-1 flex h-full min-h-0 overflow-hidden">
        {isAdmin && showConversationSidebar && (
          <aside className="w-80 shrink-0 border-r border-border bg-card/30 hidden lg:flex lg:flex-col">
            <ConversationSidebar {...sidebarProps} />
          </aside>
        )}

        <div className="flex-1 flex flex-col h-full min-h-0 overflow-hidden">
          {/* Chat header */}
          <div className="border-b border-border px-4 md:px-6 py-2.5 flex items-center justify-between gap-2 bg-card/50">
            <div className="flex items-center gap-2 min-w-0 shrink-0">
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={() => setShowConversationSidebar((prev) => !prev)}
                aria-label={showConversationSidebar ? "Hide conversations sidebar" : "Show conversations sidebar"}
                title="Toggle conversations sidebar (Ctrl/Cmd+B)"
              >
                <PanelLeft className="h-4 w-4" />
              </Button>
              <MessageSquare className="h-5 w-5 text-primary" />
              <span className="font-semibold text-sm tracking-tight">PlantIQ Assistant</span>
            </div>

            <div className="hidden xl:flex items-center gap-2 flex-1 justify-center min-w-0 px-3">
              <span className="text-[11px] uppercase tracking-wide text-muted-foreground ml-1">Scope</span>
              <Select value={conv.selectedWorkspace} onValueChange={conv.setSelectedWorkspace}>
                <SelectTrigger className="h-8 w-[180px] text-[11px] rounded-full bg-background/80 border-border/80">
                  <SelectValue placeholder="Workspace scope" />
                </SelectTrigger>
                <SelectContent>
                  {WORKSPACE_OPTIONS.map((ws) => <SelectItem key={ws} value={ws}>{ws}</SelectItem>)}
                </SelectContent>
              </Select>
              <Button
                type="button"
                size="sm"
                variant={conv.includeSharedDocuments ? "default" : "outline"}
                className="h-8 rounded-full px-3 text-[11px] font-medium"
                onClick={() => conv.setIncludeSharedDocuments((p) => !p)}
              >
                {conv.includeSharedDocuments ? "Extended" : "Focused"}
              </Button>
              {conv.conversationId && (
                <Button
                  type="button"
                  variant={conv.scopeIsDirty ? "default" : "outline"}
                  size="sm"
                  className="h-8 rounded-full px-3 text-[11px] font-medium"
                  disabled={!conv.scopeIsDirty}
                  onClick={() => { void conv.persistConversationScope(); }}
                >
                  Save scope
                </Button>
              )}
            </div>

            <div className="flex items-center gap-1.5">
              <Button variant="outline" size="sm" className="h-8 rounded-full gap-1.5 px-3 text-xs font-medium" onClick={newChat} aria-label="Start a new thread">
                {messages.length > 0 ? <RotateCcw className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />} New Thread
              </Button>
              <div className="relative" data-profile-menu>
                <Button variant="ghost" size="sm" className="gap-2 h-8 rounded-full border border-border/70 bg-background/40 hover:bg-background/70" onClick={() => setShowProfileMenu(!showProfileMenu)}>
                  <Avatar className="h-6 w-6 border border-primary/30">
                    <AvatarFallback className="bg-primary/20 text-primary text-xs font-bold">
                      {user ? getInitials(user.fullName) : "?"}
                    </AvatarFallback>
                  </Avatar>
                  <span className="text-xs font-medium hidden sm:inline max-w-[100px] truncate">{user?.fullName}</span>
                  <ChevronDown className="h-3 w-3 text-muted-foreground" />
                </Button>
                {showProfileMenu && (
                  <div className="absolute right-0 mt-2 w-52 rounded-lg border border-border/80 bg-card/95 backdrop-blur shadow-lg z-50 overflow-hidden">
                    <div className="px-4 py-3 border-b border-border bg-muted/40">
                      <p className="text-xs font-semibold text-foreground">{user?.fullName}</p>
                      <p className="text-xs text-muted-foreground">{user?.email}</p>
                    </div>
                    <button
                      className="w-full px-4 py-2 text-left text-xs font-medium hover:bg-muted/50 transition-colors flex items-center gap-2 text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                      onClick={() => {
                        setShowProfileDialog(true);
                        setShowProfileMenu(false);
                      }}
                    >
                      👤 View Profile
                    </button>
                    <button
                      className="w-full px-4 py-2 text-left text-xs font-medium hover:bg-destructive/10 transition-colors flex items-center gap-2 text-destructive border-t border-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-destructive/60"
                      onClick={handleLogout}
                    >
                      <LogOut className="h-3 w-3" /> Sign Out
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Mobile search panel */}
          {canViewFeedbackMetrics && (
            <div className="border-b border-border px-4 md:px-6 py-3 bg-card/10">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-xs font-semibold text-foreground">Answer Quality Metrics</p>
                  <p className="text-[11px] text-muted-foreground">Admin/reviewer visibility for Candidate 2 feedback loop.</p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant={showFeedbackMetrics ? "default" : "outline"}
                  className="h-8 rounded-full px-3 text-xs"
                  onClick={() => setShowFeedbackMetrics((prev) => !prev)}
                >
                  {showFeedbackMetrics ? "Hide metrics" : "Show metrics"}
                </Button>
              </div>

              {showFeedbackMetrics && (
                <div className="mt-3 rounded-lg border border-border bg-card/60 p-3 space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="text-[11px] text-muted-foreground flex items-center gap-1">
                      Window
                      <select
                        value={feedbackMetricsWindowDays}
                        onChange={(event) => setFeedbackMetricsWindowDays(Number(event.target.value) as 7 | 30 | 90)}
                        className="rounded border border-border bg-background px-2 py-1 text-xs text-foreground"
                      >
                        <option value={7}>7 days</option>
                        <option value={30}>30 days</option>
                        <option value={90}>90 days</option>
                      </select>
                    </label>

                    <label className="text-[11px] text-muted-foreground flex items-center gap-1">
                      Scope
                      <select
                        value={feedbackMetricsScopeMode}
                        onChange={(event) => setFeedbackMetricsScopeMode(event.target.value as "all" | "current")}
                        className="rounded border border-border bg-background px-2 py-1 text-xs text-foreground"
                      >
                        <option value="all">All areas</option>
                        <option value="current">Current area ({conv.selectedWorkspace})</option>
                      </select>
                    </label>
                  </div>

                  {isFeedbackMetricsLoading && (
                    <p className="text-xs text-muted-foreground">Loading feedback metrics...</p>
                  )}

                  {feedbackMetricsError && (
                    <p className="text-xs text-red-300">{feedbackMetricsError}</p>
                  )}

                  {!isFeedbackMetricsLoading && !feedbackMetricsError && feedbackMetrics && (
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                      <div className="rounded border border-border bg-background/70 px-2 py-1.5">
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Total</p>
                        <p className="text-sm font-semibold">{feedbackMetrics.total_feedback_events}</p>
                      </div>
                      <div className="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1.5">
                        <p className="text-[10px] text-emerald-200 uppercase tracking-wide">Positive</p>
                        <p className="text-sm font-semibold text-emerald-100">{feedbackMetrics.positive_feedback_events}</p>
                      </div>
                      <div className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1.5">
                        <p className="text-[10px] text-amber-200 uppercase tracking-wide">Negative</p>
                        <p className="text-sm font-semibold text-amber-100">{feedbackMetrics.negative_feedback_events}</p>
                      </div>
                      <div className="rounded border border-red-500/30 bg-red-500/10 px-2 py-1.5">
                        <p className="text-[10px] text-red-200 uppercase tracking-wide">Flagged</p>
                        <p className="text-sm font-semibold text-red-100">{feedbackMetrics.flagged_answers}</p>
                      </div>
                      <div className="rounded border border-border bg-background/70 px-2 py-1.5">
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Window</p>
                        <p className="text-sm font-semibold">{feedbackMetrics.window_days}d</p>
                      </div>
                    </div>
                  )}

                  {!isFeedbackMetricsLoading && !feedbackMetricsError && feedbackMetrics && feedbackMetrics.reason_breakdown.length > 0 && (
                    <div className="space-y-1">
                      <p className="text-[11px] text-muted-foreground">Reason breakdown</p>
                      <div className="flex flex-wrap gap-1.5">
                        {feedbackMetrics.reason_breakdown.slice(0, 8).map((metric) => (
                          <Badge key={metric.reason_code} variant="outline" className="text-[10px]">
                            {metric.reason_code}: {metric.count}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="border-b border-border px-4 md:px-6 py-3 bg-card/10 lg:hidden">
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <input
                  value={conv.conversationSearch}
                  onChange={(e) => conv.setConversationSearch(e.target.value)}
                  placeholder="Search conversations"
                  aria-label="Search conversations"
                  className="w-full rounded border border-border/80 bg-background px-2.5 py-1.5 text-xs"
                />
                <Button variant="outline" size="sm" className="h-9" onClick={newChat} aria-label="Start a new thread">New</Button>
              </div>
              <div className="flex items-center gap-2">
                <Select value={conv.conversationWorkspaceFilter} onValueChange={conv.setConversationWorkspaceFilter}>
                  <SelectTrigger className="h-9 w-40"><SelectValue placeholder="Workspace" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DEFAULT_CONVERSATION_WORKSPACE_FILTER}>All workspaces</SelectItem>
                    {WORKSPACE_OPTIONS.map((ws) => <SelectItem key={ws} value={ws}>{ws}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Button type="button" variant={conv.showPinnedOnly ? "default" : "outline"} size="sm" className="h-9 px-2"
                  onClick={() => conv.setShowPinnedOnly((p) => !p)} aria-label="Toggle pinned conversations">
                  <Pin className="h-3.5 w-3.5" />
                </Button>
                {conv.activeConversationSummary && (
                  <Button type="button" variant="outline" size="sm" className="h-9 px-2"
                    onClick={() => { void conv.handleToggleConversationPin(conv.activeConversationSummary!); }}
                    aria-label={conv.activeConversationSummary.isPinned ? "Unpin active conversation" : "Pin active conversation"}>
                    {conv.activeConversationSummary.isPinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
                  </Button>
                )}
                <Button type="button" variant="ghost" size="sm" className="h-9 px-2"
                  disabled={!conv.hasActiveConversationDiscoveryFilters} onClick={conv.resetConversationDiscoveryFilters}
                  aria-label="Reset conversation discovery filters">
                  Reset
                </Button>
              </div>
              <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                <Badge variant="outline" className="h-5 px-1.5 text-[10px] border-primary/30 text-primary">
                  <Pin className="h-3 w-3 mr-1" /> {conv.pinnedConversationCount} pinned
                </Badge>
                {conv.showPinnedOnly && <Badge variant="outline" className="h-5 px-1.5 text-[10px]">Pinned only</Badge>}
                {conv.conversationWorkspaceFilter !== DEFAULT_CONVERSATION_WORKSPACE_FILTER && (
                  <Badge variant="outline" className="h-5 px-1.5 text-[10px]">{conv.conversationWorkspaceFilter}</Badge>
                )}
                {Boolean(conv.conversationSearch.trim()) && (
                  <Badge variant="outline" className="h-5 px-1.5 text-[10px]">Search: {conv.conversationSearch.trim()}</Badge>
                )}
              </div>

              <div className="pt-1 border-t border-border/60 mt-1 space-y-2 xl:hidden">
                <p className="text-[11px] text-muted-foreground">Conversation scope</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <Select value={conv.selectedWorkspace} onValueChange={conv.setSelectedWorkspace}>
                    <SelectTrigger className="h-9 text-xs rounded-full bg-background/80 border-border/80">
                      <SelectValue placeholder="Workspace scope" />
                    </SelectTrigger>
                    <SelectContent>
                      {WORKSPACE_OPTIONS.map((ws) => <SelectItem key={ws} value={ws}>{ws}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant={conv.includeSharedDocuments ? "default" : "outline"}
                    className="h-8 rounded-full px-3 text-xs"
                    onClick={() => conv.setIncludeSharedDocuments((p) => !p)}
                  >
                    {conv.includeSharedDocuments ? "Extended" : "Focused"}
                  </Button>
                  {conv.conversationId && (
                    <Button
                      type="button"
                      variant={conv.scopeIsDirty ? "default" : "outline"}
                      size="sm"
                      className="h-8 rounded-full px-3 text-xs"
                      disabled={!conv.scopeIsDirty}
                      onClick={() => { void conv.persistConversationScope(); }}
                    >
                      Save scope
                    </Button>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 mt-2">
              <Select value={conv.conversationId || "new"} onValueChange={(value) => {
                if (value === "new") { newChat(); return; }
                const target = conv.conversations.find((c) => c.id === value);
                if (target) void conv.handleSelectConversation(target);
              }}>
                <SelectTrigger className="h-9 flex-1"><SelectValue placeholder="Select conversation" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="new">New Conversation</SelectItem>
                  {conv.filteredConversations.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.isPinned ? "📌 " : ""}{getConversationDisplayTitle(c)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Messages */}
          <MessageList
            messages={messages}
            isStreaming={isStreaming}
            expandedCites={expandedCites}
            savedIds={savedIds}
            bottomRef={bottomRef}
            onToggleCites={toggleCites}
            onSetActiveCite={setActiveCite}
            onToggleSave={(msgId) => { void toggleSave(msgId); }}
            onSubmitAssistantFeedback={submitAssistantFeedback}
          />

          {/* Cold-start notice */}
          {showColdStartNotice && (
            <div className="border-t border-amber-400/20 bg-amber-400/5 px-6 py-2 text-xs text-amber-400 flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
              Starting LLM &mdash; this may take up to 45 seconds on first request
            </div>
          )}

          {/* Input */}
          <div className="border-t border-border p-4 md:p-5 bg-card/40">
            <form onSubmit={handleSubmit} className="max-w-3xl mx-auto">
              {scopeDeniedState && isScopeRetryBlocked && (
                <div className="mb-3 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                  <p className="font-semibold">Scope restricted by server policy{scopeDeniedState.reasonCode ? ` (${scopeDeniedState.reasonCode})` : ""}</p>
                  <p className="mt-1">{scopeDeniedState.message}</p>
                  <p className="mt-1 text-red-300">Adjust workspace/scope selection before retrying this question.</p>
                </div>
              )}
              <span className="sr-only" aria-live="polite">
                {isStreaming ? "Assistant is generating a response." : "Assistant is ready for your next question."}
              </span>
              <div className="flex gap-2 items-end">
                <Textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Ask about equipment, procedures, or safety..."
                  aria-label="Chat message input"
                  className="min-h-[56px] max-h-[220px] resize-none bg-card border-border/80 rounded-xl leading-relaxed"
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(); } }}
                />
                <Button
                  type="submit"
                  size="icon"
                  disabled={!query.trim() || isStreaming || isScopeRetryBlocked}
                  className="shrink-0 h-12 w-12"
                  aria-label={isStreaming ? "Generating response" : "Send message"}
                >
                  {isStreaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </Button>
              </div>
              <p className="text-[11px] text-muted-foreground mt-2 text-center">
                Responses generated from approved facility documents only &middot; Press Enter to send &middot; Ctrl/Cmd+B toggles sidebar &middot; Ctrl/Cmd+Shift+N starts a new thread
              </p>
            </form>
          </div>
        </div>
      </div>

      {/* Source drawer overlay */}
      {activeCite && <SourceDrawer cite={activeCite} onClose={() => setActiveCite(null)} />}
      {user && (
        <ProfileDialog
          user={user}
          open={showProfileDialog}
          onOpenChange={setShowProfileDialog}
        />
      )}
    </AppLayout>
  );
}
