/**
 * WebSocket Client
 * Real-time streaming for pipeline status and chat responses.
 *
 * Role in architecture:
 * - Provides low-latency bidirectional channel for status/token updates.
 * - Complements SSE endpoints used elsewhere in the app.
 * - Normalizes backend payloads into typed unions for UI consumers.
 *
 * Supported streams:
 * - Pipeline channel: progress, stage-complete, complete, error, heartbeat.
 * - Chat channel: token, citation, complete, error, heartbeat.
 *
 * Message contracts:
 * - Messages are represented as discriminated unions by `type`.
 * - Unknown or keepalive frames (`connected`, `heartbeat`, `pong`) are preserved but safely typed.
 * - Consumers can switch on `type` exhaustively to guarantee runtime safety.
 *
 * Reliability considerations:
 * - Connection lifecycle (open/close/error) is expected to be handled by caller components.
 * - Heartbeat and pong events enable stale-connection detection.
 * - Errors are structured with context (`stage`, `document_id`) for actionable UI messages.
 *
 * Design note:
 * - This module intentionally focuses on contracts and transport helpers rather than UI logic.
 * - Keeping contracts here avoids duplicated ad-hoc parsing in pages/components.
 */

import { getFastApiWsBaseUrl } from './client';

// ============================================================================
// Type Definitions
// ============================================================================

export type PipelineMessageType =
  | 'connected'
  | 'progress'
  | 'stage-complete'
  | 'error'
  | 'complete'
  | 'heartbeat'
  | 'pong';

export type ChatMessageType =
  | 'connected'
  | 'token'
  | 'citation'
  | 'complete'
  | 'error'
  | 'heartbeat'
  | 'pong';

// Pipeline progress frame emitted repeatedly during active stages.
// `progress` is normalized as percentage [0..100].
export interface PipelineProgressMessage {
  type: 'progress';
  document_id: string;
  stage: string;
  progress: number; // 0-100
  message: string;
  timestamp: string;
}

// Stage-complete frame emitted once per completed backend stage.
// `duration` allows UI to surface per-stage timing diagnostics.
export interface PipelineStageCompleteMessage {
  type: 'stage-complete';
  document_id: string;
  stage: string;
  duration: number; // seconds
  output?: Record<string, unknown>;
  timestamp: string;
}

// Error frame for unrecoverable pipeline-stage failures.
export interface PipelineErrorMessage {
  type: 'error';
  document_id: string;
  stage: string;
  error: string;
  timestamp: string;
}

// Terminal success frame when pipeline processing is complete.
export interface PipelineCompleteMessage {
  type: 'complete';
  document_id: string;
  status: string;
  artifacts: string[];
  timestamp: string;
}

// Token-by-token assistant output for streaming chat UI.
export interface ChatTokenMessage {
  type: 'token';
  content: string;
  conversation_id: string;
  message_id: string;
  timestamp: string;
}

// Citation payload emitted independently from text tokens.
// Enables source badges/drawers to update without waiting for completion.
export interface ChatCitationMessage {
  type: 'citation';
  citation: {
    id: string;
    document_id: string;
    document_title: string;
    section_heading?: string;
    page_number?: number;
    excerpt: string;
    relevance_score: number;
  };
  timestamp: string;
}

// Terminal chat frame containing final citation set for persistence.
export interface ChatCompleteMessage {
  type: 'complete';
  message_id: string;
  citations: Array<{
    id: string;
    document_id: string;
    document_title: string;
    section_heading?: string;
    page_number?: number;
    excerpt: string;
    relevance_score: number;
  }>;
  timestamp: string;
}

// Terminal chat error frame for stream interruption/failure states.
export interface ChatErrorMessage {
  type: 'error';
  error: string;
  timestamp: string;
}

export type PipelineMessage =
  | PipelineProgressMessage
  | PipelineStageCompleteMessage
  | PipelineErrorMessage
  | PipelineCompleteMessage
  | { type: 'connected' | 'heartbeat' | 'pong'; [key: string]: unknown };

export type ChatMessage =
  | ChatTokenMessage
  | ChatCitationMessage
  | ChatCompleteMessage
  | ChatErrorMessage
  | { type: 'connected' | 'heartbeat' | 'pong'; [key: string]: unknown };

const isDevEnvironment = process.env.NODE_ENV !== 'production';

function logDebug(...args: unknown[]): void {
  if (isDevEnvironment) {
    console.debug(...args);
  }
}

function getAuthToken(): string | null {
  if (typeof globalThis === 'undefined' || !('localStorage' in globalThis)) {
    return null;
  }

  return globalThis.localStorage?.getItem('auth_token') ?? null;
}

// ============================================================================
// WebSocket Client Classes
// ============================================================================

