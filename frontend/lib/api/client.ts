/**
 * Base API Client for PostgREST and FastAPI
 *
 * Architecture:
 * - Centralizes HTTP request handling for PostgREST and FastAPI.
 * - Manages JWT token retrieval and Authorization header injection.
 * - Normalizes API error handling via ApiError.
 * - Supports both JSON and multipart FormData payloads.
 */

const POSTGREST_URL = process.env.NEXT_PUBLIC_POSTGREST_URL || 'http://localhost:3001';

export function getFastApiBaseUrl(): string {
   // Resolve FastAPI server URL with fallback chain.
   // Priority: tunneled URL > explicit env var > localhost dev default.
  return (
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.NEXT_PUBLIC_FASTAPI_URL ||
    'http://localhost:8000'
  );
}

export function getFastApiWsBaseUrl(): string {
   // Convert http(s) → ws(s) for WebSocket upgrade.
   // Maintains hostname/port from getFastApiBaseUrl().
  return getFastApiBaseUrl().replace(/^http/, 'ws');
}

export class ApiError extends Error {
   // Custom error for API failures: captures status code + response body for client handlers.
  constructor(
    message: string,
    public status: number,
    public data?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Retrieve JWT token from localStorage.
 * Returns null if running in non-browser context (SSR) or localStorage unreachable.
 * Token is attached to all subsequent API requests via Authorization header.
 */
export function getAuthToken(): string | null {
  if (typeof globalThis === 'undefined' || !('localStorage' in globalThis)) {
    return null;
  }

  return globalThis.localStorage?.getItem('auth_token') ?? null;
}

/**
 * Base fetch wrapper with authentication and error handling
 */
async function apiFetch<T>(
  url: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getAuthToken();
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  
  const headers: Record<string, string> = {};

  if (!isFormData) {
    headers['Content-Type'] = 'application/json';
  }

  // Merge with options headers
  if (options.headers) {
    Object.entries(options.headers).forEach(([key, value]) => {
      if (value) headers[key] = String(value);
    });
  }

  if (isFormData && !options.headers) {
    delete headers['Content-Type'];
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers,
    });

    // Handle non-JSON responses
    const contentType = response.headers.get('content-type');
    const isJson = contentType?.includes('application/json');

    if (!response.ok) {
      const errorData = isJson ? await response.json() : await response.text();
      throw new ApiError(
        `API Error: ${response.statusText}`,
        response.status,
        errorData
      );
    }

    // Handle 204 No Content
    if (response.status === 204) {
      return undefined as T;
    }

    return isJson ? await response.json() : await response.text() as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(
      error instanceof Error ? error.message : 'Unknown error occurred',
      0
    );
  }
}

/**
 * PostgREST-specific fetch with Prefer headers
 */
export async function postgrestFetch<T>(
  path: string,
  options: RequestInit & {
    prefer?: 'return=representation' | 'return=minimal' | 'count=exact';
  } = {}
): Promise<T> {
  const { prefer, ...fetchOptions } = options;
  
  const headers: Record<string, string> = {};

  // Merge with fetch options headers
  if (fetchOptions.headers) {
    Object.entries(fetchOptions.headers).forEach(([key, value]) => {
      if (value) headers[key] = String(value);
    });
  }

  if (prefer) {
    headers['Prefer'] = prefer;
  }

  // Ensure path starts with /
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  
  return apiFetch<T>(`${POSTGREST_URL}${normalizedPath}`, {
    ...fetchOptions,
    headers,
  });
}

/**
 * FastAPI-specific fetch
 */
export async function fastapiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  // Ensure path starts with /
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  
  return apiFetch<T>(`${getFastApiBaseUrl()}${normalizedPath}`, options);
}

/**
 * Build query string from object
 */
export function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const queryParams = new URLSearchParams();
  
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) {
      queryParams.append(key, String(value));
    }
  });
  
  const queryString = queryParams.toString();
  return queryString ? `?${queryString}` : '';
}

/**
 * PostgREST query builder helper
 */
export class PostgRESTQuery<T> {
  private resource: string;
  private params: Record<string, string> = {};
  
  constructor(resource: string) {
    this.resource = resource;
  }
  
  select(columns: string): this {
    this.params.select = columns;
    return this;
  }
  
  eq(column: string, value: string | number | boolean): this {
    this.params[`${column}`] = `eq.${value}`;
    return this;
  }
  
  like(column: string, pattern: string): this {
    this.params[`${column}`] = `like.*${pattern}*`;
    return this;
  }
  
  gte(column: string, value: string | number): this {
    this.params[`${column}`] = `gte.${value}`;
    return this;
  }
  
  lte(column: string, value: string | number): this {
    this.params[`${column}`] = `lte.${value}`;
    return this;
  }
  
  order(column: string, direction: 'asc' | 'desc' = 'asc'): this {
    this.params.order = this.params.order
      ? `${this.params.order},${column}.${direction}`
      : `${column}.${direction}`;
    return this;
  }
  
  limit(count: number): this {
    this.params.limit = String(count);
    return this;
  }
  
  offset(count: number): this {
    this.params.offset = String(count);
    return this;
  }
  
  async execute(): Promise<T> {
    const query = buildQuery(this.params);
    return postgrestFetch<T>(`${this.resource}${query}`);
  }
  
  async single(): Promise<T extends Array<infer U> ? U : T> {
    const query = buildQuery(this.params);
    const result = await postgrestFetch<T>(`${this.resource}${query}`);
    
    if (Array.isArray(result) && result.length > 0) {
      return result[0] as T extends Array<infer U> ? U : T;
    }
    
    throw new ApiError('No results found', 404);
  }
}

/**
 * Create a PostgREST query builder
 */
export function from<T>(resource: string): PostgRESTQuery<T> {
  return new PostgRESTQuery<T>(resource);
}
