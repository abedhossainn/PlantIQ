"use client";

/**
 * RAG Chat Interface - Main User Interaction Layer
 * 
 * Architecture:
 * - Displays conversations with message history and real-time streaming
 * - Manages conversation selection, creation, renaming, pinning, deletion
 * - Handles document scope filtering (workspace, document type) for RAG queries
 * - Implements citation/source reference system with expandable drawer
 * - Bidirectional conversation sync with PostgREST backend
 * 
 * Data Flow (Query → Generation):
 * 1. User submits query with workspace/doc-type filters
 * 2. streamChatQuery() opens SSE connection to FastAPI
 * 3. Backend loads embeddings, searches similar documents, invokes LLM
 * 4. Tokens streamed back via SSE as MessageSSEEvent
 * 5. Citations emitted separately as CitationSSEEvent
 * 6. UI accumulates tokens into message, renders citations as badges
 * 7. Message + citations saved to PostgREST via conversation CRUD
 * 
 * Conversation Lifecycle:
 * - Create: Auto-create on first message, or via UI button
 * - Read: Load list from PostgREST, fetch single by ID
 * - Update: Modify title, scope filters, pin status
 * - Delete: Remove from PostgREST (soft or hard delete per backend)
 * 
 * Citation System:
 * - Citations emitted during token streaming
 * - Each citation: document_id, source, page_number, chunk_text
 * - Rendered as click-able badges in message
 * - Click opens SourceDrawer with full source preview + nav link
 * 
 * UI State Management:
 * - activeConversationId: Current conversation being viewed/edited
 * - conversations: List of all conversations (sorted by pin status + lastMessage)
 * - messages: Array of ChatMessage objects (role, content, citations)
 * - streamedMessage: Accumulates tokens during SSE streaming
 * - isStreaming: Indicates active generation (disables send button)
 * 
 * Optimizations:
 * - Discovery filters reduce API payload (search + workspace filter)
 * - Message rendering uses react-markdown with syntax highlighting
 * - Citation drawer lazy-renders source content (prevents excessive DOM)
 * 
 * Error Handling:
 * - Network errors logged to console, shown in toast
 * - SSE timeouts trigger polling fallback (if enabled)
 * - Conversation load failures show empty state
 */

