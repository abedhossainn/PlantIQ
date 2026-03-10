/**
 * WebSocket Client
 * Real-time streaming for pipeline status and chat responses
 */

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

export interface PipelineProgressMessage {
  type: 'progress';
  document_id: string;
  stage: string;
  progress: number; // 0-100
  message: string;
  timestamp: string;
}

export interface PipelineStageCompleteMessage {
  type: 'stage-complete';
  document_id: string;
  stage: string;
  duration: number; // seconds
  output?: Record<string, unknown>;
  timestamp: string;
}

export interface PipelineErrorMessage {
  type: 'error';
  document_id: string;
  stage: string;
  error: string;
  timestamp: string;
}

export interface PipelineCompleteMessage {
  type: 'complete';
  document_id: string;
  status: string;
  artifacts: string[];
  timestamp: string;
}

export interface ChatTokenMessage {
  type: 'token';
  content: string;
  conversation_id: string;
  message_id: string;
  timestamp: string;
}

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
      console.log('WebSocket connected:', this.wsUrl);
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
      console.log('WebSocket closed:', event.code, event.reason);
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
    
    console.log(
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
    const baseUrl = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';
    const wsUrl = baseUrl.replace(/^http/, 'ws');
    return `${wsUrl}/ws/pipeline/${this.documentId}`;
  }

  protected onOpen(): void {
    console.log(`Connected to pipeline status for document: ${this.documentId}`);
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
    console.log('Pipeline WebSocket closed:', event.code);
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
    const baseUrl = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';
    const wsUrl = baseUrl.replace(/^http/, 'ws');
    return `${wsUrl}/ws/chat/${this.conversationId}`;
  }

  protected onOpen(): void {
    console.log(`Connected to chat stream for conversation: ${this.conversationId}`);
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
    console.log('Chat WebSocket closed:', event.code);
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
