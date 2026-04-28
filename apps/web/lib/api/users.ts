/**
 * Admin user management API
 *
 * GET   /api/v1/auth/admin/users              — list LDAP-backed users (admin only)
 * PATCH /api/v1/auth/admin/users/{id}/role    — update user role (admin only)
 * PATCH /api/v1/auth/admin/users/{id}/status  — enable/disable user (admin only)
 * POST  /api/v1/auth/admin/users/sync         — bulk-provision LDAP users (admin only)
 *
 * POST /api/v1/auth/admin/users is removed (410 Gone).
 * User creation is managed exclusively through LDAP.
 */

import { ApiError, fastapiFetch } from './client';

export interface AdminUserResponse {
  id: string;
  username: string;
  email: string;
  full_name: string;
  role: string;
  department: string | null;
  status: string;
}

export interface AdminUsersListResponse {
  items: AdminUserResponse[];
  total: number;
  page: number;
  page_size: number;
}

export type DirectoryVerifyCertMode = 'required' | 'optional' | 'none';

export interface DirectoryConfigResponse {
  id: string;
  host: string;
  server_url: string | null;
  port: number;
  base_dn: string;
  user_search_base: string;
  bind_dn: string;
  has_bind_password: boolean;
  use_ssl: boolean;
  start_tls: boolean;
  verify_cert_mode: DirectoryVerifyCertMode;
  search_filter_template: string;
  is_active: boolean;
  updated_by: string | null;
  updated_at: string;
  created_at: string;
}

export interface DirectoryConfigUpsertRequest {
  host?: string;
  server_url?: string;
  port?: number;
  base_dn: string;
  user_search_base: string;
  bind_dn: string;
  bind_password?: string;
  use_ssl: boolean;
  start_tls: boolean;
  verify_cert_mode: DirectoryVerifyCertMode;
  search_filter_template: string;
}

export interface DirectoryConfigTestRequest {
  config?: DirectoryConfigUpsertRequest;
}

export interface DirectoryConfigTestResponse {
  success: boolean;
  message: string;
  source: 'supplied' | 'db' | 'env';
}

function extractHostFromServerUrl(serverUrl: string | null | undefined): string | null {
  if (!serverUrl) {
    return null;
  }

  try {
    const hostname = new URL(serverUrl).hostname.trim();
    return hostname || null;
  } catch {
    const match = serverUrl.match(/^[a-z]+:\/\/([^/:?#]+)/i);
    const host = match?.[1]?.trim();
    return host || null;
  }
}

function deriveDomainFromBaseDn(baseDn: string): string | null {
  const dcParts = baseDn
    .split(',')
    .map((segment) => segment.trim())
    .filter((segment) => segment.toLowerCase().startsWith('dc='))
    .map((segment) => segment.slice(3).trim())
    .filter(Boolean);

  if (dcParts.length === 0) {
    return null;
  }

  return dcParts.join('.');
}

export function getDirectoryDomainLabel(
  config: Pick<DirectoryConfigResponse, 'server_url' | 'host' | 'base_dn'> | null | undefined,
): string | null {
  if (!config) {
    return null;
  }

  const baseDnDomain = deriveDomainFromBaseDn(config.base_dn);

  const serverHost = extractHostFromServerUrl(config.server_url);
  if (serverHost) {
    // If single-label (e.g. Docker service name "ldap"), prefer fuller base_dn domain if available
    if (!serverHost.includes('.') && baseDnDomain) {
      return baseDnDomain;
    }
    return serverHost;
  }

  const host = config.host?.trim();
  if (host) {
    const isSingleLabel = !host.includes('.');
    if (isSingleLabel && baseDnDomain) {
      return baseDnDomain;
    }
    return host;
  }

  return baseDnDomain;
}

interface ApiDetailMessage {
  code?: string;
  message?: string;
}

function parseApiDetailMessage(data: unknown): ApiDetailMessage | null {
  if (!data || typeof data !== 'object') {
    return null;
  }

  const payload = data as Record<string, unknown>;
  const detail = payload.detail;
  if (detail && typeof detail === 'object') {
    const detailRecord = detail as Record<string, unknown>;
    return {
      code: typeof detailRecord.code === 'string' ? detailRecord.code : undefined,
      message: typeof detailRecord.message === 'string' ? detailRecord.message : undefined,
    };
  }

  return {
    code: typeof payload.code === 'string' ? payload.code : undefined,
    message: typeof payload.message === 'string' ? payload.message : undefined,
  };
}

function normalizeApiError(error: unknown, fallbackMessage: string): ApiError {
  if (error instanceof ApiError) {
    const detail = parseApiDetailMessage(error.data);
    if (detail?.message) {
      return new ApiError(detail.message, error.status, {
        ...(typeof error.data === 'object' && error.data ? error.data as Record<string, unknown> : {}),
        code: detail.code,
      });
    }
    return error;
  }

  return new ApiError(
    error instanceof Error ? error.message : fallbackMessage,
    0,
  );
}

export async function getAdminUsers(
  page = 1,
  pageSize = 100,
): Promise<AdminUsersListResponse> {
  return fastapiFetch<AdminUsersListResponse>(
    `/api/v1/auth/admin/users?page=${page}&page_size=${pageSize}`,
  );
}

export async function patchUserRole(
  userId: string,
  role: string,
): Promise<AdminUserResponse> {
  return fastapiFetch<AdminUserResponse>(
    `/api/v1/auth/admin/users/${encodeURIComponent(userId)}/role`,
    { method: 'PATCH', body: JSON.stringify({ role }) },
  );
}

export async function patchUserStatus(
  userId: string,
  status: 'active' | 'disabled',
): Promise<AdminUserResponse> {
  return fastapiFetch<AdminUserResponse>(
    `/api/v1/auth/admin/users/${encodeURIComponent(userId)}/status`,
    { method: 'PATCH', body: JSON.stringify({ status }) },
  );
}

export async function getAdminDirectoryConfig(): Promise<DirectoryConfigResponse> {
  try {
    return await fastapiFetch<DirectoryConfigResponse>('/api/v1/auth/admin/directory-config');
  } catch (error) {
    throw normalizeApiError(error, 'Failed to load directory settings.');
  }
}

export async function upsertAdminDirectoryConfig(
  payload: DirectoryConfigUpsertRequest,
): Promise<DirectoryConfigResponse> {
  try {
    return await fastapiFetch<DirectoryConfigResponse>('/api/v1/auth/admin/directory-config', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  } catch (error) {
    throw normalizeApiError(error, 'Failed to save directory settings.');
  }
}

export async function testAdminDirectoryConfig(
  payload: DirectoryConfigTestRequest,
): Promise<DirectoryConfigTestResponse> {
  try {
    return await fastapiFetch<DirectoryConfigTestResponse>('/api/v1/auth/admin/directory-config/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  } catch (error) {
    throw normalizeApiError(error, 'Directory connection test failed.');
  }
}

export async function activateAdminDirectoryConfig(): Promise<DirectoryConfigResponse> {
  try {
    return await fastapiFetch<DirectoryConfigResponse>('/api/v1/auth/admin/directory-config/activate', {
      method: 'POST',
      body: JSON.stringify({}),
    });
  } catch (error) {
    throw normalizeApiError(error, 'Failed to activate directory settings.');
  }
}
