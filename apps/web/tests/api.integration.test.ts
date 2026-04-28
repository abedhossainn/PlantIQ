import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  canAccessFeedbackMetrics,
  consumeStreamingResponse,
  getChatFeedbackMetrics,
  streamChatQuery,
  submitChatFeedback,
  submitChatQuery,
} from '../lib/api/chat';
import type { Citation as ApiCitation } from '../lib/api/chat';
import { getActiveConversation, getConversations, updateConversationPin, updateConversationScope, updateConversationTitle } from '../lib/api/conversations';
import { ApiError, fastapiFetch, formatScopeDeniedMessage, from, getFastApiBaseUrl, parseScopeAccessDeniedPayload, postgrestFetch } from '../lib/api/client';
import { deleteDocument, getDocuments } from '../lib/api/documents';
import { canOpenOptimizedReview, getOptimizationLifecycleLabel, isQAReadyStatus } from '../lib/document-status';
import { downloadArtifact, fetchArtifactJson, getPipelineStatus, streamIngestionEvents, streamOptimizationLogs, uploadDocument } from '../lib/api/pipeline';
import { getDocumentOptimizedChunks, updateOptimizedChunk } from '../lib/api/optimized-review';
import { ChatWebSocketClient, PipelineWebSocketClient } from '../lib/api/websocket';
import {
  activateAdminDirectoryConfig,
  getAdminDirectoryConfig,
  testAdminDirectoryConfig,
  upsertAdminDirectoryConfig,
} from '../lib/api/users';

class LocalStorageMock {
  private store = new Map<string, string>();

  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  clear(): void {
    this.store.clear();
  }
}

class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readonly url: string;
  readyState = MockWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
  }

  open(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.({} as Event);
  }

  emitMessage(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  });
}

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });

  return new Response(stream, {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  });
}

