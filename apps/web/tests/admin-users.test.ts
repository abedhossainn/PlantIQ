/**
 * Admin Users API — unit tests for LDAP-only user management policy
 *
 * Covers:
 * - getAdminUsers calls GET /api/v1/auth/admin/users
 * - getAdminUsers maps pagination params to query string
 * - getAdminUsers throws ApiError on non-OK response
 * - patchUserRole calls PATCH /api/v1/auth/admin/users/{id}/role
 * - patchUserRole throws ApiError on 403 (self-escalation guard)
 * - patchUserRole throws ApiError on 404 (user not found)
 * - createAdminUser is NOT exported from the API module (endpoint removed)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getAdminUsers, getDirectoryDomainLabel, patchUserRole } from '../lib/api/users';
import { ApiError } from '../lib/api/client';
import * as apiModule from '../lib/api';
import { readFileSync } from 'node:fs';

const adminUsersPageSource = readFileSync(
  new URL('../app/admin/users/page.tsx', import.meta.url),
  'utf8',
);

// ── helpers ────────────────────────────────────────────────────────────────

function makeUserItem(overrides: Partial<{
  id: string; username: string; email: string; full_name: string;
  role: string; department: string | null; status: string;
}> = {}) {
  return {
    id: 'user-1',
    username: 'jdoe',
    email: 'jdoe@example.com',
    full_name: 'Jane Doe',
    role: 'user',
    department: 'Operations',
    status: 'active',
    ...overrides,
  };
}

function makeListResponse(items = [makeUserItem()]) {
  return { items, total: items.length, page: 1, page_size: 100 };
}

// ── global fetch mock ──────────────────────────────────────────────────────

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
  // Silence NEXT_PUBLIC_API_URL for deterministic base URL
  vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://localhost:8000');
  vi.stubEnv('NEXT_PUBLIC_FASTAPI_URL', '');
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function mockFetch(status: number, body: unknown) {
  const json = vi.fn().mockResolvedValue(body);
  (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : String(status),
    headers: { get: () => 'application/json' },
    json,
  });
}

// ── getAdminUsers ──────────────────────────────────────────────────────────

describe('getAdminUsers', () => {
  it('calls GET /api/v1/auth/admin/users with default pagination', async () => {
    const payload = makeListResponse();
    mockFetch(200, payload);

    const result = await getAdminUsers();

    expect(fetch).toHaveBeenCalledOnce();
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/auth/admin/users');
    expect(url).toContain('page=1');
    expect(url).toContain('page_size=100');
    expect(init?.method ?? 'GET').toBe('GET');
    expect(result).toEqual(payload);
  });

  it('forwards custom page / pageSize as query params', async () => {
    mockFetch(200, makeListResponse());

    await getAdminUsers(3, 25);

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain('page=3');
    expect(url).toContain('page_size=25');
  });

  it('returns the items array from the response', async () => {
    const items = [makeUserItem({ id: 'a' }), makeUserItem({ id: 'b', role: 'admin' })];
    mockFetch(200, makeListResponse(items));

    const result = await getAdminUsers();

    expect(result.items).toHaveLength(2);
    expect(result.items[0].id).toBe('a');
    expect(result.items[1].role).toBe('admin');
  });

  it('throws ApiError on non-OK response', async () => {
    mockFetch(401, { detail: 'Not authenticated' });

    await expect(getAdminUsers()).rejects.toBeInstanceOf(ApiError);
  });

  it('throws ApiError with correct status code on failure', async () => {
    mockFetch(403, { detail: 'Forbidden' });

    const err = await getAdminUsers().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(403);
  });
});

// ── patchUserRole ──────────────────────────────────────────────────────────

describe('patchUserRole', () => {
  it('calls PATCH /api/v1/auth/admin/users/{id}/role', async () => {
    const updated = makeUserItem({ role: 'admin' });
    mockFetch(200, updated);

    await patchUserRole('user-1', 'admin');

    expect(fetch).toHaveBeenCalledOnce();
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/auth/admin/users/user-1/role');
    expect((init as RequestInit).method).toBe('PATCH');
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ role: 'admin' });
  });

  it('URL-encodes the user ID', async () => {
    mockFetch(200, makeUserItem());

    await patchUserRole('user/special+chars', 'user');

    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).not.toContain('user/special+chars');
    expect(url).toContain(encodeURIComponent('user/special+chars'));
  });

  it('returns the updated user record', async () => {
    const updated = makeUserItem({ role: 'admin' });
    mockFetch(200, updated);

    const result = await patchUserRole('user-1', 'admin');
    expect(result.role).toBe('admin');
  });

  it('throws ApiError with status 403 on self-escalation guard', async () => {
    mockFetch(403, { detail: 'Cannot update own role' });

    const err = await patchUserRole('own-id', 'admin').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(403);
  });

  it('throws ApiError with status 404 when user has no local profile', async () => {
    mockFetch(404, { detail: 'User not found' });

    const err = await patchUserRole('ghost-id', 'user').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
  });
});

// ── LDAP policy: createAdminUser must not be exported ─────────────────────

describe('LDAP policy — createAdminUser removed', () => {
  it('createAdminUser is not exported from the API module', () => {
    // The endpoint returns 410 Gone; the function must not exist in the
    // public API surface so callers cannot accidentally use it.
    expect((apiModule as Record<string, unknown>).createAdminUser).toBeUndefined();
  });

  it('AdminCreateUserRequest type is not exported from the API module', () => {
    // Types are erased at runtime; this is a belt-and-suspenders check that
    // no runtime stub was left behind.
    expect((apiModule as Record<string, unknown>).AdminCreateUserRequest).toBeUndefined();
  });
});

describe('getDirectoryDomainLabel', () => {
  it('prefers server_url host when available', () => {
    expect(
      getDirectoryDomainLabel({
        server_url: 'ldaps://ldap.example.com:636',
        host: 'fallback.local',
        base_dn: 'dc=plantiq,dc=local',
      })
    ).toBe('ldap.example.com');
  });

  it('prefers base_dn domain over single-label server_url hostname', () => {
    expect(
      getDirectoryDomainLabel({
        server_url: 'ldap://ldap:1389',
        host: '',
        base_dn: 'dc=plantiq,dc=local',
      }),
    ).toBe('plantiq.local');
  });

  it('falls back to host when server_url is missing', () => {
    expect(
      getDirectoryDomainLabel({
        server_url: null,
        host: 'ldap.internal.local',
        base_dn: 'dc=plantiq,dc=local',
      })
    ).toBe('ldap.internal.local');
  });

  it('prefers base_dn-derived domain over a single-label host', () => {
    expect(
      getDirectoryDomainLabel({
        server_url: null,
        host: 'ldap',
        base_dn: 'dc=plantiq,dc=local',
      })
    ).toBe('plantiq.local');
  });

  it('uses single-label host as-is when base_dn cannot provide a domain', () => {
    expect(
      getDirectoryDomainLabel({
        server_url: null,
        host: 'ldap',
        base_dn: 'ou=users,ou=engineering',
      })
    ).toBe('ldap');
  });

  it('uses multi-label host even when base_dn is also available', () => {
    expect(
      getDirectoryDomainLabel({
        server_url: null,
        host: 'ldap.corp',
        base_dn: 'dc=plantiq,dc=local',
      })
    ).toBe('ldap.corp');
  });

  it('derives domain from base_dn when server_url and host are unavailable', () => {
    expect(
      getDirectoryDomainLabel({
        server_url: null,
        host: '',
        base_dn: 'ou=users,dc=plantiq,dc=local',
      })
    ).toBe('plantiq.local');
  });

  it('returns null when domain cannot be derived', () => {
    expect(
      getDirectoryDomainLabel({
        server_url: null,
        host: '',
        base_dn: 'ou=users,ou=engineering',
      })
    ).toBeNull();
  });
});

describe('admin users page domain display', () => {
  it('shows a connected domain header badge with the green active-profile styling', () => {
    expect(adminUsersPageSource).toContain('Connected domain:');
    expect(adminUsersPageSource).toContain('Domain not connected');
    expect(adminUsersPageSource).toContain('variant="outline"');
    expect(adminUsersPageSource).toContain('border-green-400/30 bg-green-400/10 text-green-300');
    expect(adminUsersPageSource).toContain('shrink-0 whitespace-nowrap');
    expect(adminUsersPageSource).toContain('{directoryDomain ? `Connected domain: ${directoryDomain}` : "Domain not connected"}');
  });

  it('loads directory config to resolve the connected domain label', () => {
    expect(adminUsersPageSource).toContain('await getAdminDirectoryConfig()');
    expect(adminUsersPageSource).toContain('setDirectoryDomain(getDirectoryDomainLabel(config))');
  });

  it('does not render the connected domain as plain subtitle text in the left header block', () => {
    expect(adminUsersPageSource).not.toContain('Connected domain: <span className="font-medium text-foreground">');
  });
});
