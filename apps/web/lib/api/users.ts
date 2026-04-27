/**
 * Admin user management API
 *
 * GET   /api/v1/auth/admin/users              — list LDAP-backed users (admin only)
 * PATCH /api/v1/auth/admin/users/{id}/role    — update user role (admin only)
 *
 * POST /api/v1/auth/admin/users is removed (410 Gone).
 * User creation is managed exclusively through LDAP.
 */

import { ApiError, getFastApiBaseUrl, getAuthToken, fastapiFetch } from './client';

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