import { useState, useRef, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Send, Bookmark, FileText, MessageSquare, RotateCcw, X, BookmarkCheck, ExternalLink, Trash2, Clock3, Pencil, Check, Pin, PinOff, LogOut, ChevronDown } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useRouter } from "next/navigation";
import {
  getActiveConversation,
  getConversationById,
  getConversations,
  updateConversationPin,
  updateConversationTitle,
  updateConversationScope,
  createBookmark,
  deleteBookmark,
  deleteConversation as removeConversation,
  isMessageBookmarked,
} from "@/lib/api";
import { streamChatQuery, getLlmStatus } from "@/lib/api/chat";
import type { Citation as ApiCitation, LlmStatus } from "@/lib/api/chat";
import type { ChatMessage, Citation, Conversation } from "@/types";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// ---------------------------------------------------------------------------
// Chat Page State Model (Developer Reference)
// ---------------------------------------------------------------------------
// Core identity state
// - conversationId: active thread identifier.
// - conversations: sidebar list model used for discovery and selection.
// - messages: canonical timeline rendered in the main panel.
//
// Query + scope state
// - query: raw text input from the compose box.
// - selectedWorkspace: workspace scope forwarded to backend retrieval.
// - selectedDocumentType: optional document-type narrowing.
// - includeSharedDocuments: controls whether shared corpus participates in retrieval.
//
// Streaming state
// - isStreaming: locks send controls and indicates active generation.
// - llmStatus: backend warm/cold state for UX messaging.
// - showColdStartNotice: informs operators when first token latency may be elevated.
//
// Conversation management state
// - editingConversationId/title: optimistic rename controls.
// - savedIds: bookmark cache for assistant messages.
// - expandedCites: UI expansion model for per-message citation lists.
//
// Discovery preferences state
// - conversationSearch: local keyword filtering for title/preview scans.
// - conversationWorkspaceFilter: sidebar workspace partitioning.
// - showPinnedOnly: focused work mode for priority threads.
// - persisted by user ID to restore analyst context across sessions.
//
// Rendering strategy
// - Markdown rendering is restricted to assistant content for readability.
// - SourceDrawer is isolated to prevent citation detail bloat in the main timeline.
// - bottomRef anchors automatic scroll behavior during streaming.
//
// Operational constraints
// - Keep chat interactions responsive under long outputs.
// - Avoid duplicate writes by deferring persistence to controlled handlers.
// - Preserve deterministic ordering of conversation updates.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Chat Event Handling Playbook
// ---------------------------------------------------------------------------
// Conversation index loading:
// - Load summaries first for fast sidebar paint.
// - Load full conversation details lazily after selection.
// - If selected conversation is missing, clear active selection safely.
//
// Conversation discovery behavior:
// - Search filters should be non-destructive (view-level only).
// - Pinned filter should narrow results but not mutate source list.
// - Workspace filter should combine with search and pin constraints.
//
// Streaming query behavior:
// - Add user message immediately for responsive UX.
// - Start assistant placeholder state before first token arrives.
// - Accumulate tokens into a single assistant message.
// - Append citations as they arrive without blocking token flow.
// - Finalize message on terminal event (`complete` or `error`).
//
// Bookmark synchronization:
// - Bookmark state is derived from backend, cached in `savedIds`.
// - Toggle actions should update UI optimistically where safe.
// - On failure, restore previous bookmark state and notify user.
//
// Renaming/pinning strategy:
// - Sidebar metadata updates should preserve current message timeline.
// - Keep active conversation selected across metadata updates.
// - Reflect backend response order after update for consistency.
//
// Scroll management:
// - Auto-scroll to bottom when receiving stream tokens.
// - Do not force-scroll when user is reviewing older messages (future enhancement).
// - Keep bottomRef logic isolated to reduce accidental regressions.
//
// Error policy:
// - User-facing failures should be concise and actionable.
// - Developer diagnostics should remain in console for triage.
// - Hard failures should never leave isStreaming=true.
//
// UX guardrails:
// - Disable send while streaming to avoid interleaved generations.
// - Preserve query draft when recoverable errors occur.
// - Keep source drawer independent from compose state.
//
// Accessibility considerations:
// - Ensure button labels remain descriptive for screen readers.
// - Keyboard focus should remain stable during streaming updates.
// - Color badges should not be the only channel for status communication.
// ---------------------------------------------------------------------------

interface ChatDiscoveryPreferences {
  conversationSearch: string;
  conversationWorkspaceFilter: string;
  showPinnedOnly: boolean;
}

const DEFAULT_CONVERSATION_WORKSPACE_FILTER = "all";

const WORKSPACE_OPTIONS = [
  "Power Block",
  "Pre Treatment",
  "Liquefaction",
  "OSBL (Outside Battery Limits)",
  "Maintenance",
  "Instrumentation",
  "DCS (Distributed Control System)",
  "Electrical",
  "Mechanical",
];