describe('frontend hybrid API integration contracts', () => {
  const fetchMock = vi.fn();
  const localStorageMock = new LocalStorageMock();

  beforeEach(() => {
    localStorageMock.clear();
    localStorageMock.setItem('auth_token', 'test-token');
    MockWebSocket.instances = [];
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('localStorage', localStorageMock);
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.useRealTimers();
    vi.unstubAllEnvs();
  });

  it('resolves FastAPI base URL from NEXT_PUBLIC_API_URL when NEXT_PUBLIC_FASTAPI_URL is unset', () => {
    vi.stubEnv('NEXT_PUBLIC_FASTAPI_URL', undefined);
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://localhost:8001');

    expect(getFastApiBaseUrl()).toBe('http://localhost:8001');
  });

  it('uses NEXT_PUBLIC_API_URL for FastAPI requests when NEXT_PUBLIC_FASTAPI_URL is unset', async () => {
    vi.stubEnv('NEXT_PUBLIC_FASTAPI_URL', undefined);
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://localhost:8001');

    fetchMock.mockResolvedValueOnce(jsonResponse([{ id: 'doc-1' }]));

    await fastapiFetch('/api/v1/documents');

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8001/api/v1/documents');
  });

  it('labels approved-for-optimization as ready for optimization in the optimization workflow', () => {
    expect(getOptimizationLifecycleLabel('approved-for-optimization')).toBe('Ready for Optimization');
  });

  it('submits non-streaming chat queries through FastAPI with auth', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        message_id: 'msg-1',
        conversation_id: 'conv-1',
        content: 'Answer',
        citations: [],
        timestamp: '2026-03-10T00:00:00Z',
      })
    );

    const result = await submitChatQuery({ query: 'What is LNG?' });

    expect(result.content).toBe('Answer');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/chat/query');
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer test-token');
    expect(JSON.parse(options.body as string)).toEqual({
      query: 'What is LNG?',
      stream: false,
    });
  });

  it('submits scoped chat payload with workspace preference', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        message_id: 'msg-2',
        conversation_id: 'conv-2',
        content: 'Scoped answer',
        citations: [],
        timestamp: '2026-03-10T00:00:00Z',
      })
    );

    await submitChatQuery({
      query: 'How do I start liquefaction?',
      workspace: 'Liquefaction',
      include_shared_documents: true,
    });

    const [, options] = fetchMock.mock.calls[0];
    expect(JSON.parse(options.body as string)).toEqual({
      query: 'How do I start liquefaction?',
      workspace: 'Liquefaction',
      include_shared_documents: true,
      stream: false,
    });
  });

  it('submits Candidate 2 feedback payload with optional reason/comment fields', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        event_id: 'evt-1',
        answer_message_id: '550e8400-e29b-41d4-a716-446655440000',
        conversation_id: '550e8400-e29b-41d4-a716-446655440001',
        timestamp: '2026-04-27T00:00:00Z',
        snapshot: {
          answer_message_id: '550e8400-e29b-41d4-a716-446655440000',
          conversation_id: '550e8400-e29b-41d4-a716-446655440001',
          feedback_count: 3,
          positive_count: 2,
          negative_count: 1,
          negative_streak: 0,
          quality_score: 0.33,
          is_flagged: false,
          last_feedback_at: '2026-04-27T00:00:00Z',
        },
      })
    );

    await submitChatFeedback({
      answer_message_id: '550e8400-e29b-41d4-a716-446655440000',
      conversation_id: '550e8400-e29b-41d4-a716-446655440001',
      sentiment: 'down',
      reason_code: 'INSUFFICIENT_DETAIL',
      comment: 'Please include startup prerequisites.',
      area_scope: 'Liquefaction',
    });

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/chat/feedback');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body as string)).toEqual({
      answer_message_id: '550e8400-e29b-41d4-a716-446655440000',
      conversation_id: '550e8400-e29b-41d4-a716-446655440001',
      sentiment: 'down',
      reason_code: 'INSUFFICIENT_DETAIL',
      comment: 'Please include startup prerequisites.',
      area_scope: 'Liquefaction',
    });
  });

  it('normalizes feedback API error messages from backend detail payload', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          detail: {
            code: 'INVALID_FEEDBACK_TARGET',
            message: 'Feedback can only target assistant answer messages.',
          },
        },
        { status: 400, statusText: 'Bad Request' }
      )
    );

    await expect(
      submitChatFeedback({
        answer_message_id: 'bad-id',
        sentiment: 'up',
      })
    ).rejects.toMatchObject({
      message: 'Feedback can only target assistant answer messages.',
      status: 400,
    });
  });

  it('fetches Candidate 2 feedback metrics with expected query parameters', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        window_days: 7,
        total_feedback_events: 10,
        positive_feedback_events: 8,
        negative_feedback_events: 2,
        flagged_answers: 1,
        reason_breakdown: [{ reason_code: 'INACCURATE', count: 2 }],
      })
    );

    const metrics = await getChatFeedbackMetrics({
      window_days: 7,
      area_scope: 'Liquefaction',
    });

    expect(metrics.total_feedback_events).toBe(10);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/chat/feedback/metrics?window_days=7&area_scope=Liquefaction');
  });

  it('enforces role gating contract for feedback metrics visibility', () => {
    expect(canAccessFeedbackMetrics('admin')).toBe(true);
    expect(canAccessFeedbackMetrics('reviewer')).toBe(true);
    expect(canAccessFeedbackMetrics('plantig_admin')).toBe(true);
    expect(canAccessFeedbackMetrics('plantig_reviewer')).toBe(true);
    expect(canAccessFeedbackMetrics('user')).toBe(false);
    expect(canAccessFeedbackMetrics()).toBe(false);
  });

  it('loads redacted admin directory config from backend contract', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: 'cfg-1',
        host: 'ldap.local',
        server_url: 'ldap://ldap.local:389',
        port: 389,
        base_dn: 'dc=plantiq,dc=local',
        user_search_base: 'ou=users,dc=plantiq,dc=local',
        bind_dn: 'cn=admin,dc=plantiq,dc=local',
        has_bind_password: true,
        use_ssl: false,
        start_tls: false,
        verify_cert_mode: 'required',
        search_filter_template: '(&(objectClass=person)(uid={username}))',
        is_active: false,
        updated_by: null,
        updated_at: '2026-04-27T00:00:00Z',
        created_at: '2026-04-27T00:00:00Z',
      })
    );

    const cfg = await getAdminDirectoryConfig();

    expect(cfg.host).toBe('ldap.local');
    expect(cfg.has_bind_password).toBe(true);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/auth/admin/directory-config');
    expect((options.method ?? 'GET')).toBe('GET');
  });

  it('saves admin directory config through PUT endpoint', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: 'cfg-2',
        host: 'ldap.prod.local',
        server_url: 'ldaps://ldap.prod.local:636',
        port: 636,
        base_dn: 'dc=prod,dc=local',
        user_search_base: 'ou=users,dc=prod,dc=local',
        bind_dn: 'cn=svc,dc=prod,dc=local',
        has_bind_password: true,
        use_ssl: true,
        start_tls: false,
        verify_cert_mode: 'required',
        search_filter_template: '(&(objectClass=person)(uid={username}))',
        is_active: false,
        updated_by: null,
        updated_at: '2026-04-27T00:00:00Z',
        created_at: '2026-04-27T00:00:00Z',
      })
    );

    const saved = await upsertAdminDirectoryConfig({
      host: 'ldap.prod.local',
      port: 636,
      base_dn: 'dc=prod,dc=local',
      user_search_base: 'ou=users,dc=prod,dc=local',
      bind_dn: 'cn=svc,dc=prod,dc=local',
      bind_password: 'SecretPass!123',
      use_ssl: true,
      start_tls: false,
      verify_cert_mode: 'required',
      search_filter_template: '(&(objectClass=person)(uid={username}))',
    });

    expect(saved.port).toBe(636);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/auth/admin/directory-config');
    expect(options.method).toBe('PUT');
    expect(JSON.parse(options.body as string)).toMatchObject({
      host: 'ldap.prod.local',
      bind_password: 'SecretPass!123',
      use_ssl: true,
    });
  });

  it('tests supplied admin directory config through non-destructive endpoint', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        success: true,
        message: 'Connection test passed',
        source: 'supplied',
      })
    );

    const result = await testAdminDirectoryConfig({
      config: {
        host: 'ldap.test.local',
        port: 389,
        base_dn: 'dc=test,dc=local',
        user_search_base: 'ou=users,dc=test,dc=local',
        bind_dn: 'cn=svc,dc=test,dc=local',
        bind_password: 'TestPass!123',
        use_ssl: false,
        start_tls: true,
        verify_cert_mode: 'optional',
        search_filter_template: '(&(objectClass=person)(uid={username}))',
      },
    });

    expect(result.success).toBe(true);
    expect(result.source).toBe('supplied');
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/auth/admin/directory-config/test');
    expect(options.method).toBe('POST');
  });

  it('activates admin directory config through activation endpoint', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: 'cfg-3',
        host: 'ldap.active.local',
        server_url: 'ldap://ldap.active.local:389',
        port: 389,
        base_dn: 'dc=active,dc=local',
        user_search_base: 'ou=users,dc=active,dc=local',
        bind_dn: 'cn=svc,dc=active,dc=local',
        has_bind_password: true,
        use_ssl: false,
        start_tls: true,
        verify_cert_mode: 'required',
        search_filter_template: '(&(objectClass=person)(uid={username}))',
        is_active: true,
        updated_by: null,
        updated_at: '2026-04-27T00:00:00Z',
        created_at: '2026-04-27T00:00:00Z',
      })
    );

    const activated = await activateAdminDirectoryConfig();

    expect(activated.is_active).toBe(true);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/auth/admin/directory-config/activate');
    expect(options.method).toBe('POST');
  });

  it('normalizes admin directory config API errors from backend detail payload', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          detail: {
            code: 'DIRECTORY_CONFIG_INVALID',
            message: 'use_ssl and start_tls cannot both be true',
          },
        },
        { status: 422, statusText: 'Unprocessable Entity' }
      )
    );

    await expect(
      upsertAdminDirectoryConfig({
        host: 'ldap.bad.local',
        port: 389,
        base_dn: 'dc=bad,dc=local',
        user_search_base: 'ou=users,dc=bad,dc=local',
        bind_dn: 'cn=svc,dc=bad,dc=local',
        use_ssl: true,
        start_tls: true,
        verify_cert_mode: 'required',
        search_filter_template: '(&(objectClass=person)(uid={username}))',
      })
    ).rejects.toMatchObject({
      message: 'use_ssl and start_tls cannot both be true',
      status: 422,
    });
  });

  it('parses Candidate 1 scope-denial contract for chat requests', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          detail: {
            code: 'SCOPE_ACCESS_DENIED',
            reason_code: 'SYSTEM_SCOPE_RESTRICTED',
            message: 'You are not permitted to query Liquefaction.',
            requested_scope: {
              workspace: 'Liquefaction',
              include_shared_documents: true,
            },
          },
        },
        { status: 403, statusText: 'Forbidden' }
      )
    );

    let thrown: unknown;
    try {
      await submitChatQuery({
        query: 'How do I start liquefaction?',
        workspace: 'Liquefaction',
      });
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toBeInstanceOf(ApiError);
    const apiError = thrown as ApiError;
    expect(apiError.status).toBe(403);

    const denied = parseScopeAccessDeniedPayload(apiError.data);
    expect(denied?.code).toBe('SCOPE_ACCESS_DENIED');
    expect(denied?.reason_code).toBe('SYSTEM_SCOPE_RESTRICTED');
    expect(denied?.requested_scope).toMatchObject({ workspace: 'Liquefaction' });
    expect(formatScopeDeniedMessage(denied!)).toContain('SYSTEM_SCOPE_RESTRICTED');
  });

  it('hydrates persisted conversation scope metadata from conversation summaries', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: 'conv-1',
          user_id: 'user-1',
          title: 'Scoped conversation',
          workspace: 'Mechanical',
          document_type_filters: ['Maintenance Manual'],
          preferred_document_types: ['Maintenance Manual'],
          include_shared_documents: false,
          created_at: '2026-03-27T00:00:00Z',
          updated_at: '2026-03-27T01:00:00Z',
          message_count: 2,
          last_message_at: '2026-03-27T01:00:00Z',
          last_message_preview: 'Use the mechanical maintenance checklist.',
        },
      ])
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: 'msg-1',
          conversation_id: 'conv-1',
          role: 'assistant',
          content: 'Use the mechanical maintenance checklist.',
          citations: [],
          timestamp: '2026-03-27T01:00:00Z',
        },
      ])
    );

    const activeConversation = await getActiveConversation();

    expect(activeConversation?.conversation.workspace).toBe('Mechanical');
    expect(activeConversation?.conversation.documentTypeFilters).toEqual(['Maintenance Manual']);
    expect(activeConversation?.conversation.preferredDocumentTypes).toEqual(['Maintenance Manual']);
    expect(activeConversation?.conversation.includeSharedDocuments).toBe(false);
    expect(activeConversation?.messages).toHaveLength(1);
  });

  it('maps conversation summaries into history-ready conversation metadata', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: 'conv-1',
          user_id: 'user-1',
          title: 'What maintenance checklist applies?',
          workspace: 'Mechanical',
          document_type_filters: ['Maintenance Manual'],
          preferred_document_types: ['Maintenance Manual'],
          include_shared_documents: false,
          created_at: '2026-03-27T00:00:00Z',
          updated_at: '2026-03-27T01:00:00Z',
          message_count: 4,
          last_message_at: '2026-03-27T01:05:00Z',
          last_message_preview: 'Use the mechanical maintenance checklist before startup.',
        },
      ])
    );

    const conversations = await getConversations({ limit: 10 });

    expect(conversations).toHaveLength(1);
    expect(conversations[0].title).toBe('What maintenance checklist applies?');
    expect(conversations[0].workspace).toBe('Mechanical');
    expect(conversations[0].isPinned).toBe(false);
    expect(conversations[0].messageCount).toBe(4);
    expect(conversations[0].lastMessagePreview).toBe('Use the mechanical maintenance checklist before startup.');
    expect(conversations[0].includeSharedDocuments).toBe(false);
  });

  it('maps pinned conversation metadata from conversation summaries', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: 'conv-pin',
          user_id: 'user-1',
          title: 'Pinned runbook',
          is_pinned: true,
          workspace: 'Liquefaction',
          document_type_filters: ['Procedure'],
          preferred_document_types: ['Procedure'],
          include_shared_documents: true,
          created_at: '2026-03-27T00:00:00Z',
          updated_at: '2026-03-27T01:00:00Z',
          message_count: 1,
          last_message_at: '2026-03-27T01:00:00Z',
          last_message_preview: 'Pinned checklist.',
        },
      ])
    );

    const conversations = await getConversations({ limit: 10 });

    expect(conversations).toHaveLength(1);
    expect(conversations[0].isPinned).toBe(true);
  });

  it('applies search filter when fetching conversations', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    await getConversations({ search: 'startup' });

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(
      'http://localhost:3001/conversation_summaries?select=*&order=is_pinned.desc%2Cupdated_at.desc&title=like.*startup*'
    );
  });

  it('applies workspace filter when fetching conversations', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    await getConversations({ workspace: 'Liquefaction', limit: 10, offset: 5 });

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(
      'http://localhost:3001/conversation_summaries?select=*&order=is_pinned.desc%2Cupdated_at.desc&workspace=eq.Liquefaction&limit=10&offset=5'
    );
  });

  it('updates conversation title through PostgREST and returns refreshed conversation payload', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: 'conv-1',
          user_id: 'user-1',
          title: 'Updated title',
          workspace: 'Liquefaction',
          document_type_filters: ['Procedure'],
          preferred_document_types: ['Procedure'],
          include_shared_documents: true,
          created_at: '2026-03-27T00:00:00Z',
          updated_at: '2026-03-27T01:00:00Z',
          message_count: 1,
          last_message_at: '2026-03-27T01:00:00Z',
          last_message_preview: 'Checklist loaded.',
        },
      ])
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: 'msg-1',
          conversation_id: 'conv-1',
          role: 'assistant',
          content: 'Checklist loaded.',
          citations: [],
          timestamp: '2026-03-27T01:00:00Z',
        },
      ])
    );

    const updatedConversation = await updateConversationTitle('conv-1', 'Updated title');

    const [patchUrl, patchOptions] = fetchMock.mock.calls[0];
    expect(patchUrl).toBe('http://localhost:3001/conversations?id=eq.conv-1');
    expect(patchOptions.method).toBe('PATCH');
    expect(JSON.parse(patchOptions.body as string)).toEqual({ title: 'Updated title' });

    expect(updatedConversation.title).toBe('Updated title');
    expect(updatedConversation.messages).toHaveLength(1);
  });

  it('updates conversation scope through PostgREST and returns refreshed conversation payload', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: 'conv-2',
          user_id: 'user-1',
          title: 'Scope test',
          workspace: 'Mechanical',
          document_type_filters: ['Maintenance Manual'],
          preferred_document_types: ['Maintenance Manual'],
          include_shared_documents: false,
          created_at: '2026-03-27T00:00:00Z',
          updated_at: '2026-03-27T02:00:00Z',
          message_count: 2,
          last_message_at: '2026-03-27T02:00:00Z',
          last_message_preview: 'Updated scope saved.',
        },
      ])
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: 'msg-2',
          conversation_id: 'conv-2',
          role: 'assistant',
          content: 'Updated scope saved.',
          citations: [],
          timestamp: '2026-03-27T02:00:00Z',
        },
      ])
    );

    const updatedConversation = await updateConversationScope('conv-2', {
      workspace: 'Mechanical',
      includeSharedDocuments: false,
    });

    const [patchUrl, patchOptions] = fetchMock.mock.calls[0];
    expect(patchUrl).toBe('http://localhost:3001/conversations?id=eq.conv-2');
    expect(patchOptions.method).toBe('PATCH');
    expect(JSON.parse(patchOptions.body as string)).toEqual({
      workspace: 'Mechanical',
      include_shared_documents: false,
    });

    expect(updatedConversation.workspace).toBe('Mechanical');
    expect(updatedConversation.includeSharedDocuments).toBe(false);
  });

  it('updates conversation pin state through PostgREST and returns refreshed conversation payload', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: 'conv-pin-1',
          user_id: 'user-1',
          title: 'Pinned title',
          is_pinned: true,
          workspace: 'Liquefaction',
          document_type_filters: ['Procedure'],
          preferred_document_types: ['Procedure'],
          include_shared_documents: true,
          created_at: '2026-03-27T00:00:00Z',
          updated_at: '2026-03-27T02:00:00Z',
          message_count: 2,
          last_message_at: '2026-03-27T02:00:00Z',
          last_message_preview: 'Pinned scope saved.',
        },
      ])
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: 'msg-pin-1',
          conversation_id: 'conv-pin-1',
          role: 'assistant',
          content: 'Pinned scope saved.',
          citations: [],
          timestamp: '2026-03-27T02:00:00Z',
        },
      ])
    );

    const updatedConversation = await updateConversationPin('conv-pin-1', true);

    const [patchUrl, patchOptions] = fetchMock.mock.calls[0];
    expect(patchUrl).toBe('http://localhost:3001/conversations?id=eq.conv-pin-1');
    expect(patchOptions.method).toBe('PATCH');
    expect(JSON.parse(patchOptions.body as string)).toEqual({ is_pinned: true });

    expect(updatedConversation.isPinned).toBe(true);
    expect(updatedConversation.messages).toHaveLength(1);
  });

  it('consumes chat SSE token events and accumulates content', async () => {
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: token\ndata: {"event":"token","conversation_id":"conv-1","message_id":"msg-1","token":"Hel","content":"Hel","done":false}\n\n',
        'event: token\ndata: {"event":"token","conversation_id":"conv-1","message_id":"msg-1","token":"lo","content":"lo","done":false}\n\n',
        'event: token\ndata: {"event":"token","conversation_id":"conv-1","message_id":"msg-1","token":" world","content":" world","done":false}\n\n',
        'event: complete\ndata: {"event":"complete","conversation_id":"conv-1","message_id":"msg-1","done":true}\n\n',
      ])
    );

    const tokens: string[] = [];
    const fullResponse = await consumeStreamingResponse(
      { query: 'stream me' },
      (token) => tokens.push(token)
    );

    expect(fullResponse).toBe('Hello world');
    expect(tokens).toEqual(['Hel', 'lo', ' world']);
  });

  it('collects citations from chat SSE citation events', async () => {
    const citationPayload: ApiCitation = {
      id: 'cite-1',
      document_id: 'doc-abc',
      document_title: 'LNG Manual',
      section_heading: 'Safety',
      page_number: 42,
      workspace: 'Liquefaction',
      system: 'Liquefaction',
      document_type: 'Procedure',
      excerpt: 'Keep away from open flames.',
      relevance_score: 0.95,
    };

    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: token\ndata: {"event":"token","conversation_id":"conv-1","message_id":"msg-1","token":"Answer","content":"Answer","done":false}\n\n',
        `event: citation\ndata: ${JSON.stringify({ event: 'citation', conversation_id: 'conv-1', message_id: 'msg-1', citation: citationPayload, done: false })}\n\n`,
        'event: complete\ndata: {"event":"complete","conversation_id":"conv-1","message_id":"msg-1","done":true}\n\n',
      ])
    );

    const receivedCitations: ApiCitation[] = [];
    const content = await consumeStreamingResponse(
      { query: 'cite me' },
      undefined,
      (c) => receivedCitations.push(c)
    );

    expect(content).toBe('Answer');
    expect(receivedCitations).toHaveLength(1);
    expect(receivedCitations[0].document_title).toBe('LNG Manual');
    expect(receivedCitations[0].page_number).toBe(42);
    expect(receivedCitations[0].workspace).toBe('Liquefaction');
    expect(receivedCitations[0].document_type).toBe('Procedure');
  });

  it('terminates stream cleanly on complete event', async () => {
    // complete arrives before the stream body closes — generator should return
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: token\ndata: {"event":"token","conversation_id":"conv-1","message_id":"msg-1","token":"Hi","content":"Hi","done":false}\n\n',
        'event: complete\ndata: {"event":"complete","conversation_id":"conv-1","message_id":"msg-1","done":true}\n\n',
        // This token should NOT be yielded — stream already terminated on complete.
        'event: token\ndata: {"event":"token","conversation_id":"conv-1","message_id":"msg-1","token":"extra","content":"extra","done":false}\n\n',
      ])
    );

    const events = [];
    for await (const evt of streamChatQuery({ query: 'stop test' })) {
      events.push(evt);
    }

    const types = events.map((e) => e.type);
    expect(types).toContain('token');
    expect(types).toContain('complete');
    // 'extra' token after complete must not appear
    const tokenContents = events
      .filter((e) => e.type === 'token')
      .map((e) => (e as { type: 'token'; content: string }).content);
    expect(tokenContents).not.toContain('extra');
  });

  it('surfaces error events from chat SSE stream', async () => {
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: error\ndata: {"event":"error","error":"LLM inference failed","done":true}\n\n',
      ])
    );

    await expect(
      consumeStreamingResponse({ query: 'error test' })
    ).rejects.toThrow('LLM inference failed');
  });

  it('parses chat SSE blocks split across chunk boundaries', async () => {
    // The SSE block is split across two decoded chunks.
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: token\ndata: {"event":"token","conversation_id":"conv-1","message_id":"msg-1","token":"Hel',
        'lo","content":"Hello","done":false}\n\nevent: complete\ndata: {"event":"complete","conversation_id":"conv-1","message_id":"msg-1","done":true}\n\n',
      ])
    );

    const tokens: string[] = [];
    await consumeStreamingResponse({ query: 'chunk test' }, (t) => tokens.push(t));
    expect(tokens).toContain('Hello');
  });

  it('returns cleanly when chat SSE closes without a complete event', async () => {
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: token\ndata: {"event":"token","conversation_id":"conv-1","message_id":"msg-1","token":"partial","content":"partial","done":false}\n\n',
      ])
    );

    const tokens: string[] = [];
    const content = await consumeStreamingResponse({ query: 'implicit eof' }, (t) => tokens.push(t));

    expect(tokens).toEqual(['partial']);
    expect(content).toBe('partial');
  });

  it('uploads documents as multipart form data without forcing JSON content type', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        document_id: 'doc-1',
        status: 'extracting',
        file_path: '/tmp/doc-1_manual.pdf',
        message: 'started',
      })
    );

    const file = new File(['%PDF-1.4'], 'manual.pdf', { type: 'application/pdf' });
    const result = await uploadDocument({
      file,
      title: 'Plant Manual',
      version: '1.0',
      system: 'LNG',
      documentType: 'procedure',
      notes: 'integration-test',
    });

    expect(result.status).toBe('extracting');
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/documents/upload');

    const headers = options.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer test-token');
    expect(headers['Content-Type']).toBeUndefined();

    const formData = options.body as FormData;
    expect(formData.get('title')).toBe('Plant Manual');
    expect(formData.get('version')).toBe('1.0');
    expect(formData.get('system')).toBe('LNG');
    expect(formData.get('document_type')).toBe('procedure');
    expect(formData.get('notes')).toBe('integration-test');
  });

  it('parses Candidate 1 scope-denial contract for upload requests', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          detail: {
            code: 'SCOPE_ACCESS_DENIED',
            reason_code: 'SYSTEM_SCOPE_RESTRICTED',
            message: 'Upload to this system is restricted.',
            requested_scope: {
              system: 'Power Block',
            },
          },
        },
        { status: 403, statusText: 'Forbidden' }
      )
    );

    const file = new File(['%PDF-1.4'], 'manual.pdf', { type: 'application/pdf' });

    let thrown: unknown;
    try {
      await uploadDocument({
        file,
        title: 'Restricted Upload',
        system: 'Power Block',
        documentType: 'Procedure',
      });
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toBeInstanceOf(ApiError);
    const apiError = thrown as ApiError;
    expect(apiError.status).toBe(403);

    const denied = parseScopeAccessDeniedPayload(apiError.data);
    expect(denied?.code).toBe('SCOPE_ACCESS_DENIED');
    expect(denied?.requested_scope).toMatchObject({ system: 'Power Block' });
    expect(formatScopeDeniedMessage(denied!)).toContain('Power Block');
  });

  it('downloads artifacts using the backend route contract', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('artifact-data', {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    );

    const blob = await downloadArtifact('doc-123', 'qa-report');
    expect(await blob.text()).toBe('artifact-data');

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/documents/doc-123/artifacts/qa_report');
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer test-token');
  });

  it('fetchArtifactJson uses the resolved FastAPI base URL and disables caching', async () => {
    vi.stubEnv('NEXT_PUBLIC_FASTAPI_URL', undefined);
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://localhost:8001');

    fetchMock.mockResolvedValueOnce(
      jsonResponse({ decision: 'review', metrics: {}, passed_criteria: [], failed_criteria: [], recommendations: [] })
    );

    await fetchArtifactJson('doc-123', 'qa_report');

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8001/api/v1/documents/doc-123/artifacts/qa_report');
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer test-token');
    expect(options.cache).toBe('no-store');
  });

  it('builds PostgREST queries with filters, sort order, and auth', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([{ id: 'doc-1', title: 'Doc 1' }]));

    const result = await from<Array<{ id: string; title: string }>>('document_summaries')
      .select('id,title')
      .eq('status', 'in-review')
      .order('uploaded_at', 'desc')
      .limit(5)
      .execute();

    expect(result).toEqual([{ id: 'doc-1', title: 'Doc 1' }]);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe(
      'http://localhost:3001/document_summaries?select=id%2Ctitle&status=eq.in-review&order=uploaded_at.desc&limit=5'
    );
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer test-token');
  });

  it('creates authenticated websocket connections and sends heartbeat pings', () => {
    vi.useFakeTimers();
    const handler = vi.fn();
    const client = new PipelineWebSocketClient('doc-123', handler);

    client.connect();
    const socket = MockWebSocket.instances[0];

    expect(socket.url).toBe('ws://localhost:8000/ws/pipeline/doc-123?token=test-token');

    socket.open();
    socket.emitMessage({
      type: 'progress',
      document_id: 'doc-123',
      stage: 'extracting',
      progress: 25,
      message: 'Extracting',
      timestamp: '2026-03-10T00:00:00Z',
    });

    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'progress', progress: 25 })
    );

    vi.advanceTimersByTime(25000);
    expect(socket.sent).toContain(JSON.stringify({ type: 'ping' }));

    client.disconnect();
    expect(socket.readyState).toBe(MockWebSocket.CLOSED);
  });

  it('sends websocket chat queries with optional filters', () => {
    const client = new ChatWebSocketClient('conv-123');
    client.connect();

    const socket = MockWebSocket.instances[0];
    socket.open();

    client.sendQuery('What is LNG density?', ['doc-1'], ['LNG']);

    expect(socket.sent).toContain(
      JSON.stringify({
        type: 'query',
        query: 'What is LNG density?',
        document_filters: ['doc-1'],
        system_filters: ['LNG'],
      })
    );
  });

  it('fetches pipeline status through FastAPI', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        document_id: 'doc-123',
        status: 'vlm-validating',
        current_stage: 'vlm-validation',
        progress: 60,
      })
    );

    const result = await getPipelineStatus('doc-123');
    expect(result.progress).toBe(60);

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/documents/doc-123/status');
  });

  it('deletes documents through the FastAPI cleanup endpoint with auth', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        document_id: 'doc-delete-1',
        qdrant_chunks_deleted: true,
        deleted_paths: ['/tmp/doc-delete-1.pdf', '/tmp/doc-delete-1'],
        message: 'Document deleted successfully',
      })
    );

    const result = await deleteDocument('doc-delete-1');

    expect(result.document_id).toBe('doc-delete-1');
    expect(result.qdrant_chunks_deleted).toBe(true);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/documents/doc-delete-1');
    expect(options.method).toBe('DELETE');
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer test-token');
  });

  it('maps snake_case document counters into frontend totalPages and totalSections', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: 'doc-1',
          title: 'COMMON Module 4 Electrical Distribution System',
          version: '1',
          system: 'Electrical',
          document_type: 'Technical Manual',
          status: 'final-approved',
          uploaded_by: 'admin',
          uploaded_at: '2026-04-21T00:00:00Z',
          total_pages: 235,
          total_sections: 51,
          review_progress: 100,
          qa_score: 99,
        },
      ])
    );

    const docs = await getDocuments();

    expect(docs).toHaveLength(1);
    expect(docs[0].totalPages).toBe(235);
    expect(docs[0].totalSections).toBe(51);
    expect(docs[0].documentType).toBe('Technical Manual');
  });

  it('maps camelCase document counters into frontend totalPages and totalSections', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          id: 'doc-2',
          title: 'COMMON Module 3 Characteristics of LNG',
          version: '1',
          system: 'Mechanical',
          documentType: 'Technical Standard',
          status: 'final-approved',
          uploadedBy: 'admin',
          uploadedAt: '2026-04-04T00:00:00Z',
          totalPages: 30,
          totalSections: 12,
          reviewProgress: 100,
          qaScore: 100,
        },
      ])
    );

    const docs = await getDocuments();

    expect(docs).toHaveLength(1);
    expect(docs[0].totalPages).toBe(30);
    expect(docs[0].totalSections).toBe(12);
    expect(docs[0].documentType).toBe('Technical Standard');
  });

  it('supports direct PostgREST fetch prefer headers', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    await postgrestFetch('/bookmarks', { prefer: 'return=representation' });

    const [, options] = fetchMock.mock.calls[0];
    expect((options.headers as Record<string, string>).Prefer).toBe('return=representation');
  });

  // ============================================================================
  // Ingestion SSE contract tests
  // ============================================================================

  it('collects ingestion progress events from SSE stream', async () => {
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: job.accepted\ndata: {"event":"job.accepted","document_id":"doc-xyz","job_id":"job-1","stage":"queued","progress":0,"message":"Job accepted"}\n\n',
        'event: progress\ndata: {"event":"progress","document_id":"doc-xyz","job_id":"job-1","stage":"extraction","progress":30,"message":"Extracting"}\n\n',
        'event: stage.complete\ndata: {"event":"stage.complete","document_id":"doc-xyz","job_id":"job-1","stage":"extraction","progress":30,"message":"Extraction done"}\n\n',
        'event: complete\ndata: {"event":"complete","document_id":"doc-xyz","job_id":"job-1","stage":"completed","progress":100,"message":"Done"}\n\n',
      ])
    );

    const events = [];
    for await (const event of streamIngestionEvents('doc-xyz')) {
      events.push(event);
    }

    const types = events.map((e) => e.type);
    expect(types).toEqual(['job.accepted', 'progress', 'stage.complete', 'complete']);

    // Verify stream terminated after complete.
    expect(events[events.length - 1].type).toBe('complete');
    expect(events[3].progress).toBe(100);
  });

  it('terminates ingestion stream on error event', async () => {
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: progress\ndata: {"event":"progress","document_id":"doc-xyz","job_id":"job-1","stage":"extraction","progress":20,"message":"Extracting"}\n\n',
        'event: error\ndata: {"event":"error","document_id":"doc-xyz","job_id":"job-1","stage":"extraction","progress":20,"message":"Failed","error":"Subprocess exited with code 1"}\n\n',
        // Should NOT be yielded after error.
        'event: progress\ndata: {"event":"progress","document_id":"doc-xyz","job_id":"job-1","stage":"validation","progress":50,"message":"Validating"}\n\n',
      ])
    );

    const events = [];
    for await (const event of streamIngestionEvents('doc-xyz')) {
      events.push(event);
    }

    const types = events.map((e) => e.type);
    expect(types).toContain('progress');
    expect(types).toContain('error');
    // No event after the error.
    expect(types[types.length - 1]).toBe('error');
    expect(types).not.toContain('validation');
  });

  it('yields a connection error event when ingestion SSE request fails', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(null, { status: 503, statusText: 'Service Unavailable' })
    );

    const events = [];
    for await (const event of streamIngestionEvents('doc-fail')) {
      events.push(event);
    }

    expect(events).toHaveLength(1);
    expect(events[0].type).toBe('error');
    if (events[0].type === 'error') {
      expect(events[0].error).toContain('Service Unavailable');
    }
  });

  it('passes auth token in ingestion SSE request header', async () => {
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: complete\ndata: {"event":"complete","document_id":"doc-auth","job_id":"job-1","stage":"completed","progress":100,"message":"Done"}\n\n',
      ])
    );

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    for await (const _ of streamIngestionEvents('doc-auth')) {
      break;
    }

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/documents/doc-auth/events/');
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer test-token');
  });

  it('parses ingestion SSE events delimited with CRLF separators', async () => {
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: progress\r\ndata: {"event":"progress","document_id":"doc-crlf","job_id":"job-1","stage":"extraction","progress":33,"message":"Extracting"}\r\n\r\n',
        'event: complete\r\ndata: {"event":"complete","document_id":"doc-crlf","job_id":"job-1","stage":"completed","progress":100,"message":"Done"}\r\n\r\n',
      ])
    );

    const events = [];
    for await (const event of streamIngestionEvents('doc-crlf')) {
      events.push(event);
    }

    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ type: 'progress', progress: 33, stage: 'extraction' });
    expect(events[1]).toMatchObject({ type: 'complete', progress: 100, stage: 'completed' });
  });

  it('parses ingestion SSE blocks split across chunk boundaries', async () => {
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: progress\ndata: {"event":"progress","document_id":"doc-split","job_id":"job-1","stage":"extraction","progress":4',
        '0,"message":"Extracting"}\n\nevent: complete\ndata: {"event":"complete","document_id":"doc-split","job_id":"job-1","stage":"completed","progress":100,"message":"Done"}\n\n',
      ])
    );

    const events = [];
    for await (const event of streamIngestionEvents('doc-split')) {
      events.push(event);
    }

    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ type: 'progress', progress: 40, stage: 'extraction' });
    expect(events[1]).toMatchObject({ type: 'complete', progress: 100, stage: 'completed' });
  });

  it('parses ingestion SSE ping heartbeat events', async () => {
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: ping\ndata: {"event":"ping","document_id":"doc-ping","stage":"monitoring","progress":56,"message":"Waiting for runner output..."}\n\n',
        'event: complete\ndata: {"event":"complete","document_id":"doc-ping","job_id":"job-1","stage":"completed","progress":100,"message":"Done"}\n\n',
      ])
    );

    const events = [];
    for await (const event of streamIngestionEvents('doc-ping')) {
      events.push(event);
    }

    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ type: 'ping', stage: 'heartbeat', progress: 56 });
    expect(events[1]).toMatchObject({ type: 'complete', progress: 100 });
  });

  it('treats optimization stream aborts during reader.read as normal shutdown', async () => {
    const releaseLock = vi.fn();
    const read = vi.fn().mockRejectedValue(new DOMException('BodyStreamBuffer was aborted', 'AbortError'));

    fetchMock.mockResolvedValueOnce({
      ok: true,
      body: {
        getReader: () => ({
          read,
          releaseLock,
        }),
      },
    } as unknown as Response);

    const events = [];
    for await (const event of streamOptimizationLogs('doc-opt')) {
      events.push(event);
    }

    expect(events).toEqual([]);
    expect(read).toHaveBeenCalledTimes(1);
    expect(releaseLock).toHaveBeenCalledTimes(1);
  });

  it('parses optimization SSE events delimited with CRLF separators', async () => {
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        'event: log\r\ndata: {"event":"log","timestamp":"2026-04-21T00:00:00Z","level":"INFO","message":"Starting"}\r\n\r\n',
        'event: done\r\ndata: {"event":"done","status":"optimization-complete"}\r\n\r\n',
      ])
    );

    const events = [];
    for await (const event of streamOptimizationLogs('doc-opt-crlf')) {
      events.push(event);
    }

    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ type: 'log', level: 'INFO', message: 'Starting' });
    expect(events[1]).toMatchObject({ type: 'done', status: 'optimization-complete' });
  });

  // -------------------------------------------------------------------------
  // isQAReadyStatus — used by the optimizing page to detect already-completed
  // documents and immediately show the completion state without waiting for SSE
  // -------------------------------------------------------------------------

  it('isQAReadyStatus returns true for optimization-complete and all downstream statuses', () => {
    expect(isQAReadyStatus('optimization-complete')).toBe(true);
    expect(isQAReadyStatus('qa-review')).toBe(true);
    expect(isQAReadyStatus('qa-passed')).toBe(true);
    expect(isQAReadyStatus('final-approved')).toBe(true);
    expect(isQAReadyStatus('approved')).toBe(true);
  });

  it('isQAReadyStatus returns false for statuses that precede optimization completion', () => {
    expect(isQAReadyStatus('approved-for-optimization')).toBe(false);
    expect(isQAReadyStatus('optimizing')).toBe(false);
    expect(isQAReadyStatus('failed')).toBe(false);
    expect(isQAReadyStatus('in-review')).toBe(false);
    expect(isQAReadyStatus('validation-complete')).toBe(false);
  });

  it('getPipelineStatus returns the raw status for an already-complete document', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        document_id: 'b549bbfc-f9bd-48be-aac0-bdeb165de5f2',
        status: 'optimization-complete',
        progress: 100,
        started_at: '2026-03-26T00:00:00Z',
        completed_at: '2026-03-26T01:00:00Z',
      })
    );

    const result = await getPipelineStatus('b549bbfc-f9bd-48be-aac0-bdeb165de5f2');

    expect(result.status).toBe('optimization-complete');
    expect(isQAReadyStatus(result.status)).toBe(true);
  });

  it('getPipelineStatus downstream statuses are also detected as QA-ready', async () => {
    for (const status of ['qa-review', 'qa-passed', 'final-approved'] as const) {
      fetchMock.mockResolvedValueOnce(
        jsonResponse({
          document_id: 'doc-downstream',
          status,
          progress: 100,
        })
      );

      const result = await getPipelineStatus('doc-downstream');
      expect(isQAReadyStatus(result.status)).toBe(true);
    }
  });

  // ============================================================================
  // Optimized Review API helpers
  // ============================================================================

  it('getDocumentOptimizedChunks fetches the optimized-chunks endpoint with auth', async () => {
    const mockResponse = {
      document_name: 'LNG Operations Manual',
      review_unit: 'optimized_chunk',
      chunks: [
        {
          id: 'chunk-001',
          chunk_number: 1,
          heading: 'Safety Protocols',
          markdown_content: '## Safety Protocols\n\nContent here.',
          text_preview: 'Safety Protocols content...',
          source_pages: [1, 2],
          table_facts: ['Table 1: Pressure limits'],
          ambiguity_flags: [],
        },
      ],
    };

    fetchMock.mockResolvedValueOnce(jsonResponse(mockResponse));

    const result = await getDocumentOptimizedChunks('doc-abc');

    expect(result.document_name).toBe('LNG Operations Manual');
    expect(result.review_unit).toBe('optimized_chunk');
    expect(result.chunks).toHaveLength(1);
    expect(result.chunks[0].id).toBe('chunk-001');
    expect(result.chunks[0].heading).toBe('Safety Protocols');
    expect(result.chunks[0].source_pages).toEqual([1, 2]);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/documents/doc-abc/optimized-chunks');
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer test-token');
  });

  it('updateOptimizedChunk sends a PATCH with the correct payload and returns chunk_id + status', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ chunk_id: 'chunk-001', status: 'saved' }));

    const payload = {
      heading: 'Updated Safety Protocols',
      markdown_content: '## Updated Safety Protocols\n\nNew content.',
      table_facts: ['Table 1: Updated pressure limits'],
      ambiguity_flags: ['Figure 3 description unclear'],
    };

    const result = await updateOptimizedChunk('doc-abc', 'chunk-001', payload);

    expect(result.chunk_id).toBe('chunk-001');
    expect(result.status).toBe('saved');

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/documents/doc-abc/optimized-chunks/chunk-001');
    expect(options.method).toBe('PATCH');
    expect((options.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer test-token');

    const body = JSON.parse(options.body as string);
    expect(body.heading).toBe('Updated Safety Protocols');
    expect(body.markdown_content).toBe('## Updated Safety Protocols\n\nNew content.');
    expect(body.table_facts).toEqual(['Table 1: Updated pressure limits']);
    expect(body.ambiguity_flags).toEqual(['Figure 3 description unclear']);
  });

  it('getDocumentOptimizedChunks returns empty chunks array on backend error', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Not found' }), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      })
    );

    await expect(getDocumentOptimizedChunks('doc-missing')).rejects.toThrow();
  });

  // ============================================================================
  // Routing helpers: canOpenOptimizedReview
  // ============================================================================

  it('canOpenOptimizedReview returns true for optimization-complete and qa-review', () => {
    expect(canOpenOptimizedReview('optimization-complete')).toBe(true);
    expect(canOpenOptimizedReview('qa-review')).toBe(true);
  });

  it('canOpenOptimizedReview returns false for finalized and pre-optimization statuses', () => {
    expect(canOpenOptimizedReview('qa-passed')).toBe(false);
    expect(canOpenOptimizedReview('final-approved')).toBe(false);
    expect(canOpenOptimizedReview('approved')).toBe(false);
    expect(canOpenOptimizedReview('optimizing')).toBe(false);
    expect(canOpenOptimizedReview('in-review')).toBe(false);
    expect(canOpenOptimizedReview('failed')).toBe(false);
  });

  // ============================================================================
  // Navigation contract: optimization-complete routes to optimized-review
  // ============================================================================

  it('optimization-complete is a QA-ready status and maps to the optimized-review route', () => {
    // When the optimizing page detects this status, it should:
    // 1. treat the document as complete (isQAReadyStatus → true)
    // 2. allow the user to open the optimized-review editor (canOpenOptimizedReview → true)
    const status = 'optimization-complete' as const;
    expect(isQAReadyStatus(status)).toBe(true);
    expect(canOpenOptimizedReview(status)).toBe(true);
  });

  it('qa-review status allows reopening optimized-review for remediation edits', () => {
    const status = 'qa-review' as const;
    expect(isQAReadyStatus(status)).toBe(true);
    expect(canOpenOptimizedReview(status)).toBe(true);
  });
});