/**
 * API client for CloakBrowser Manager backend.
 */

export type HostOS = "windows" | "macos" | "linux";
export type RuntimeMode = "native" | "docker";
export type ViewerMode = "native-window" | "vnc";
export type BrowserEngine = "auto" | "system_chrome" | "cloakbrowser";
export type LaunchMode = "manual" | "debug";

export interface Profile {
  id: string;
  name: string;
  browser_engine: BrowserEngine | string | null;
  device_profile: string | null;
  fingerprint_seed: number;
  proxy: string | null;
  timezone: string | null;
  locale: string | null;
  platform: string;
  user_agent: string | null;
  screen_width: number;
  screen_height: number;
  gpu_vendor: string | null;
  gpu_renderer: string | null;
  hardware_concurrency: number | null;
  device_memory: number | null;
  humanize: boolean;
  human_preset: string;
  headless: boolean;
  geoip: boolean;
  clipboard_sync: boolean;
  auto_launch: boolean;
  group_name: string | null;
  account_platform: string | null;
  cookies_json: string | null;
  startup_urls: string[];
  color_scheme: string | null;
  launch_args: string[];
  notes: string | null;
  user_data_dir: string;
  created_at: string;
  updated_at: string;
  last_opened_at: string | null;
  last_exit_at: string | null;
  last_exit_reason: string | null;
  deleted_at: string | null;
  tags: { tag: string; color: string | null }[];
  status: "running" | "stopped";
  runtime_mode: RuntimeMode;
  viewer_mode: ViewerMode;
  vnc_ws_port: number | null;
  cdp_url: string | null;
  launch_mode: LaunchMode | null;
  proxy_geo: ProxyTestResult | null;
}

export interface ProfileCreateData {
  name: string;
  browser_engine?: BrowserEngine | null;
  device_profile?: string | null;
  fingerprint_seed?: number | null;
  proxy?: string | null;
  timezone?: string | null;
  locale?: string | null;
  platform?: string;
  user_agent?: string | null;
  screen_width?: number;
  screen_height?: number;
  gpu_vendor?: string | null;
  gpu_renderer?: string | null;
  hardware_concurrency?: number | null;
  device_memory?: number | null;
  humanize?: boolean;
  human_preset?: string;
  headless?: boolean;
  geoip?: boolean;
  clipboard_sync?: boolean;
  auto_launch?: boolean;
  group_name?: string | null;
  account_platform?: string | null;
  cookies_json?: string | null;
  startup_urls?: string[];
  color_scheme?: string | null;
  launch_args?: string[];
  notes?: string | null;
  tags?: { tag: string; color: string | null }[];
}

export interface LaunchResult {
  profile_id: string;
  status: string;
  runtime_mode: RuntimeMode;
  viewer_mode: ViewerMode;
  vnc_ws_port: number | null;
  display: string | null;
  cdp_url: string | null;
  browser_engine: string | null;
  launch_mode: LaunchMode;
}

export interface SystemStatus {
  running_count: number;
  binary_version: string;
  profiles_total: number;
  host_os: HostOS;
  runtime_mode: RuntimeMode;
  viewer_mode: ViewerMode;
}

export interface ManagerUpdateResult {
  ok: boolean;
  updated: boolean;
  before: string | null;
  after: string | null;
  branch: string | null;
  restart_required: boolean;
  message: string;
  log: string[];
}

export interface BrowserUpdateResult {
  ok: boolean;
  updated: boolean;
  wrapper_version: string | null;
  current_version: string | null;
  available_version: string | null;
  installed_version: string | null;
  platform: string | null;
  binary_verified: boolean;
  restart_required: boolean;
  message: string;
}

export interface PreflightIssue {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
}

export interface PreflightResult {
  status: "pass" | "warning" | "fail";
  browser_engine: string;
  launch_mode: LaunchMode;
  can_launch: boolean;
  issues: PreflightIssue[];
  capabilities: Record<string, unknown>;
}

export interface ProxyTestResult {
  ok: boolean;
  ip: string | null;
  country: string | null;
  country_code: string | null;
  suggested_locale: string | null;
  region: string | null;
  city: string | null;
  timezone: string | null;
  org: string | null;
  asn: string | null;
  source: string;
}

