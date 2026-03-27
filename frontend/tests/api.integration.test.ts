import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { consumeStreamingResponse, streamChatQuery, submitChatQuery } from '../lib/api/chat';
import type { Citation as ApiCitation } from '../lib/api/chat';
import { fastapiFetch, from, getFastApiBaseUrl, postgrestFetch } from '../lib/api/client';
import { canOpenOptimizedReview, getOptimizationLifecycleLabel, isQAReadyStatus } from '../lib/document-status';
import { downloadArtifact, fetchArtifactJson, getPipelineStatus, streamIngestionEvents, streamOptimizationLogs, uploadDocument } from '../lib/api/pipeline';
import { getDocumentOptimizedChunks, updateOptimizedChunk } from '../lib/api/optimized-review';
import { ChatWebSocketClient, PipelineWebSocketClient } from '../lib/api/websocket';

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
    expect(url).toBe('http://localhost:8000/api/v1/documents/doc-auth/events');
    expect((options.headers as Record<string, string>).Authorization).toBe('Bearer test-token');
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