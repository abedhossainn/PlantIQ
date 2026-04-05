"use client";

import { useState, useRef, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Send, FileText, MessageSquare, RotateCcw, Pin, PinOff, LogOut, ChevronDown } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useRouter } from "next/navigation";
import {
  createBookmark,
  deleteBookmark,
  getConversationById,
} from "@/lib/api";
import { streamChatQuery, getLlmStatus } from "@/lib/api/chat";
import type { Citation as ApiCitation, LlmStatus } from "@/lib/api/chat";
import type { ChatMessage, Citation, Conversation } from "@/types";
import { DEFAULT_CONVERSATION_WORKSPACE_FILTER, WORKSPACE_OPTIONS, CHAT_DOCUMENT_TYPE_OPTIONS } from "./_constants";
import { getInitials, getConversationDisplayTitle } from "./_helpers";
import { SourceDrawer } from "./_components/SourceDrawer";
import { ConversationSidebar } from "./_components/ConversationSidebar";
import { MessageList } from "./_components/MessageList";
import { useConversations } from "./_hooks/useConversations";

const CHAT_SUGGESTIONS = [
  "What is the density of LNG at atmospheric pressure?",
  "How do I start up the cryogenic pump?",
  "What actions should I take if there is an LNG spill?",
  "What are the calibration requirements for pressure transmitters?",
];

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

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function newChat() {
    clearChat();
    conv.setConversationId(null);
    conv.setSelectedWorkspace("Liquefaction");
    conv.setSelectedDocumentType("all");
    conv.setIncludeSharedDocuments(true);
  }

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
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
        document_type_filters: conv.selectedDocumentType !== "all" ? [conv.selectedDocumentType] : undefined,
        preferred_document_types: conv.selectedDocumentType !== "all" ? [conv.selectedDocumentType] : undefined,
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
  };

  return (
    <AppLayout sidebarContent={!isAdmin ? <ConversationSidebar {...sidebarProps} /> : undefined}>
      <div className="flex-1 flex h-full min-h-0 overflow-hidden">
        {isAdmin && (
          <aside className="w-80 shrink-0 border-r border-border bg-card/30 hidden lg:flex lg:flex-col">
            <ConversationSidebar {...sidebarProps} />
          </aside>
        )}

        <div className="flex-1 flex flex-col h-full min-h-0 overflow-hidden">
          {/* Chat header */}
          <div className="border-b border-border px-6 py-3 flex items-center justify-between bg-card/40">
            <div className="flex items-center gap-2">
              <MessageSquare className="h-5 w-5 text-primary" />
              <span className="font-semibold text-sm">PlantIQ Assistant</span>
              {conv.activeConversationSummary && (
                <Badge variant="outline" className="text-xs border-primary/30 text-primary">
                  {getConversationDisplayTitle(conv.activeConversationSummary)}
                </Badge>
              )}
              <Badge variant="outline" className={`text-xs ${llmStatus === null ? "text-muted-foreground border-muted-foreground/30" : !llmStatus.container_reachable ? "text-amber-400 border-amber-400/30 bg-amber-400/10 animate-pulse" : llmStatus.active_requests > 0 ? "text-amber-400 border-amber-400/30 bg-amber-400/10" : "text-green-400 border-green-400/30 bg-green-400/10"}`}>
                {llmStatus === null ? "LLM Offline" : !llmStatus.container_reachable ? "LLM Starting..." : llmStatus.active_requests > 0 ? "Generating..." : "LLM Ready"}
              </Badge>
            </div>
            <div className="flex items-center gap-2">
              {messages.length > 0 && (
                <Button variant="outline" size="sm" className="gap-1.5 text-xs" onClick={newChat}>
                  <RotateCcw className="h-3.5 w-3.5" /> New Chat
                </Button>
              )}
              <div className="relative" data-profile-menu>
                <Button variant="ghost" size="sm" className="gap-2 h-9" onClick={() => setShowProfileMenu(!showProfileMenu)}>
                  <Avatar className="h-6 w-6 border border-primary/30">
                    <AvatarFallback className="bg-primary/20 text-primary text-xs font-bold">
                      {user ? getInitials(user.fullName) : "?"}
                    </AvatarFallback>
                  </Avatar>
                  <span className="text-xs font-medium hidden sm:inline max-w-[100px] truncate">{user?.fullName}</span>
                  <ChevronDown className="h-3 w-3 text-muted-foreground" />
                </Button>
                {showProfileMenu && (
                  <div className="absolute right-0 mt-2 w-48 rounded-lg border border-border bg-card shadow-lg z-50 overflow-hidden">
                    <div className="px-4 py-3 border-b border-border bg-muted/40">
                      <p className="text-xs font-semibold text-foreground">{user?.fullName}</p>
                      <p className="text-xs text-muted-foreground">{user?.email}</p>
                    </div>
                    <button
                      className="w-full px-4 py-2 text-left text-xs font-medium hover:bg-muted/50 transition-colors flex items-center gap-2 text-foreground"
                      onClick={() => { router.push("/profile"); setShowProfileMenu(false); }}
                    >
                      👤 View Profile
                    </button>
                    <button
                      className="w-full px-4 py-2 text-left text-xs font-medium hover:bg-destructive/10 transition-colors flex items-center gap-2 text-destructive border-t border-border"
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
          <div className="border-b border-border px-6 py-3 bg-card/10 lg:hidden">
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <input
                  value={conv.conversationSearch}
                  onChange={(e) => conv.setConversationSearch(e.target.value)}
                  placeholder="Search conversations"
                  className="w-full rounded border border-border bg-background px-2 py-1.5 text-xs"
                />
                <Button variant="outline" size="sm" className="h-9" onClick={newChat}>New</Button>
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

          {/* Scope settings */}
          <div className="border-b border-border px-6 py-3 bg-card/20">
            <div className="max-w-3xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-2">
              <div>
                <p className="text-[11px] text-muted-foreground mb-1">Workspace (default scope)</p>
                <Select value={conv.selectedWorkspace} onValueChange={conv.setSelectedWorkspace}>
                  <SelectTrigger className="h-9"><SelectValue placeholder="Select workspace" /></SelectTrigger>
                  <SelectContent>
                    {WORKSPACE_OPTIONS.map((ws) => <SelectItem key={ws} value={ws}>{ws}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground mb-1">Document type (subfilter)</p>
                <Select value={conv.selectedDocumentType} onValueChange={conv.setSelectedDocumentType}>
                  <SelectTrigger className="h-9"><SelectValue placeholder="All document types" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All document types</SelectItem>
                    {CHAT_DOCUMENT_TYPE_OPTIONS.map((dt) => <SelectItem key={dt} value={dt}>{dt}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground mb-1">Shared docs</p>
                <Button type="button" variant={conv.includeSharedDocuments ? "default" : "outline"} size="sm" className="h-9 w-full"
                  onClick={() => conv.setIncludeSharedDocuments((p) => !p)}>
                  {conv.includeSharedDocuments ? "Included" : "Excluded"}
                </Button>
              </div>
            </div>
            <div className="max-w-3xl mx-auto mt-2 flex items-center gap-2 text-[11px] text-muted-foreground">
              <span className="font-medium">Conversation scope:</span>
              <Badge variant="outline" className="text-[11px] px-2 py-0 h-5">{conv.selectedWorkspace}</Badge>
              {conv.selectedDocumentType !== "all" && (
                <Badge variant="outline" className="text-[11px] px-2 py-0 h-5">{conv.selectedDocumentType}</Badge>
              )}
              {conv.conversationId && (
                <Button type="button" variant={conv.scopeIsDirty ? "default" : "outline"} size="sm"
                  className="h-6 text-[11px] px-2 py-0" disabled={!conv.scopeIsDirty}
                  onClick={() => { void conv.persistConversationScope(); }}>
                  Save scope
                </Button>
              )}
            </div>
          </div>

          {/* Messages */}
          <MessageList
            messages={messages}
            isStreaming={isStreaming}
            expandedCites={expandedCites}
            savedIds={savedIds}
            suggestions={CHAT_SUGGESTIONS}
            bottomRef={bottomRef}
            onToggleCites={toggleCites}
            onSetActiveCite={setActiveCite}
            onToggleSave={(msgId) => { void toggleSave(msgId); }}
            onSelectSuggestion={setQuery}
          />

          {/* Cold-start notice */}
          {showColdStartNotice && (
            <div className="border-t border-amber-400/20 bg-amber-400/5 px-6 py-2 text-xs text-amber-400 flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
              Starting LLM &mdash; this may take up to 45 seconds on first request
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
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(); } }}
                />
                <Button type="submit" size="icon" disabled={!query.trim() || isStreaming} className="shrink-0 h-12 w-12">
                  <Send className="h-4 w-4" />
                </Button>
              </div>
              <p className="text-xs text-muted-foreground mt-2 text-center">
                Responses generated from approved facility documents only &middot; Press Enter to send
              </p>
            </form>
          </div>
        </div>
      </div>

      {/* Source drawer overlay */}
      {activeCite && <SourceDrawer cite={activeCite} onClose={() => setActiveCite(null)} />}
    </AppLayout>
  );
}
