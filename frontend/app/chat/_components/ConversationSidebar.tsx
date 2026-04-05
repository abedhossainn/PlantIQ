"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Pin, PinOff, Pencil, Check, Trash2, Clock3 } from "lucide-react";
import { DEFAULT_CONVERSATION_WORKSPACE_FILTER, WORKSPACE_OPTIONS } from "../_constants";
import { formatConversationTimestamp, getConversationDisplayTitle } from "../_helpers";
import type { Conversation } from "@/types";

interface ConversationSidebarProps {
  conversationId: string | null;
  filteredConversations: Conversation[];
  pinnedConversationCount: number;
  conversationSearch: string;
  conversationWorkspaceFilter: string;
  showPinnedOnly: boolean;
  hasActiveConversationDiscoveryFilters: boolean;
  editingConversationId: string | null;
  editingConversationTitle: string;
  onSearchChange: (value: string) => void;
  onWorkspaceFilterChange: (value: string) => void;
  onTogglePinnedOnly: () => void;
  onResetFilters: () => void;
  onSelectConversation: (conversation: Conversation) => void;
  onStartEdit: (conversation: Conversation) => void;
  onSaveTitle: (conversationId: string) => void;
  onCancelEdit: () => void;
  onTogglePin: (conversation: Conversation) => void;
  onDeleteConversation: (conversationId: string) => void;
  onTitleEditChange: (value: string) => void;
}

export function ConversationSidebar({
  conversationId,
  filteredConversations,
  pinnedConversationCount,
  conversationSearch,
  conversationWorkspaceFilter,
  showPinnedOnly,
  hasActiveConversationDiscoveryFilters,
  editingConversationId,
  editingConversationTitle,
  onSearchChange,
  onWorkspaceFilterChange,
  onTogglePinnedOnly,
  onResetFilters,
  onSelectConversation,
  onStartEdit,
  onSaveTitle,
  onCancelEdit,
  onTogglePin,
  onDeleteConversation,
  onTitleEditChange,
}: ConversationSidebarProps) {
  return (
    <>
      <div className="px-3 py-3 border-b border-border space-y-2">
        <input
          value={conversationSearch}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search conversations"
          className="w-full rounded border border-border bg-background px-2 py-1.5 text-xs"
        />
        <div className="flex items-center gap-2">
          <Select value={conversationWorkspaceFilter} onValueChange={onWorkspaceFilterChange}>
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
            onClick={onTogglePinnedOnly}
          >
            <Pin className="h-3.5 w-3.5" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 px-2 text-xs"
            disabled={!hasActiveConversationDiscoveryFilters}
            onClick={onResetFilters}
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
                onClick={() => onSelectConversation(conversation)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelectConversation(conversation);
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
                        onChange={(event) => onTitleEditChange(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            onSaveTitle(conversation.id);
                          } else if (event.key === "Escape") {
                            event.preventDefault();
                            onCancelEdit();
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
                        onSaveTitle(conversation.id);
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
                        onTogglePin(conversation);
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
                        onStartEdit(conversation);
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
                      onDeleteConversation(conversation.id);
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
}
