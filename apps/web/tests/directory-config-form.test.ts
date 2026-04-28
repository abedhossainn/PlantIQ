import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import {
  buildDirectoryConfigUpsertPayload,
  getDefaultDirectoryConfigHiddenValues,
  mapConfigToFormValues,
  validateDirectoryConfigForm,
} from '../app/admin/users/_helpers';

const directoryConfigPageSource = readFileSync(
  new URL('../app/admin/users/page.tsx', import.meta.url),
  'utf8',
);

describe('directory config form helpers', () => {
  it('maps API config into minimal form values and preserved hidden values', () => {
    const mapped = mapConfigToFormValues({
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
    });

    expect(mapped.formValues.connectionTarget).toBe('ldap://ldap.local:389');
    expect(mapped.formValues.baseDn).toBe('dc=plantiq,dc=local');
    expect(mapped.hiddenValues.host).toBe('ldap.local');
    expect(mapped.hiddenValues.port).toBe(389);
    expect(mapped.hiddenValues.searchFilterTemplate).toBe('(&(objectClass=person)(uid={username}))');
  });

  it('validates required minimal fields', () => {
    const errors = validateDirectoryConfigForm({
      connectionTarget: '',
      baseDn: '',
      userSearchBase: '',
      bindDn: '',
    });

    expect(errors.connectionTarget).toBeTruthy();
    expect(errors.baseDn).toBeTruthy();
    expect(errors.userSearchBase).toBeTruthy();
    expect(errors.bindDn).toBeTruthy();
  });

  it('builds payload using hidden defaults when hidden fields are absent', () => {
    const defaults = getDefaultDirectoryConfigHiddenValues();
    const payload = buildDirectoryConfigUpsertPayload(
      {
        connectionTarget: 'ldap.local',
        baseDn: 'dc=plantiq,dc=local',
        userSearchBase: 'ou=users,dc=plantiq,dc=local',
        bindDn: 'cn=admin,dc=plantiq,dc=local',
      },
      defaults,
      '',
    );

    expect(payload.bind_password).toBeUndefined();
    expect(payload.host).toBe('ldap.local');
    expect(payload.port).toBe(389);
    expect(payload.use_ssl).toBe(false);
    expect(payload.verify_cert_mode).toBe('required');
  });

  it('preserves hidden server settings when user edits only minimal fields', () => {
    const mapped = mapConfigToFormValues({
      id: 'cfg-3',
      host: 'ldap.active.local',
      server_url: null,
      port: 636,
      base_dn: 'dc=active,dc=local',
      user_search_base: 'ou=users,dc=active,dc=local',
      bind_dn: 'cn=svc,dc=active,dc=local',
      has_bind_password: true,
      use_ssl: true,
      start_tls: false,
      verify_cert_mode: 'optional',
      search_filter_template: '(&(objectClass=person)(uid={username}))',
      is_active: true,
      updated_by: null,
      updated_at: '2026-04-27T00:00:00Z',
      created_at: '2026-04-27T00:00:00Z',
    });

    const payload = buildDirectoryConfigUpsertPayload(
      {
        ...mapped.formValues,
        baseDn: 'dc=active,dc=local',
      },
      mapped.hiddenValues,
      'SecretPass!123',
    );

    expect(payload.bind_password).toBe('SecretPass!123');
    expect(payload.port).toBe(636);
    expect(payload.use_ssl).toBe(true);
    expect(payload.verify_cert_mode).toBe('optional');
  });

  it('treats URL input as primary connection target while preserving host compatibility', () => {
    const payload = buildDirectoryConfigUpsertPayload(
      {
        connectionTarget: 'ldaps://ldap.prod.local:636',
        baseDn: 'dc=prod,dc=local',
        userSearchBase: 'ou=users,dc=prod,dc=local',
        bindDn: 'cn=svc,dc=prod,dc=local',
      },
      getDefaultDirectoryConfigHiddenValues(),
    );

    expect(payload.server_url).toBe('ldaps://ldap.prod.local:636');
    expect(payload.host).toBe('ldap.prod.local');
    expect(payload.port).toBe(636);
  });

  it('uses merged Save/Update + Activate button copy and does not render a separate Activate button label', () => {
    expect(directoryConfigPageSource).toContain('Save & Activate');
    expect(directoryConfigPageSource).toContain('Update & Activate');
    expect(directoryConfigPageSource).not.toMatch(/>\s*Activate\s*<\/Button>/);
  });

  it('preserves save-then-activate sequencing and activate-failure status copy', () => {
    const saveCallIndex = directoryConfigPageSource.indexOf('await upsertAdminDirectoryConfig(payload)');
    const activateCallIndex = directoryConfigPageSource.indexOf('await activateAdminDirectoryConfig()');

    expect(saveCallIndex).toBeGreaterThanOrEqual(0);
    expect(activateCallIndex).toBeGreaterThanOrEqual(0);
    expect(saveCallIndex).toBeLessThan(activateCallIndex);
    expect(directoryConfigPageSource).toContain('Directory settings saved, but activation failed.');
  });
});
