import type {
  DirectoryConfigResponse,
  DirectoryConfigUpsertRequest,
  DirectoryVerifyCertMode,
} from '@/lib/api/users';

export interface DirectoryConfigFormValues {
  connectionTarget: string;
  baseDn: string;
  userSearchBase: string;
  bindDn: string;
}

export interface DirectoryConfigHiddenValues {
  host: string;
  serverUrl: string;
  port: number;
  useSsl: boolean;
  startTls: boolean;
  verifyCertMode: DirectoryVerifyCertMode;
  searchFilterTemplate: string;
}

export type DirectoryConfigFormErrors = Partial<Record<keyof DirectoryConfigFormValues, string>>;

const DEFAULT_SEARCH_FILTER_TEMPLATE = '(&(objectClass=person)(uid={username}))';

export function getDefaultDirectoryConfigHiddenValues(): DirectoryConfigHiddenValues {
  return {
    host: '',
    serverUrl: '',
    port: 389,
    useSsl: false,
    startTls: false,
    verifyCertMode: 'required',
    searchFilterTemplate: DEFAULT_SEARCH_FILTER_TEMPLATE,
  };
}

export function mapConfigToFormValues(config: DirectoryConfigResponse): {
  formValues: DirectoryConfigFormValues;
  hiddenValues: DirectoryConfigHiddenValues;
} {
  const serverUrl = config.server_url ?? '';
  const host = config.host ?? '';
  const connectionTarget = serverUrl || host;

  const hiddenValues: DirectoryConfigHiddenValues = {
    host,
    serverUrl,
    port: Number.isFinite(config.port) ? Number(config.port) : 389,
    useSsl: Boolean(config.use_ssl),
    startTls: Boolean(config.start_tls),
    verifyCertMode: config.verify_cert_mode ?? 'required',
    searchFilterTemplate: config.search_filter_template ?? DEFAULT_SEARCH_FILTER_TEMPLATE,
  };

  return {
    formValues: {
      connectionTarget,
      baseDn: config.base_dn ?? '',
      userSearchBase: config.user_search_base ?? '',
      bindDn: config.bind_dn ?? '',
    },
    hiddenValues,
  };
}

function parseConnectionTarget(connectionTarget: string): {
  host: string;
  serverUrl: string;
  port: number | null;
} {
  const trimmed = connectionTarget.trim();
  if (!trimmed) {
    return { host: '', serverUrl: '', port: null };
  }

  if (trimmed.includes('://')) {
    try {
      const parsed = new URL(trimmed);
      const parsedPort = parsed.port ? Number(parsed.port) : null;
      const hasValidPort = parsedPort !== null && Number.isInteger(parsedPort) && parsedPort > 0 && parsedPort <= 65535;
      return {
        host: parsed.hostname || '',
        serverUrl: trimmed,
        port: hasValidPort ? parsedPort : null,
      };
    } catch {
      return {
        host: '',
        serverUrl: trimmed,
        port: null,
      };
    }
  }

  return {
    host: trimmed,
    serverUrl: '',
    port: null,
  };
}

export function validateDirectoryConfigForm(values: DirectoryConfigFormValues): DirectoryConfigFormErrors {
  const errors: DirectoryConfigFormErrors = {};

  if (!values.connectionTarget.trim()) {
    errors.connectionTarget = 'Server URL or host is required.';
  }

  if (!values.baseDn.trim()) {
    errors.baseDn = 'Base DN is required.';
  }

  if (!values.userSearchBase.trim()) {
    errors.userSearchBase = 'User Search Base is required.';
  }

  if (!values.bindDn.trim()) {
    errors.bindDn = 'Bind DN is required.';
  }

  return errors;
}

export function buildDirectoryConfigUpsertPayload(
  values: DirectoryConfigFormValues,
  hiddenValues: DirectoryConfigHiddenValues,
  bindPassword?: string,
): DirectoryConfigUpsertRequest {
  const parsedTarget = parseConnectionTarget(values.connectionTarget);
  const nextHost = parsedTarget.host || hiddenValues.host;
  const nextServerUrl = parsedTarget.serverUrl;
  const nextPort = parsedTarget.port ?? hiddenValues.port;

  const payload: DirectoryConfigUpsertRequest = {
    base_dn: values.baseDn.trim(),
    user_search_base: values.userSearchBase.trim(),
    bind_dn: values.bindDn.trim(),
    use_ssl: hiddenValues.useSsl,
    start_tls: hiddenValues.startTls,
    verify_cert_mode: hiddenValues.verifyCertMode,
    search_filter_template: hiddenValues.searchFilterTemplate.trim() || DEFAULT_SEARCH_FILTER_TEMPLATE,
  };

  if (nextHost) {
    payload.host = nextHost;
  }

  if (nextServerUrl) {
    payload.server_url = nextServerUrl;
  }

  payload.port = nextPort;

  if (bindPassword && bindPassword.trim().length > 0) {
    payload.bind_password = bindPassword;
  }

  return payload;
}
