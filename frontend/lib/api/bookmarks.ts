/**
 * Bookmarks API - PostgREST integration
 * Handles bookmark CRUD operations
 */

import { postgrestFetch, from } from './client';
import type { Bookmark } from '@/types';

/**
 * Bookmark detail from bookmark_details view
 */
export interface BookmarkDetail {
  id: string;
  user_id: string;
  conversation_id: string;
  message_id: string;
  tags: string[] | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  // From conversation
  conversation_title: string | null;
  conversation_created_at: string;
  // From message
  message_content: string;
  message_timestamp: string;
  message_citations: unknown | null; // JSONB field
  // User info
  user_username: string;
  user_full_name: string;
}

/**
 * Convert BookmarkDetail to frontend Bookmark type
 */
function toBookmark(detail: BookmarkDetail): Bookmark {
  // Extract query from message (assuming first user message in context)
  // In production, the query would be stored separately or extracted differently
  const query = detail.conversation_title || 'Bookmarked conversation';
  
  // Parse citations if present
  const citations = detail.message_citations 
    ? (Array.isArray(detail.message_citations) ? detail.message_citations : [])
    : [];
  
  return {
    id: detail.id,
    userId: detail.user_id,
    conversationId: detail.conversation_id,
    messageId: detail.message_id,
    query: query,
    answer: detail.message_content,
    citations: citations as Bookmark['citations'],
    createdAt: detail.created_at,
    tags: detail.tags || [],
    notes: detail.notes || undefined,
  };
}

/**
 * Get all bookmarks for current user
 */
export async function getBookmarks(filters?: {
  tag?: string;
  limit?: number;
  offset?: number;
}): Promise<Bookmark[]> {
  const query = from<BookmarkDetail[]>('bookmark_details')
    .select('*')
    .order('created_at', 'desc');
  
  if (filters?.limit) {
    query.limit(filters.limit);
  }
  
  if (filters?.offset) {
    query.offset(filters.offset);
  }
  
  const details = await query.execute();
  
  // Filter by tag on client side since PostgREST array filtering is complex
  let filtered = details;
  if (filters?.tag) {
    filtered = details.filter(d => d.tags?.includes(filters.tag!));
  }
  
  return filtered.map(toBookmark);
}

/**
 * Get single bookmark by ID
 */
export async function getBookmarkById(id: string): Promise<Bookmark> {
  const detail = await from<BookmarkDetail[]>('bookmark_details')
    .select('*')
    .eq('id', id)
    .single();
  
  return toBookmark(detail);
}

/**
 * Create new bookmark
 */
export async function createBookmark(data: {
  conversationId: string;
  messageId: string;
  tags?: string[];
  notes?: string;
}): Promise<Bookmark> {
  // Get current user ID from token (would be in JWT claims)
  // For now, we'll let the database handle it via RLS
  const dbData = {
    conversation_id: data.conversationId,
    message_id: data.messageId,
    tags: data.tags || [],
    notes: data.notes || null,
  };
  
  const created = await postgrestFetch<Array<{ id: string }>>(
    '/bookmarks',
    {
      method: 'POST',
      body: JSON.stringify(dbData),
      headers: {
        'Prefer': 'return=representation',
      },
    }
  );
  
  if (!created || created.length === 0) {
    throw new Error('Failed to create bookmark');
  }
  
  // Re-fetch from view to get full details
  return getBookmarkById(created[0].id);
}

/**
 * Update bookmark
 */
export async function updateBookmark(
  id: string,
  updates: {
    tags?: string[];
    notes?: string;
  }
): Promise<Bookmark> {
  const dbUpdates: Record<string, unknown> = {};
  if (updates.tags !== undefined) dbUpdates.tags = updates.tags;
  if (updates.notes !== undefined) dbUpdates.notes = updates.notes || null;
  
  await postgrestFetch<void>(
    `/bookmarks?id=eq.${id}`,
    {
      method: 'PATCH',
      body: JSON.stringify(dbUpdates),
    }
  );
  
  // Re-fetch to get updated data
  return getBookmarkById(id);
}

/**
 * Delete bookmark
 */
export async function deleteBookmark(id: string): Promise<void> {
  await postgrestFetch<void>(`/bookmarks?id=eq.${id}`, {
    method: 'DELETE',
  });
}

/**
 * Check if a message is bookmarked
 */
export async function isMessageBookmarked(messageId: string): Promise<boolean> {
  const bookmarks = await postgrestFetch<Array<{ id: string }>>(
    `/bookmarks?message_id=eq.${messageId}&select=id&limit=1`
  );
  
  return bookmarks.length > 0;
}
