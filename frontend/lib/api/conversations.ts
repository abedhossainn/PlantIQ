/**
 * Conversations API - PostgREST integration
 * Handles chat conversations and messages
 */

import { postgrestFetch, from } from './client';
import type { Conversation, ChatMessage } from '@/types';

/**
 * Conversation summary from conversation_summaries view
 */
export interface ConversationSummary {
  id: string;
  user_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_at: string | null;
  last_message_preview: string | null;
}

/**
 * Database chat_message structure
 */
export interface DbChatMessage {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: unknown | null; // JSONB
  timestamp: string;
}

/**
 * Convert ConversationSummary to frontend Conversation type (without messages)
 */
function toConversation(summary: ConversationSummary, messages: ChatMessage[] = []): Conversation {
  return {
    id: summary.id,
    userId: summary.user_id,
    title: summary.title || 'New Conversation',
    messages: messages,
    createdAt: summary.created_at,
    updatedAt: summary.updated_at,
  };
}

/**
 * Convert DbChatMessage to frontend ChatMessage type
 */
function toChatMessage(dbMessage: DbChatMessage): ChatMessage {
  return {
    id: dbMessage.id,
    role: dbMessage.role,
    content: dbMessage.content,
    timestamp: dbMessage.timestamp,
    citations: dbMessage.citations ? (Array.isArray(dbMessage.citations) ? dbMessage.citations : []) as ChatMessage['citations'] : undefined,
  };
}

/**
 * Get all conversations for current user (without messages)
 */
export async function getConversations(filters?: {
  limit?: number;
  offset?: number;
}): Promise<Conversation[]> {
  const query = from<ConversationSummary[]>('conversation_summaries')
    .select('*')
    .order('updated_at', 'desc');
  
  if (filters?.limit) {
    query.limit(filters.limit);
  }
  
  if (filters?.offset) {
    query.offset(filters.offset);
  }
  
  const summaries = await query.execute();
  return summaries.map(s => toConversation(s, []));
}

/**
 * Get single conversation by ID with messages
 */
export async function getConversationById(id: string): Promise<Conversation> {
  const summary = await from<ConversationSummary[]>('conversation_summaries')
    .select('*')
    .eq('id', id)
    .single();
  
  const messages = await getConversationMessages(id);
  return toConversation(summary, messages);
}

/**
 * Get messages for a conversation
 */
export async function getConversationMessages(
  conversationId: string,
  filters?: {
    limit?: number;
    offset?: number;
  }
): Promise<ChatMessage[]> {
  const query = from<DbChatMessage[]>('chat_messages')
    .select('*')
    .eq('conversation_id', conversationId)
    .order('timestamp', 'asc');
  
  if (filters?.limit) {
    query.limit(filters.limit);
  }
  
  if (filters?.offset) {
    query.offset(filters.offset);
  }
  
  const dbMessages = await query.execute();
  return dbMessages.map(toChatMessage);
}

/**
 * Create new conversation
 */
export async function createConversation(title?: string): Promise<Conversation> {
  const dbData = {
    title: title || null,
  };
  
  const created = await postgrestFetch<ConversationSummary[]>(
    '/conversations',
    {
      method: 'POST',
      body: JSON.stringify(dbData),
      headers: {
        'Prefer': 'return=representation',
      },
    }
  );
  
  if (!created || created.length === 0) {
    throw new Error('Failed to create conversation');
  }
  
  return toConversation(created[0]);
}

/**
 * Create new message in a conversation
 */
export async function createMessage(data: {
  conversationId: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: unknown;
}): Promise<ChatMessage> {
  const dbData = {
    conversation_id: data.conversationId,
    role: data.role,
    content: data.content,
    citations: data.citations || null,
  };
  
  const created = await postgrestFetch<DbChatMessage[]>(
    '/chat_messages',
    {
      method: 'POST',
      body: JSON.stringify(dbData),
      headers: {
        'Prefer': 'return=representation',
      },
    }
  );
  
  if (!created || created.length === 0) {
    throw new Error('Failed to create message');
  }
  
  return toChatMessage(created[0]);
}

/**
 * Update conversation title
 */
export async function updateConversationTitle(
  id: string,
  title: string
): Promise<Conversation> {
  await postgrestFetch<void>(
    `/conversations?id=eq.${id}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    }
  );
  
  return getConversationById(id);
}

/**
 * Delete conversation
 */
export async function deleteConversation(id: string): Promise<void> {
  await postgrestFetch<void>(`/conversations?id=eq.${id}`, {
    method: 'DELETE',
  });
}

/**
 * Get active conversation (most recent) with messages
 */
export async function getActiveConversation(): Promise<{
  conversation: Conversation;
  messages: ChatMessage[];
} | null> {
  const conversations = await getConversations({ limit: 1 });
  
  if (conversations.length === 0) {
    return null;
  }
  
  const conversation = conversations[0];
  const convMessages = await getConversationMessages(conversation.id);
  conversation.messages = convMessages;
  
  return {
    conversation,
    messages: convMessages,
  };
}
