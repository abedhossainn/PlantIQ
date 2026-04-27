/**
 * Admin user management API
 *
 * GET   /api/v1/auth/admin/users              — list LDAP-backed users (admin only)
 * PATCH /api/v1/auth/admin/users/{id}/role    — update user role (admin only)
 *
 * POST /api/v1/auth/admin/users is removed (410 Gone).
 * User creation is managed exclusively through LDAP.
 */

import { ApiError, getFastApiBaseUrl, getAuthToken } from './client';

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

export async function getAdminUsers(
  page = 1,
  pageSize = 100,
): Promise<AdminUsersListResponse> {
  const base = getFastApiBaseUrl();
  const token = getAuthToken();

  const url = new URL(`${base}/api/v1/auth/admin/users`);
  url.searchParams.set('page', String(page));
  url.searchParams.set('page_size', String(pageSize));

  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  const contentType = response.headers.get('content-type');
  const data = contentType?.includes('application/json')
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    throw new ApiError(`API Error: ${response.statusText}`, response.status, data);
  }

  return data as AdminUsersListResponse;
}

export async function patchUserRole(
  userId: string,
  role: string,
): Promise<AdminUserResponse> {
  const base = getFastApiBaseUrl();
  const token = getAuthToken();

  const response = await fetch(
    `${base}/api/v1/auth/admin/users/${encodeURIComponent(userId)}/role`,
    {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ role }),
    },
  );

  const contentType = response.headers.get('content-type');
  const data = contentType?.includes('application/json')
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    throw new ApiError(`API Error: ${response.statusText}`, response.status, data);
  }

  return data as AdminUserResponse;
}
