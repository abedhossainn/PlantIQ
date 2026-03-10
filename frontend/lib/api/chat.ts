/**
 * Chat API Client
 * Handles RAG chat queries with streaming and citation support
 */

import { fastapiFetch, getAuthToken } from './client';

// ============================================================================
// Type Definitions
// ============================================================================

export interface Citation {
  id: string;
  document_id: string;
  document_title: string;
  section_heading?: string;
  page_number?: number;
  excerpt: string;
  relevance_score: number; // 0.0-1.0
}

export interface ChatQueryRequest {
  query: string;
  conversation_id?: string;
  document_filters?: string[]; // Filter by document UUIDs
  system_filters?: string[]; // Filter by system type
  stream?: boolean;
}

export interface ChatQueryResponse {
  message_id: string;
  conversation_id: string;
  content: string;
  citations: Citation[];
  timestamp: string;
}

// ============================================================================
// API Functions
// ============================================================================

/**
 * Submit a RAG chat query (non-streaming)
 * 
 * Process flow:
 * 1. Generate query embedding
 * 2. Search Qdrant for relevant chunks
 * 3. Build RAG prompt with context
 * 4. Generate LLM response
 * 5. Save to database
 * 6. Return complete response with citations
 * 
 * @param request Chat query request
 * @returns Complete response with citations
 */
export async function submitChatQuery(
  request: ChatQueryRequest
): Promise<ChatQueryResponse> {
  return fastapiFetch<ChatQueryResponse>('/api/v1/chat/query', {
    method: 'POST',
    body: JSON.stringify({
      ...request,
      stream: false,
    }),
  });
}

/**
 * Submit a RAG chat query with streaming response (SSE)
 * 
 * Returns an async generator that yields tokens as they're generated
 * 
 * @param request Chat query request
 * @returns Async generator yielding response tokens
 */
export async function* streamChatQuery(
  request: ChatQueryRequest
): AsyncGenerator<string, void, unknown> {
  const token = getAuthToken();

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000'}/api/v1/chat/stream`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify({
        ...request,
        stream: true,
      }),
    }
  );

  if (!response.ok) {
    throw new Error(`Chat streaming failed: ${response.statusText}`);
  }

  if (!response.body) {
    throw new Error('Response body is null');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const processEvent = async function* (event: string): AsyncGenerator<string, void, unknown> {
    const lines = event.split('\n');

    for (const line of lines) {
      if (!line.startsWith('data: ')) {
        continue;
      }

      const data = line.slice(6);

      if (data === '[DONE]') {
        return;
      }

      try {
        const parsed = JSON.parse(data);

        if (parsed.error) {
          throw new Error(parsed.error);
        }

        if (parsed.content || typeof parsed === 'string') {
          yield typeof parsed === 'string' ? parsed : parsed.content;
        }
      } catch (error) {
        if (data && data !== '[DONE]') {
          yield data;
        }
      }
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let separatorIndex = buffer.indexOf('\n\n');
      while (separatorIndex !== -1) {
        const event = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);

        for await (const token of processEvent(event)) {
          yield token;
        }

        if (event.includes('data: [DONE]')) {
          return;
        }

        separatorIndex = buffer.indexOf('\n\n');
      }
    }

    if (buffer.trim()) {
      for await (const token of processEvent(buffer.trim())) {
        yield token;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Helper to consume streaming response and build complete message
 * 
 * @param request Chat query request
 * @param onToken Callback for each token received
 * @returns Complete message content
 */
export async function consumeStreamingResponse(
  request: ChatQueryRequest,
  onToken?: (token: string) => void
): Promise<string> {
  let fullContent = '';

  for await (const token of streamChatQuery(request)) {
    fullContent += token;
    if (onToken) {
      onToken(token);
    }
  }

  return fullContent;
}
