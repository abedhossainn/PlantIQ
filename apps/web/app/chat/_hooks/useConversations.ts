"use client";

import { useState, useRef, useEffect } from "react";
import {
  getActiveConversation,
  getConversationById,
  getConversations,
  updateConversationPin,
  updateConversationTitle,
  updateConversationScope,
  deleteConversation as removeConversation,
  isMessageBookmarked,
} from "@/lib/api";
import { getAuthToken } from "@/lib/api/client";
import type { ChatMessage, Conversation } from "@/types";
import {
  DEFAULT_CONVERSATION_WORKSPACE_FILTER,
  WORKSPACE_OPTIONS,
  getChatDiscoveryPreferencesKey,
  type ChatDiscoveryPreferences,
} from "../_constants";
import { getConversationDisplayTitle } from "../_helpers";

interface UseConversationsOptions {
  user: { id: string } | null;
  isAuthLoading?: boolean;
  onClearChat: () => void;
  onSetMessages: (messages: ChatMessage[]) => void;
  onSetSavedIds: (ids: Set<string>) => void;
}

export function useConversations({
  user,
  isAuthLoading = false,
  onClearChat,
  onSetMessages,
  onSetSavedIds,
}: UseConversationsOptions) {
  const hasHydratedDiscoveryPreferences = useRef(false);

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [editingConversationId, setEditingConversationId] = useState<string | null>(null);
  const [editingConversationTitle, setEditingConversationTitle] = useState<string>("");
  const [conversationSearch, setConversationSearch] = useState<string>("");
  const [conversationWorkspaceFilter, setConversationWorkspaceFilter] = useState<string>(DEFAULT_CONVERSATION_WORKSPACE_FILTER);
  const [showPinnedOnly, setShowPinnedOnly] = useState<boolean>(false);
  const [selectedWorkspace, setSelectedWorkspace] = useState<string>("Liquefaction");
  const [includeSharedDocuments, setIncludeSharedDocuments] = useState<boolean>(true);
  const [isLoading, setIsLoading] = useState(true);

  const activeConversationSummary = conversations.find((c) => c.id === conversationId);

  async function resolveSavedMessageIds(nextMessages: ChatMessage[]) {
    const bookmarked = new Set<string>();
    for (const msg of nextMessages) {
      if (msg.role === "assistant" && (await isMessageBookmarked(msg.id))) {
        bookmarked.add(msg.id);
      }
    }
    onSetSavedIds(bookmarked);
  }

  async function loadConversationIndex(activeId?: string | null) {
    const list = await getConversations();
    setConversations(list);
    if (activeId !== undefined) {
      setConversationId(activeId);
    }
    return list;
  }

  function applyConversationScope(scope: {
    workspace?: string;
    includeSharedDocuments?: boolean;
  }) {
    if (scope.workspace) setSelectedWorkspace(scope.workspace);
    if (typeof scope.includeSharedDocuments === "boolean") {
      setIncludeSharedDocuments(scope.includeSharedDocuments);
    }
  }

  async function loadConversation(conversation: Conversation) {
    const full = await getConversationById(conversation.id);
    setConversationId(full.id);
    applyConversationScope(full);
    onSetMessages(full.messages);
    await resolveSavedMessageIds(full.messages);
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
        const refreshed = await getConversationById(conversationIdToUpdate);
        onSetMessages(refreshed.messages);
      }
    } catch (err) {
      console.error("Failed to update conversation title:", err);
    } finally {
      cancelConversationTitleEdit();
    }
  }

  const scopeIsDirty = Boolean(
    activeConversationSummary &&
      ((activeConversationSummary.workspace || "") !== selectedWorkspace ||
        (activeConversationSummary.includeSharedDocuments ?? true) !== includeSharedDocuments)
  );

  async function persistConversationScope() {
    if (!conversationId) return;
    try {
      const updated = await updateConversationScope(conversationId, {
        workspace: selectedWorkspace,
        includeSharedDocuments,
      });
      applyConversationScope(updated);
      await loadConversationIndex(updated.id);
    } catch (err) {
      console.error("Failed to persist conversation scope:", err);
    }
  }

  async function handleToggleConversationPin(conversation: Conversation) {
    try {
      await updateConversationPin(conversation.id, !conversation.isPinned);
      await loadConversationIndex(conversation.id);
    } catch (err) {
      console.error("Failed to update conversation pin state:", err);
    }
  }

  function resetConversationDiscoveryFilters() {
    setConversationSearch("");
    setConversationWorkspaceFilter(DEFAULT_CONVERSATION_WORKSPACE_FILTER);
    setShowPinnedOnly(false);
  }

  const pinnedConversationCount = conversations.filter((c) => c.isPinned).length;
  const hasActiveConversationDiscoveryFilters =
    Boolean(conversationSearch.trim()) ||
    conversationWorkspaceFilter !== DEFAULT_CONVERSATION_WORKSPACE_FILTER ||
    showPinnedOnly;

  const filteredConversations = conversations
    .filter((conversation) => {
      if (showPinnedOnly && !conversation.isPinned) return false;
      const workspaceMatch =
        conversationWorkspaceFilter === "all" ||
        conversation.workspace === conversationWorkspaceFilter;
      const searchTerm = conversationSearch.trim().toLowerCase();
      if (!searchTerm) return workspaceMatch;
      const title = getConversationDisplayTitle(conversation).toLowerCase();
      const preview = (conversation.lastMessagePreview || "").toLowerCase();
      return workspaceMatch && (title.includes(searchTerm) || preview.includes(searchTerm));
    })
    .sort((a, b) => {
      const pinPriority = Number(Boolean(b.isPinned)) - Number(Boolean(a.isPinned));
      if (pinPriority !== 0) return pinPriority;
      return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
    });

  // Hydrate persisted discovery preferences per authenticated user
  useEffect(() => {
    hasHydratedDiscoveryPreferences.current = false;
    if (!user || typeof globalThis === "undefined" || !("localStorage" in globalThis)) return;

    const storageKey = getChatDiscoveryPreferencesKey(user.id);
    const raw = globalThis.localStorage.getItem(storageKey);
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as Partial<ChatDiscoveryPreferences>;
        if (typeof parsed.conversationSearch === "string") setConversationSearch(parsed.conversationSearch);
        if (
          typeof parsed.conversationWorkspaceFilter === "string" &&
          (parsed.conversationWorkspaceFilter === "all" ||
            WORKSPACE_OPTIONS.includes(parsed.conversationWorkspaceFilter))
        ) {
          setConversationWorkspaceFilter(parsed.conversationWorkspaceFilter);
        }
        if (typeof parsed.showPinnedOnly === "boolean") setShowPinnedOnly(parsed.showPinnedOnly);
      } catch (err) {
        console.error("Failed to parse chat discovery preferences:", err);
      }
    }
    hasHydratedDiscoveryPreferences.current = true;
  }, [user]);

  // Persist discovery preferences whenever controls change
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

  // Load conversations and active conversation on mount
  useEffect(() => {
    async function loadData() {
      if (!user) {
        setIsLoading(false);
        return;
      }
      setIsLoading(true);
      try {
        const list = await loadConversationIndex();
        const result = await getActiveConversation();
        if (result && list.some((c) => c.id === result.conversation.id)) {
          await loadConversation(result.conversation);
        }
      } catch (err) {
        console.error("Failed to load conversation:", err);
      } finally {
        setIsLoading(false);
      }
    }
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // Intentionally omits loadConversationIndex/loadConversation: these are internal
    // functions that only close over stable React state setters and module-level API
    // calls; adding them to deps would re-run the effect on every render.
  }, [user]);

  async function handleSelectConversation(conversation: Conversation) {
    await loadConversation(conversation);
  }

  async function handleDeleteConversation(conversationIdToDelete: string) {
    try {
      await removeConversation(conversationIdToDelete);
      const isActive = conversationId === conversationIdToDelete;
      const updated = await loadConversationIndex(isActive ? null : conversationId);
      if (isActive) {
        const next = updated.find((c) => c.id !== conversationIdToDelete);
        if (next) {
          await loadConversation(next);
        } else {
          onClearChat();
        }
      }
    } catch (err) {
      console.error("Failed to delete conversation:", err);
    }
  }

  return {
    conversationId,
    setConversationId,
    conversations,
    editingConversationId,
    editingConversationTitle,
    setEditingConversationTitle,
    conversationSearch,
    setConversationSearch,
    conversationWorkspaceFilter,
    setConversationWorkspaceFilter,
    showPinnedOnly,
    setShowPinnedOnly,
    selectedWorkspace,
    setSelectedWorkspace,
    includeSharedDocuments,
    setIncludeSharedDocuments,
    isLoading,
    activeConversationSummary,
    filteredConversations,
    pinnedConversationCount,
    hasActiveConversationDiscoveryFilters,
    scopeIsDirty,
    loadConversationIndex,
    loadConversation,
    applyConversationScope,
    startConversationTitleEdit,
    cancelConversationTitleEdit,
    saveConversationTitle,
    persistConversationScope,
    handleToggleConversationPin,
    resetConversationDiscoveryFilters,
    handleSelectConversation,
    handleDeleteConversation,
  };
}