/**
 * Base WebSocket client with reconnection logic
 */
abstract class BaseWebSocketClient {
  protected ws: WebSocket | null = null;
  protected reconnectAttempts = 0;
  protected maxReconnectAttempts = 5;
  protected reconnectDelay = 1000; // Start with 1 second
  protected pingInterval: NodeJS.Timeout | null = null;
  protected isIntentionallyClosed = false;

  abstract get wsUrl(): string;

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      console.warn('WebSocket already connected');
      return;
    }

    this.isIntentionallyClosed = false;
    const token = getAuthToken();

    const url = token ? `${this.wsUrl}?token=${token}` : this.wsUrl;
    
    try {
      this.ws = new WebSocket(url);
      this.setupEventHandlers();
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      this.scheduleReconnect();
    }
  }

  private setupEventHandlers(): void {
    if (!this.ws) return;

    this.ws.onopen = () => {
      logDebug('WebSocket connected:', this.wsUrl);
      this.reconnectAttempts = 0;
      this.reconnectDelay = 1000;
      this.startPingInterval();
      this.onOpen();
    };

    this.ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        this.onMessage(message);
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      this.onError(error);
    };

    this.ws.onclose = (event) => {
      logDebug('WebSocket closed:', event.code, event.reason);
      this.stopPingInterval();
      this.onClose(event);

      // Attempt reconnection if not intentionally closed
      if (!this.isIntentionallyClosed && this.reconnectAttempts < this.maxReconnectAttempts) {
        this.scheduleReconnect();
      }
    };
  }

  private scheduleReconnect(): void {
    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
    
    logDebug(
      `Scheduling reconnect attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts} in ${delay}ms`
    );

    setTimeout(() => {
      if (!this.isIntentionallyClosed) {
        this.connect();
      }
    }, delay);
  }

  private startPingInterval(): void {
    // Send ping every 25 seconds (WebSocket timeout is usually 30s)
    this.pingInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 25000);
  }

  private stopPingInterval(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  disconnect(): void {
    this.isIntentionallyClosed = true;
    this.stopPingInterval();
    
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  send(data: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    } else {
      console.warn('WebSocket not connected, cannot send message');
    }
  }

  // Abstract methods to be implemented by subclasses
  protected abstract onOpen(): void;
  protected abstract onMessage(message: unknown): void;
  protected abstract onError(error: Event): void;
  protected abstract onClose(event: CloseEvent): void;
}

/**
 * Pipeline status WebSocket client
 */
export class PipelineWebSocketClient extends BaseWebSocketClient {
  private documentId: string;
  private messageHandler?: (message: PipelineMessage) => void;

  constructor(
    documentId: string,
    messageHandler?: (message: PipelineMessage) => void
  ) {
    super();
    this.documentId = documentId;
    this.messageHandler = messageHandler;
  }

  get wsUrl(): string {
    return `${getFastApiWsBaseUrl()}/ws/pipeline/${this.documentId}`;
  }

  protected onOpen(): void {
    logDebug(`Connected to pipeline status for document: ${this.documentId}`);
  }

  protected onMessage(message: unknown): void {
    if (this.messageHandler) {
      this.messageHandler(message as PipelineMessage);
    }
  }

  protected onError(error: Event): void {
    console.error('Pipeline WebSocket error:', error);
  }

  protected onClose(event: CloseEvent): void {
    logDebug('Pipeline WebSocket closed:', event.code);
  }
}

/**
 * Chat streaming WebSocket client
 */
export class ChatWebSocketClient extends BaseWebSocketClient {
  private conversationId: string;
  private messageHandler?: (message: ChatMessage) => void;

  constructor(
    conversationId: string,
    messageHandler?: (message: ChatMessage) => void
  ) {
    super();
    this.conversationId = conversationId;
    this.messageHandler = messageHandler;
  }

  get wsUrl(): string {
    return `${getFastApiWsBaseUrl()}/ws/chat/${this.conversationId}`;
  }

  protected onOpen(): void {
    logDebug(`Connected to chat stream for conversation: ${this.conversationId}`);
  }

  protected onMessage(message: unknown): void {
    if (this.messageHandler) {
      this.messageHandler(message as ChatMessage);
    }
  }

  protected onError(error: Event): void {
    console.error('Chat WebSocket error:', error);
  }

  protected onClose(event: CloseEvent): void {
    logDebug('Chat WebSocket closed:', event.code);
  }

  /**
   * Send a chat query through the WebSocket
   */
  sendQuery(query: string, documentFilters?: string[], systemFilters?: string[]): void {
    this.send({
      type: 'query',
      query,
      document_filters: documentFilters,
      system_filters: systemFilters,
    });
  }
}