export interface ProfileGroup {
  id: string;
  name: string;
  color: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProxyPreset {
  id: string;
  name: string;
  proxy: string;
  mode: string;
  created_at: string;
  updated_at: string;
}

export interface AuthStatus {
  auth_required: boolean;
  authenticated: boolean;
  username: string | null;
}

export interface FingerprintIssue {
  severity: "error" | "warning";
  signal: string;
  scope: string;
  expected: unknown;
  actual: unknown;
  message: string;
}

export interface FingerprintReport {
  profile_id: string;
  expected: {
    browser_engine: string | null;
    launch_mode: LaunchMode | null;
    external_cdp: boolean;
    locale: string | null;
    timezone: string | null;
    platform: string | null;
    screen_width: number | null;
    screen_height: number | null;
    hardware_concurrency: number | null;
    device_memory: number | null;
    gpu_vendor: string | null;
    gpu_renderer: string | null;
  };
  collection: "active" | "passive";
  proxy_geo: ProxyTestResult | null;
  network: {
    proxy_configured: boolean;
    dns_policy: string;
    webrtc_policy: string;
    tls_transport: string;
    tls_externally_verified: boolean;
    dns_externally_verified: boolean;
    external_probe_configured: boolean;
  };
  analysis: {
    status: "pass" | "warning" | "fail";
    score: number;
    error_count: number;
    warning_count: number;
    issues: FingerprintIssue[];
  };
  raw: Record<string, unknown>;
}

export interface ExternalNetworkProbe {
  observed_at?: string;
  egress?: {
    ip?: string | null;
    country?: string | null;
    region?: string | null;
    city?: string | null;
    timezone?: string | null;
    colo?: string | null;
  };
  transport?: {
    http_protocol?: string | null;
    tls_version?: string | null;
    tls_cipher?: string | null;
    tls_client_hello_length?: string | null;
  };
  headers?: {
    user_agent?: string | null;
    accept_language?: string | null;
    sec_ch_ua?: string | null;
    sec_ch_ua_platform?: string | null;
    sec_ch_ua_mobile?: string | null;
  };
  limitations?: {
    dns_resolver_externally_verified?: boolean;
    note?: string;
  };
  error?: string;
}

export interface ConfigurationImportResult {
  ok: boolean;
  profiles: number;
  groups: number;
  proxy_presets: number;
}

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// Global 401 callback — set by App to trigger login page on auth failure
let _onUnauthorized: (() => void) | null = null;
export function setOnUnauthorized(cb: (() => void) | null) {
  _onUnauthorized = cb;
}

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    if (res.status === 401 && _onUnauthorized) {
      _onUnauthorized();
      throw new ApiError(401, "未登录或访问令牌无效");
    }
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  authStatus: () =>
    request<AuthStatus>("/api/auth/status"),

  login: (username: string, password: string) =>
    request<{ ok: boolean; username: string | null }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  logout: () =>
    request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),

  getAuthAccount: () =>
    request<{ username: string | null }>("/api/auth/account"),

  updateAuthAccount: (data: {
    current_password: string;
    username?: string | null;
    new_password?: string | null;
  }) =>
    request<{ ok: boolean; username: string | null }>("/api/auth/account", {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  listProfiles: () => request<Profile[]>("/api/profiles"),

  listDeletedProfiles: () => request<Profile[]>("/api/profiles/trash"),

  getProfile: (id: string) => request<Profile>(`/api/profiles/${id}`),

  createProfile: (data: ProfileCreateData) =>
    request<Profile>("/api/profiles", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  updateProfile: (id: string, data: Partial<ProfileCreateData>) =>
    request<Profile>(`/api/profiles/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteProfile: (id: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}`, { method: "DELETE" }),

  restoreProfile: (id: string) =>
    request<Profile>(`/api/profiles/${id}/restore`, { method: "POST" }),

  purgeProfile: (id: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}/purge`, { method: "DELETE" }),

  listGroups: () => request<ProfileGroup[]>("/api/groups"),

  createGroup: (data: { name: string; color?: string | null }) =>
    request<ProfileGroup>("/api/groups", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  deleteGroup: (id: string) =>
    request<{ ok: boolean }>(`/api/groups/${id}`, { method: "DELETE" }),

  listProxyPresets: () => request<ProxyPreset[]>("/api/proxy-presets"),

  createProxyPreset: (data: { name: string; proxy: string; mode: string }) =>
    request<ProxyPreset>("/api/proxy-presets", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  createProxyPresets: (items: { name: string; proxy: string; mode: string }[]) =>
    request<ProxyPreset[]>("/api/proxy-presets/bulk", {
      method: "POST",
      body: JSON.stringify({ items }),
    }),

  deleteProxyPreset: (id: string) =>
    request<{ ok: boolean }>(`/api/proxy-presets/${id}`, { method: "DELETE" }),

  launchProfile: (id: string, launchMode: LaunchMode = "manual") =>
    request<LaunchResult>(`/api/profiles/${id}/launch`, {
      method: "POST",
      body: JSON.stringify({ launch_mode: launchMode }),
    }),

  stopProfile: (id: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}/stop`, { method: "POST" }),

  getStatus: () => request<SystemStatus>("/api/status"),

  updateManager: () =>
    request<ManagerUpdateResult>("/api/update", { method: "POST" }),

  updateBrowser: () =>
    request<BrowserUpdateResult>("/api/browser/update", { method: "POST" }),

  getPreflight: (id: string, launchMode: LaunchMode = "manual") =>
    request<PreflightResult>(`/api/profiles/${id}/preflight?launch_mode=${launchMode}`),

  exportConfiguration: () => request<Record<string, unknown>>("/api/configuration/export"),

  importConfiguration: (backup: Record<string, unknown>) =>
    request<ConfigurationImportResult>("/api/configuration/import", {
      method: "POST",
      body: JSON.stringify(backup),
    }),

  getFingerprintReport: (id: string) =>
    request<FingerprintReport>(`/api/profiles/${id}/fingerprint-report`),

  testProxy: (proxy: string) =>
    request<ProxyTestResult>("/api/proxy/test", {
      method: "POST",
      body: JSON.stringify({ proxy }),
    }),

  setClipboard: (id: string, text: string) =>
    request<{ ok: boolean }>(`/api/profiles/${id}/clipboard`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  getClipboard: (id: string) =>
    request<{ text: string }>(`/api/profiles/${id}/clipboard`),
};