const CHAT_DOCUMENT_TYPE_OPTIONS = [
  "Operating Manual",
  "Maintenance Manual",
  "Troubleshooting Guide",
  "Technical Manual",
  "Technical Standard",
  "P&ID Diagram",
  "Procedure",
  "Other",
];

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
  const { user, isAdmin, logout } = useAuth();
  const router = useRouter();
  const hasHydratedDiscoveryPreferences = useRef(false);
  
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [editingConversationId, setEditingConversationId] = useState<string | null>(null);
  const [editingConversationTitle, setEditingConversationTitle] = useState<string>("");
  const [conversationSearch, setConversationSearch] = useState<string>("");
  const [conversationWorkspaceFilter, setConversationWorkspaceFilter] = useState<string>(DEFAULT_CONVERSATION_WORKSPACE_FILTER);
  const [showPinnedOnly, setShowPinnedOnly] = useState<boolean>(false);
  const [query, setQuery] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeCite, setActiveCite] = useState<Citation | null>(null);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
    const [expandedCites, setExpandedCites] = useState<Set<string>>(new Set());

    const toggleCites = (msgId: string) =>
      setExpandedCites((prev) => {
        const next = new Set(prev);
        next.has(msgId) ? next.delete(msgId) : next.add(msgId);
        return next;
      });
  const [isLoading, setIsLoading] = useState(true);
  const [llmStatus, setLlmStatus] = useState<LlmStatus | null>(null);
  const [showColdStartNotice, setShowColdStartNotice] = useState(false);
  const [selectedWorkspace, setSelectedWorkspace] = useState<string>("Liquefaction");
  const [selectedDocumentType, setSelectedDocumentType] = useState<string>("all");
  const [includeSharedDocuments, setIncludeSharedDocuments] = useState<boolean>(true);
  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const activeConversationSummary = conversations.find((conversation) => conversation.id === conversationId);

  function getChatDiscoveryPreferencesKey(userId: string): string {
    return `chat_discovery_preferences:${userId}`;
  }

  function getInitials(name: string): string {
    return name
      .split(" ")
      .map((n) => n[0])
      .join("")
      .toUpperCase();
  }

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

  async function resolveSavedMessageIds(nextMessages: ChatMessage[]) {
    const bookmarked = new Set<string>();
    for (const msg of nextMessages) {
      if (msg.role === 'assistant' && await isMessageBookmarked(msg.id)) {
        bookmarked.add(msg.id);
      }
    }
    setSavedIds(bookmarked);
  }

  async function loadConversationIndex(preferredConversationId?: string | null) {
    const list = await getConversations({ limit: 50 });
    setConversations(list);

    const targetId = preferredConversationId || conversationId;
    if (!list.length || !targetId) {
      return list;
    }

    const exists = list.some((conversation) => conversation.id === targetId);
    if (!exists) {
      setConversationId(null);
      setMessages([]);
    }

    return list;
  }

  async function loadConversation(conversation: Conversation) {
    const fullConversation = await getConversationById(conversation.id);
    setConversationId(fullConversation.id);
    applyConversationScope(fullConversation);
    setMessages(fullConversation.messages);
    await resolveSavedMessageIds(fullConversation.messages);
  }

  function formatConversationTimestamp(value?: string | null): string {
    if (!value) return "No messages yet";

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "Recently updated";
    }

    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  }

  function getConversationDisplayTitle(conversation: Conversation): string {
    const title = conversation.title?.trim();
    if (title && title !== "New Conversation") {
      return title;
    }

    const preview = conversation.lastMessagePreview?.trim();
    if (preview) {
      return preview.length > 64 ? `${preview.slice(0, 61).trimEnd()}...` : preview;
    }

    return "New Conversation";
  }

  function startConversationTitleEdit(conversation: Conversation) {
    setEditingConversationId(conversation.id);
    setEditingConversationTitle(getConversationDisplayTitle(conversation));
  }

  function cancelConversationTitleEdit() {
    setEditingConversationId(null);
    setEditingConversationTitle("");
  }

  async function saveConversationTitle(conversationIdToUpdate: string) {
    const nextTitle = editingConversationTitle.trim();
    if (!nextTitle) {
      cancelConversationTitleEdit();
      return;
    }

    try {
      await updateConversationTitle(conversationIdToUpdate, nextTitle);
      await loadConversationIndex(conversationIdToUpdate);
      if (conversationId === conversationIdToUpdate) {
        const refreshedConversation = await getConversationById(conversationIdToUpdate);
        setMessages(refreshedConversation.messages);
      }
    } catch (err) {
      console.error('Failed to update conversation title:', err);
    } finally {
      cancelConversationTitleEdit();
    }
  }

  function applyConversationScope(scope: {
    workspace?: string;
    preferredDocumentTypes?: string[];
    documentTypeFilters?: string[];
    includeSharedDocuments?: boolean;
  }) {
    if (scope.workspace) {
      setSelectedWorkspace(scope.workspace);
    }

    const preferredDocumentType = scope.preferredDocumentTypes?.[0] || scope.documentTypeFilters?.[0];
    setSelectedDocumentType(preferredDocumentType || "all");

    if (typeof scope.includeSharedDocuments === "boolean") {
      setIncludeSharedDocuments(scope.includeSharedDocuments);
    }
  }

  const selectedScopeDocumentTypes = selectedDocumentType !== "all" ? [selectedDocumentType] : undefined;
  const scopeIsDirty = Boolean(
    activeConversationSummary && (
      (activeConversationSummary.workspace || "") !== selectedWorkspace ||
      (activeConversationSummary.includeSharedDocuments ?? true) !== includeSharedDocuments ||
      (activeConversationSummary.preferredDocumentTypes?.[0] || activeConversationSummary.documentTypeFilters?.[0] || "all") !== selectedDocumentType
    )
  );

  async function persistConversationScope() {
    if (!conversationId) {
      return;
    }

    try {
      const updatedConversation = await updateConversationScope(conversationId, {
        workspace: selectedWorkspace,
        documentTypeFilters: selectedScopeDocumentTypes,
        preferredDocumentTypes: selectedScopeDocumentTypes,
        includeSharedDocuments,
      });

      applyConversationScope(updatedConversation);
      await loadConversationIndex(updatedConversation.id);
    } catch (err) {
      console.error('Failed to persist conversation scope:', err);
    }
  }

  async function handleToggleConversationPin(conversation: Conversation) {
    try {
      await updateConversationPin(conversation.id, !conversation.isPinned);
      await loadConversationIndex(conversation.id);
    } catch (err) {
      console.error('Failed to update conversation pin state:', err);
    }
  }

  function resetConversationDiscoveryFilters() {
    setConversationSearch("");
    setConversationWorkspaceFilter(DEFAULT_CONVERSATION_WORKSPACE_FILTER);
    setShowPinnedOnly(false);
  }

  const pinnedConversationCount = conversations.filter((conversation) => conversation.isPinned).length;
  const hasActiveConversationDiscoveryFilters =
    Boolean(conversationSearch.trim()) ||
    conversationWorkspaceFilter !== DEFAULT_CONVERSATION_WORKSPACE_FILTER ||
    showPinnedOnly;

  const filteredConversations = conversations.filter((conversation) => {
    if (showPinnedOnly && !conversation.isPinned) {
      return false;
    }

    const workspaceMatch =
      conversationWorkspaceFilter === "all" || conversation.workspace === conversationWorkspaceFilter;

    const searchTerm = conversationSearch.trim().toLowerCase();
    if (!searchTerm) {
      return workspaceMatch;
    }

    const title = getConversationDisplayTitle(conversation).toLowerCase();
    const preview = (conversation.lastMessagePreview || "").toLowerCase();
    return workspaceMatch && (title.includes(searchTerm) || preview.includes(searchTerm));
  }).sort((a, b) => {
    const pinPriority = Number(Boolean(b.isPinned)) - Number(Boolean(a.isPinned));
    if (pinPriority !== 0) {
      return pinPriority;
    }

    const aTime = new Date(a.updatedAt).getTime();
    const bTime = new Date(b.updatedAt).getTime();
    return bTime - aTime;
  });

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
      if (!target.closest("[data-profile-menu]")) {
        setShowProfileMenu(false);
      }
    }
    if (showProfileMenu) {
      document.addEventListener("click", handleClickOutside);
      return () => document.removeEventListener("click", handleClickOutside);
    }
  }, [showProfileMenu]);

  // Hydrate persisted discovery preferences per authenticated user.
  useEffect(() => {
    hasHydratedDiscoveryPreferences.current = false;

    if (!user || typeof globalThis === "undefined" || !("localStorage" in globalThis)) {
      return;
    }

    const storageKey = getChatDiscoveryPreferencesKey(user.id);
    const rawPreferences = globalThis.localStorage.getItem(storageKey);

    if (rawPreferences) {
      try {
        const parsed = JSON.parse(rawPreferences) as Partial<ChatDiscoveryPreferences>;

        if (typeof parsed.conversationSearch === "string") {
          setConversationSearch(parsed.conversationSearch);
        }

        if (
          typeof parsed.conversationWorkspaceFilter === "string" &&
          (parsed.conversationWorkspaceFilter === "all" || WORKSPACE_OPTIONS.includes(parsed.conversationWorkspaceFilter))
        ) {
          setConversationWorkspaceFilter(parsed.conversationWorkspaceFilter);
        }

        if (typeof parsed.showPinnedOnly === "boolean") {
          setShowPinnedOnly(parsed.showPinnedOnly);
        }
      } catch (err) {
        console.error("Failed to parse chat discovery preferences:", err);
      }
    }

    hasHydratedDiscoveryPreferences.current = true;
  }, [user]);

  // Persist discovery preferences whenever controls change.
  useEffect(() => {
    if (
      !user ||
      !hasHydratedDiscoveryPreferences.current ||
      typeof globalThis === "undefined" ||
      !("localStorage" in globalThis)
    ) {
      return;
    }

    const storageKey = getChatDiscoveryPreferencesKey(user.id);
    const preferences: ChatDiscoveryPreferences = {
      conversationSearch,
      conversationWorkspaceFilter,
      showPinnedOnly,
    };

    globalThis.localStorage.setItem(storageKey, JSON.stringify(preferences));
  }, [conversationSearch, conversationWorkspaceFilter, showPinnedOnly, user]);

  // Load active conversation and saved bookmarks on mount
  useEffect(() => {
    async function loadData() {
      if (!user) {
        setIsLoading(false);
        return;
      }
      
      setIsLoading(true);
      try {
        const list = await loadConversationIndex();

        // Try to load active conversation
        const result = await getActiveConversation();
        if (result && list.some((conversation) => conversation.id === result.conversation.id)) {
          await loadConversation(result.conversation);
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
    setSavedIds(new Set());
    setSelectedWorkspace("Liquefaction");
    setSelectedDocumentType("all");
    setIncludeSharedDocuments(true);
  }

  async function handleSelectConversation(conversation: Conversation) {
    setActiveCite(null);
    setQuery("");
    await loadConversation(conversation);
  }

  async function handleDeleteConversation(conversationIdToDelete: string) {
    try {
      await removeConversation(conversationIdToDelete);

      const isActiveConversation = conversationId === conversationIdToDelete;
      const updatedConversations = await loadConversationIndex(
        isActiveConversation ? null : conversationId
      );

      if (isActiveConversation) {
        const nextConversation = updatedConversations.find(
          (conversation) => conversation.id !== conversationIdToDelete
        );

        if (nextConversation) {
          await loadConversation(nextConversation);
        } else {
          newChat();
        }
      }
    } catch (err) {
      console.error('Failed to delete conversation:', err);
    }
  }

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!query.trim() || isStreaming || !user) return;

    // Show cold-start notice if LLM container is not yet reachable
    if (llmStatus !== null && !llmStatus.container_reachable) {
      setShowColdStartNotice(true);
    }

    let currentConvId = conversationId;

    // Add user message to UI
    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}-user`,
      role: "user",
      content: query.trim(),
      timestamp: new Date().toISOString(),
      workspace: selectedWorkspace,
    };
    setMessages((prev) => [...prev, userMsg]);

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
      workspace: selectedWorkspace,
      citations: [],
    };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      let fullContent = "";
      const pendingCitations: Citation[] = [];
      let activeAssistantMessageId = assistantMsgId;
      let resolvedConversationId = currentConvId;
      
      // Stream typed events from RAG endpoint.
      for await (const event of streamChatQuery({
        query: queryText,
        conversation_id: currentConvId || undefined,
        workspace: selectedWorkspace,
        document_type_filters:
          selectedDocumentType !== "all" ? [selectedDocumentType] : undefined,
        preferred_document_types:
          selectedDocumentType !== "all" ? [selectedDocumentType] : undefined,
        include_shared_documents: includeSharedDocuments,
      })) {
        if (event.conversation_id) {
          resolvedConversationId = event.conversation_id;
          setConversationId(event.conversation_id);
        }

        if (event.message_id && event.message_id !== activeAssistantMessageId) {
          const previousAssistantId = activeAssistantMessageId;
          const nextAssistantMessageId = event.message_id;
          activeAssistantMessageId = nextAssistantMessageId;
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === previousAssistantId
                ? { ...msg, id: nextAssistantMessageId }
                : msg
            )
          );
        }

        if (event.type === 'token') {
          // Dismiss cold-start notice on first token
          setShowColdStartNotice(false);
          fullContent += event.content;
          // Update message with accumulated content incrementally.
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === activeAssistantMessageId
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
            workspace: raw.workspace,
            system: raw.system,
            documentType: raw.document_type,
            excerpt: raw.excerpt,
            relevanceScore: raw.relevance_score,
          });
        } else if (event.type === 'complete') {
          // Stream finished — apply collected citations to the message.
          if (pendingCitations.length > 0) {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === activeAssistantMessageId
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
            msg.id === activeAssistantMessageId && (!msg.citations || msg.citations.length === 0)
              ? { ...msg, citations: pendingCitations }
              : msg
          )
        );
      }

      if (resolvedConversationId) {
        try {
          const refreshedConversation = await getConversationById(resolvedConversationId);
          setConversationId(refreshedConversation.id);
          applyConversationScope(refreshedConversation);
          setMessages(refreshedConversation.messages);
          await resolveSavedMessageIds(refreshedConversation.messages);
          await loadConversationIndex(refreshedConversation.id);
        } catch (err) {
          console.error('Failed to refresh conversation after streaming:', err);
        }
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

  // Conversation sidebar content — shared between the AppLayout sidebarContent slot (user role)
  // and the inline aside panel (admin role).
  const conversationSidebarContent = (
    <>
      <div className="px-3 py-3 border-b border-border space-y-2">
        <input
          value={conversationSearch}
          onChange={(event) => setConversationSearch(event.target.value)}
          placeholder="Search conversations"
          className="w-full rounded border border-border bg-background px-2 py-1.5 text-xs"
        />
        <div className="flex items-center gap-2">
          <Select value={conversationWorkspaceFilter} onValueChange={setConversationWorkspaceFilter}>
            <SelectTrigger className="h-8 text-xs flex-1">
              <SelectValue placeholder="All workspaces" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={DEFAULT_CONVERSATION_WORKSPACE_FILTER}>All workspaces</SelectItem>
              {WORKSPACE_OPTIONS.map((workspace) => (
                <SelectItem key={workspace} value={workspace}>{workspace}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            variant={showPinnedOnly ? "default" : "outline"}
            size="sm"
            className="h-8 px-2 text-xs"
            onClick={() => setShowPinnedOnly((prev) => !prev)}
          >
            <Pin className="h-3.5 w-3.5" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 px-2 text-xs"
            disabled={!hasActiveConversationDiscoveryFilters}
            onClick={resetConversationDiscoveryFilters}
          >
            Reset
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
          <Badge variant="outline" className="h-5 px-1.5 text-[10px] border-primary/30 text-primary">
            <Pin className="h-3 w-3 mr-1" /> {pinnedConversationCount} pinned
          </Badge>
          {showPinnedOnly && (
            <Badge variant="outline" className="h-5 px-1.5 text-[10px]">Pinned only</Badge>
          )}
          {conversationWorkspaceFilter !== DEFAULT_CONVERSATION_WORKSPACE_FILTER && (
            <Badge variant="outline" className="h-5 px-1.5 text-[10px]">{conversationWorkspaceFilter}</Badge>
          )}
          {Boolean(conversationSearch.trim()) && (
            <Badge variant="outline" className="h-5 px-1.5 text-[10px]">Search: {conversationSearch.trim()}</Badge>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {filteredConversations.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-4 text-xs text-muted-foreground">
            No conversations match your filter.
          </div>
        ) : (
          filteredConversations.map((conversation) => {
            const isActive = conversation.id === conversationId;
            const isEditing = editingConversationId === conversation.id;
            return (
              <div
                key={conversation.id}
                role="button"
                tabIndex={0}
                onClick={() => handleSelectConversation(conversation)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    void handleSelectConversation(conversation);
                  }
                }}
                className={`w-full rounded-lg border p-3 text-left transition-colors ${
                  isActive
                    ? "border-primary bg-primary/5"
                    : "border-border bg-background hover:border-primary/40 hover:bg-primary/5"
                }`}
              >
                <div className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    {isEditing ? (
                      <input
                        autoFocus
                        value={editingConversationTitle}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) => setEditingConversationTitle(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            void saveConversationTitle(conversation.id);
                          } else if (event.key === "Escape") {
                            event.preventDefault();
                            cancelConversationTitleEdit();
                          }
                        }}
                        className="w-full rounded border border-border bg-background px-2 py-1 text-sm"
                      />
                    ) : (
                      <p className="text-sm font-medium text-foreground line-clamp-2">
                        {getConversationDisplayTitle(conversation)}
                      </p>
                    )}
                    <div className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
                      <Clock3 className="h-3 w-3" />
                      <span>{formatConversationTimestamp(conversation.lastMessageAt || conversation.updatedAt)}</span>
                    </div>
                  </div>
                  {isEditing ? (
                    <button
                      type="button"
                      aria-label="Save conversation title"
                      className="rounded p-1 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                      onClick={(event) => {
                        event.stopPropagation();
                        void saveConversationTitle(conversation.id);
                      }}
                    >
                      <Check className="h-3.5 w-3.5" />
                    </button>
                  ) : (
                    <button
                      type="button"
                      aria-label={conversation.isPinned ? "Unpin conversation" : "Pin conversation"}
                      className={`rounded p-1 hover:bg-primary/10 ${conversation.isPinned ? "text-primary" : "text-muted-foreground hover:text-primary"}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        void handleToggleConversationPin(conversation);
                      }}
                    >
                      {conversation.isPinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
                    </button>
                  )}
                  {!isEditing && (
                    <button
                      type="button"
                      aria-label="Rename conversation"
                      className="rounded p-1 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                      onClick={(event) => {
                        event.stopPropagation();
                        startConversationTitleEdit(conversation);
                      }}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  )}
                  <button
                    type="button"
                    aria-label="Delete conversation"
                    className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    onClick={(event) => {
                      event.stopPropagation();
                      void handleDeleteConversation(conversation.id);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {conversation.isPinned && (
                    <Badge variant="outline" className="h-5 px-1.5 text-[10px] border-primary/40 text-primary">
                      Pinned
                    </Badge>
                  )}
                  {conversation.workspace && (
                    <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                      {conversation.workspace}
                    </Badge>
                  )}
                  {(conversation.preferredDocumentTypes?.[0] || conversation.documentTypeFilters?.[0]) && (
                    <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                      {conversation.preferredDocumentTypes?.[0] || conversation.documentTypeFilters?.[0]}
                    </Badge>
                  )}
                </div>

                {conversation.lastMessagePreview && (
                  <p className="mt-2 text-xs text-muted-foreground line-clamp-2">
                    {conversation.lastMessagePreview}
                  </p>
                )}
              </div>
            );
          })
        )}
      </div>
    </>
  );

  return (
    <AppLayout sidebarContent={!isAdmin ? conversationSidebarContent : undefined}>
      <div className="flex-1 flex h-full min-h-0 overflow-hidden">
        {isAdmin && (
          <aside className="w-80 shrink-0 border-r border-border bg-card/30 hidden lg:flex lg:flex-col">
            {conversationSidebarContent}
          </aside>
        )}

        <div className="flex-1 flex flex-col h-full min-h-0 overflow-hidden">
        {/* Chat header */}
        <div className="border-b border-border px-6 py-3 flex items-center justify-between bg-card/40">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-primary" />
            <span className="font-semibold text-sm">PlantIQ Assistant</span>
            {activeConversationSummary && (
              <Badge variant="outline" className="text-xs border-primary/30 text-primary">
                {getConversationDisplayTitle(activeConversationSummary)}
              </Badge>
            )}
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
          <div className="flex items-center gap-2">
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
            {/* User profile dropdown menu */}
            <div className="relative" data-profile-menu>
              <Button
                variant="ghost"
                size="sm"
                className="gap-2 h-9"
                onClick={() => setShowProfileMenu(!showProfileMenu)}
              >
                <Avatar className="h-6 w-6 border border-primary/30">
                  <AvatarFallback className="bg-primary/20 text-primary text-xs font-bold">
                    {user ? getInitials(user.fullName) : "?"}
                  </AvatarFallback>
                </Avatar>
                <span className="text-xs font-medium hidden sm:inline max-w-[100px] truncate">
                  {user?.fullName}
                </span>
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
                    onClick={() => {
                      router.push("/profile");
                      setShowProfileMenu(false);
                    }}
                  >
                    👤 View Profile
                  </button>
                  <button
                    className="w-full px-4 py-2 text-left text-xs font-medium hover:bg-destructive/10 transition-colors flex items-center gap-2 text-destructive border-t border-border"
                    onClick={handleLogout}
                  >
                    <LogOut className="h-3 w-3" />
                    Sign Out
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="border-b border-border px-6 py-3 bg-card/10 lg:hidden">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <input
                value={conversationSearch}
                onChange={(event) => setConversationSearch(event.target.value)}
                placeholder="Search conversations"
                className="w-full rounded border border-border bg-background px-2 py-1.5 text-xs"
              />
              <Button variant="outline" size="sm" className="h-9" onClick={newChat}>
                New
              </Button>
            </div>
            <div className="flex items-center gap-2">
              <Select value={conversationWorkspaceFilter} onValueChange={setConversationWorkspaceFilter}>
                <SelectTrigger className="h-9 w-40">
                  <SelectValue placeholder="Workspace" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DEFAULT_CONVERSATION_WORKSPACE_FILTER}>All workspaces</SelectItem>
                  {WORKSPACE_OPTIONS.map((workspace) => (
                    <SelectItem key={workspace} value={workspace}>{workspace}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                type="button"
                variant={showPinnedOnly ? "default" : "outline"}
                size="sm"
                className="h-9 px-2"
                onClick={() => setShowPinnedOnly((prev) => !prev)}
                aria-label="Toggle pinned conversations"
              >
                <Pin className="h-3.5 w-3.5" />
              </Button>
              {activeConversationSummary && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-9 px-2"
                  onClick={() => {
                    void handleToggleConversationPin(activeConversationSummary);
                  }}
                  aria-label={activeConversationSummary.isPinned ? "Unpin active conversation" : "Pin active conversation"}
                >
                  {activeConversationSummary.isPinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
                </Button>
              )}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-9 px-2"
                disabled={!hasActiveConversationDiscoveryFilters}
                onClick={resetConversationDiscoveryFilters}
                aria-label="Reset conversation discovery filters"
              >
                Reset
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              <Badge variant="outline" className="h-5 px-1.5 text-[10px] border-primary/30 text-primary">
                <Pin className="h-3 w-3 mr-1" /> {pinnedConversationCount} pinned
              </Badge>
              {showPinnedOnly && (
                <Badge variant="outline" className="h-5 px-1.5 text-[10px]">Pinned only</Badge>
              )}
              {conversationWorkspaceFilter !== DEFAULT_CONVERSATION_WORKSPACE_FILTER && (
                <Badge variant="outline" className="h-5 px-1.5 text-[10px]">{conversationWorkspaceFilter}</Badge>
              )}
              {Boolean(conversationSearch.trim()) && (
                <Badge variant="outline" className="h-5 px-1.5 text-[10px]">Search: {conversationSearch.trim()}</Badge>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 mt-2">
            <Select
              value={conversationId || "new"}
              onValueChange={(value) => {
                if (value === "new") {
                  newChat();
                  return;
                }

                const targetConversation = conversations.find((conversation) => conversation.id === value);
                if (targetConversation) {
                  void handleSelectConversation(targetConversation);
                }
              }}
            >
              <SelectTrigger className="h-9 flex-1">
                <SelectValue placeholder="Select conversation" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="new">New Conversation</SelectItem>
                {filteredConversations.map((conversation) => (
                  <SelectItem key={conversation.id} value={conversation.id}>
                    {conversation.isPinned ? "📌 " : ""}{getConversationDisplayTitle(conversation)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="border-b border-border px-6 py-3 bg-card/20">
          <div className="max-w-3xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-2">
            <div>
              <p className="text-[11px] text-muted-foreground mb-1">Workspace (default scope)</p>
              <Select value={selectedWorkspace} onValueChange={setSelectedWorkspace}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="Select workspace" />
                </SelectTrigger>
                <SelectContent>
                  {WORKSPACE_OPTIONS.map((workspace) => (
                    <SelectItem key={workspace} value={workspace}>{workspace}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <p className="text-[11px] text-muted-foreground mb-1">Document type (subfilter)</p>
              <Select value={selectedDocumentType} onValueChange={setSelectedDocumentType}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="All document types" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All document types</SelectItem>
                  {CHAT_DOCUMENT_TYPE_OPTIONS.map((docType) => (
                    <SelectItem key={docType} value={docType}>{docType}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <p className="text-[11px] text-muted-foreground mb-1">Shared docs</p>
              <Button
                type="button"
                variant={includeSharedDocuments ? "default" : "outline"}
                size="sm"
                className="h-9 w-full"
                onClick={() => setIncludeSharedDocuments((prev) => !prev)}
              >
                {includeSharedDocuments ? "Included" : "Excluded"}
              </Button>
            </div>
          </div>
          <div className="max-w-3xl mx-auto mt-2 flex items-center gap-2 text-[11px] text-muted-foreground">
            <span className="font-medium">Conversation scope:</span>
            <Badge variant="outline" className="text-[11px] px-2 py-0 h-5">
              {selectedWorkspace}
            </Badge>
            {selectedDocumentType !== "all" && (
              <Badge variant="outline" className="text-[11px] px-2 py-0 h-5">
                {selectedDocumentType}
              </Badge>
            )}
            {conversationId && (
              <Button
                type="button"
                variant={scopeIsDirty ? "default" : "outline"}
                size="sm"
                className="h-6 text-[11px] px-2 py-0"
                disabled={!scopeIsDirty}
                onClick={() => {
                  void persistConversationScope();
                }}
              >
                Save scope
              </Button>
            )}
          </div>
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
                      <div className="w-full">
                        <button
                          onClick={() => toggleCites(message.id)}
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
                                onClick={() => setActiveCite(cite)}
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
      </div>

      {/* Source drawer overlay (US-2.3) */}
      {activeCite && <SourceDrawer cite={activeCite} onClose={() => setActiveCite(null)} />}
    </AppLayout>
  );
}
