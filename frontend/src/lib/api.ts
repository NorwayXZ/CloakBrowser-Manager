/**
 * API client for CloakBrowser Manager backend.
 */

export type HostOS = "windows" | "macos" | "linux";
export type RuntimeMode = "native" | "docker";
export type ViewerMode = "native-window" | "vnc";
export type BrowserEngine = "auto" | "system_chrome" | "cloakbrowser";
export type LaunchMode = "manual" | "debug";
export type BrowserBrand = "Chrome" | "Edge" | "Opera" | "Vivaldi";
export type WebRTCMode = "proxy" | "custom";
export type GeolocationMode = "ip" | "block" | "real";

/** CloakBrowser switches beyond the core persona; empty means "kernel decides". */
export type ScreenMode = "real" | "custom";

export interface FingerprintOptions {
  brand?: BrowserBrand | null;
  brand_version?: string | null;
  platform_version?: string | null;
  webrtc?: WebRTCMode;
  webrtc_ip?: string | null;
  geolocation?: GeolocationMode;
  noise?: boolean | null;
  screen?: ScreenMode;
  /** Fixed language for the interface, navigator and Intl; null follows the locale / exit IP. */
  language?: string | null;
  speech_voices?: boolean;
  storage_quota_mb?: number | null;
  taskbar_height?: number | null;
  windows_font_metrics?: boolean;
  allow_3p_cookies?: boolean;
  transparent_proxy?: boolean;
  portable_cookies?: boolean;
}

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
  warmup_enabled?: boolean | number;
  warmup_daily_max?: number;
  warmup_targets?: string[];
  warmup_persona?: string | null;
  evolution_enabled?: boolean | number;
  evolution_interval_hours?: number;
  headless: boolean;
  geoip: boolean;
  clipboard_sync: boolean;
  auto_launch: boolean;
  disposable: boolean;
  group_name: string | null;
  account_platform: string | null;
  cookies_json: string | null;
  startup_urls: string[];
  color_scheme: string | null;
  launch_args: string[];
  fingerprint_options?: FingerprintOptions;
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
  agent_lease?: AgentLease | null;
}

/** Who is driving a running profile: an AI agent, or the user after a takeover. */
export interface AgentLease {
  holder: string;
  kind: "agent" | "human";
  acquired_at: string;
  expires_at: string;
  seconds_left: number;
}

export type McpMode = "off" | "read-only" | "full" | "automation";
export type AgentTokenScope = "read" | "control" | "cdp";

export interface AgentToken {
  id: string;
  name: string;
  scope: AgentTokenScope;
  created_at: number;
}

export interface AgentTokenList {
  /** False when the Manager has no authentication: tokens are then not checked. */
  enforced: boolean;
  scopes: AgentTokenScope[];
  tokens: AgentToken[];
}

export interface AgentTokenCreated {
  /** Plaintext token, shown exactly once. */
  token: string;
  record: AgentToken;
  enforced: boolean;
  note: string;
}

export interface McpAuditEntry {
  id: string;
  ts: string;
  client_name: string | null;
  client_version: string | null;
  tool: string;
  args_summary: Record<string, unknown>;
  ok: boolean;
  reason: string | null;
  duration_ms: number | null;
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
  warmup_enabled?: boolean;
  warmup_daily_max?: number;
  warmup_targets?: string[];
  warmup_persona?: string | null;
  evolution_enabled?: boolean;
  evolution_interval_hours?: number;
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
  fingerprint_options?: FingerprintOptions;
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
  /** Packaged app version; null when running from a source checkout. */
  app_version?: string | null;
  binary_version: string;
  profiles_total: number;
  host_os: HostOS;
  runtime_mode: RuntimeMode;
  viewer_mode: ViewerMode;
  /** This computer's screen [width, height]; profiles that follow it launch with it. */
  host_screen?: number[] | null;
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
  download_url?: string | null;
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

export type KernelLicenseTier = "none" | "free" | "paid" | "invalid" | "unknown";

export interface KernelSettings {
  auto_update: boolean;
  release_channel: "stable" | "preview";
  pinned_version: string | null;
}

export interface InstalledKernel {
  name: string;
  version: string;
  pro: boolean;
  size_bytes: number;
  in_use: boolean;
}

export interface KernelOverview {
  wrapper_version: string | null;
  platform: string | null;
  cache_dir: string;
  license: {
    tier: KernelLicenseTier;
    plan: string | null;
    expires: string | null;
    can_pin: boolean;
    key_stored: boolean;
  };
  settings: KernelSettings;
  version: string | null;
  installed: boolean;
  pinned: boolean;
  bundled_version: string | null;
  installed_kernels: InstalledKernel[];
  running_count: number;
}

export interface KernelCheckResult {
  current_version: string | null;
  latest_version: string;
  update_available: boolean;
  pinned: boolean;
}

/** One cookie in the panel's stored shape (Cookie-Editor style fields). */
export interface PulledCookie {
  name: string;
  value: string;
  domain: string;
  path: string;
  secure?: boolean;
  httpOnly?: boolean;
  hostOnly?: boolean;
  expirationDate?: number;
  sameSite?: string;
  session?: boolean;
}

export interface CookiePullResult {
  cookies: PulledCookie[];
  cookies_json: string;
  count: number;
}

export type CookieExportFormat = "json" | "netscape";

export interface LinkabilityLink {
  a_id: string;
  b_id: string;
  a_name: string;
  b_name: string;
  score: number;
  level: "strong" | "medium" | string;
  reasons: string[];
  suggestions: string[];
}

export interface LinkabilityCluster {
  id: string;
  risk: "high" | "medium" | string;
  profiles: { id: string; name: string }[];
  links: LinkabilityLink[];
}

export interface LinkabilityResult {
  profile_count: number;
  unclustered_count: number;
  clusters: LinkabilityCluster[];
}

export interface DisposableCreateData {
  name?: string | null;
  region?: string | null;
  timezone?: string | null;
  locale?: string | null;
}

export interface SentenceSpec {
  country: string;
  city: string | null;
  interests: string[];
  persona_notes: string | null;
  purpose: string | null;
  disposable: boolean;
}

export interface SentenceAssembled {
  name: string;
  platform: string;
  device_profile: string;
  screen_width: number;
  screen_height: number;
  gpu_vendor: string;
  gpu_renderer: string;
  hardware_concurrency: number;
  device_memory: number;
  timezone: string;
  locale: string;
  warmup_targets: string[];
  warmup_enabled: boolean;
  warmup_persona: string | null;
  notes: string | null;
  disposable: boolean;
  fingerprint_options: FingerprintOptions;
}

export interface SentenceDraftResult {
  source: "llm" | "fallback";
  spec: SentenceSpec;
  assembled: SentenceAssembled;
  warnings: string[];
}

export interface SentenceCountryOption {
  code: string;
  name: string;
  locale: string | null;
  timezone: string | null;
}

export interface SentenceCityOption {
  name: string;
  name_zh: string;
  timezone: string;
}

export interface SentenceInterestOption {
  id: string;
  name: string;
  targets: string[];
}

export interface SentenceTargetOption {
  id: string;
  name: string;
}

export interface SentenceOptions {
  countries: SentenceCountryOption[];
  cities: Record<string, SentenceCityOption[]>;
  interests: SentenceInterestOption[];
  targets: SentenceTargetOption[];
}

export interface DeviceTemplateSummary {
  id: string;
  name: string;
  family: string;
  cpu: string;
  gpu_vendor: string;
  gpu_renderer: string;
  screen_width: number;
  screen_height: number;
  hardware_concurrency: number;
  device_memory: number;
  device_scale_factor: number;
}

export interface SentenceCreateResult extends Profile {
  warnings: string[];
}

export interface BurnResult {
  ok: boolean;
  profile_id: string;
  user_data_dir: string;
  files_removed: number;
  was_running: boolean;
}

export interface CookieMergeResult {
  cookies_json: string;
  format: "json" | "netscape" | "header";
  added: number;
  total: number;
}

export type AppUpdatePhase = "idle" | "checking" | "downloading" | "backing_up" | "preparing" | "restarting" | "failed";

export interface AppUpdateResult {
  ok: boolean;
  from: string | null;
  to: string;
  running: string;
  reason: string | null;
  finished_at: string;
}

export interface AppUpdateState {
  phase: AppUpdatePhase;
  label?: string;
  target?: string;
  done?: number;
  total?: number;
  error?: string;
  supported?: boolean;
  current_version?: string | null;
  last_result?: AppUpdateResult | null;
}

export type SiteCheckStatus = "pass" | "warn" | "fail" | "unknown" | "error";

export interface WarmupTarget {
  id: string;
  name: string;
}

export interface WarmupRun {
  id: string;
  profile_id: string;
  started_at: string;
  finished_at: string | null;
  duration_s: number | null;
  pages_visited: number;
  status: "ok" | "skipped" | "failed" | string;
  reason: string | null;
  detail: { targets?: string[]; urls?: string[]; script_id?: string | null } | null;
}

export interface WarmupScriptStep {
  kind: "target" | "generic" | string;
  platform: string | null;
  platform_name: string | null;
  search_query: string | null;
  dwell: "short" | "medium" | "long" | string;
  follow_link: boolean;
}

export interface WarmupScript {
  id: string;
  theme: string;
  steps: WarmupScriptStep[];
}

export interface WarmupScriptBatch {
  batch_id: string;
  created_at: string;
  status: "draft" | "approved" | "rejected" | "archived" | string;
  model: string | null;
  persona: string | null;
  scripts: WarmupScript[];
}

export interface WarmupScriptsInfo {
  llm_configured: boolean;
  generating: boolean;
  last_generation: {
    status: "done" | "error" | string;
    batch_id: string | null;
    at: string;
    error: string | null;
  } | null;
  batches: WarmupScriptBatch[];
}

export interface LlmSettings {
  configured: boolean;
  base_url: string | null;
  model: string | null;
  has_api_key: boolean;
  executor_model: string | null;
  executor_effort: string | null;
}

export interface LlmSettingsUpdate {
  base_url: string;
  model: string;
  api_key?: string | null;
  /** Deletes the stored key; wins over api_key. */
  clear_api_key?: boolean;
  executor_model: string;
  executor_effort: string;
}

export interface WarmupInfo {
  enabled: boolean;
  daily_max: number;
  targets: string[];
  age: {
    created_at: string | null;
    age_days: number | null;
    warmup_sessions: number;
    warmup_runs_total: number;
    last_warmup_at: string | null;
  };
  runs: WarmupRun[];
  warming: boolean;
}

export type EvolutionOutcome =
  | "running" | "clean" | "unfixable_only" | "experiments" | "check_failed" | "deferred" | "error";

export type ExperimentVerdict = "improved" | "no_change" | "regressed" | "error" | "deferred";

export interface EvolutionExperiment {
  knob: string;
  label: string;
  from_value: unknown;
  to_value: unknown;
  targets: string[];
  rationale: string;
  verdict: ExperimentVerdict;
  targets_detail: Record<string, { from: SiteCheckStatus | null; to: SiteCheckStatus | null }>;
  regressions: { site: string; name?: string; from: SiteCheckStatus | null; to: SiteCheckStatus | null }[];
  clone_report_id?: string | null;
  proposal_id?: string;
  note?: string | null;
}

export interface EvolutionUnfixable {
  site: string;
  name: string;
  status: SiteCheckStatus;
  reason: string;
}

export interface EvolutionLogDetail {
  source_report_id?: string;
  problem_count?: number;
  experiments?: EvolutionExperiment[];
  unfixable?: EvolutionUnfixable[];
  proposals?: string[];
}

export interface EvolutionLogEntry {
  id: string;
  profile_id: string | null;
  profile_name: string | null;
  started_at: string;
  finished_at: string | null;
  trigger: "scheduled" | "manual" | string | null;
  outcome: EvolutionOutcome | string | null;
  summary: string | null;
  detail: EvolutionLogDetail;
}

export interface EvolutionProposal {
  id: string;
  profile_id: string;
  profile_name: string | null;
  knob: string;
  label: string | null;
  from_value: unknown;
  to_value: unknown;
  targets: string[];
  evidence: {
    verdict?: string;
    rationale?: string;
    source_report_id?: string;
    clone_report_id?: string;
    targets?: Record<string, { from: SiteCheckStatus | null; to: SiteCheckStatus | null }>;
  };
  status: "pending" | "applied" | "dismissed";
  created_at: string;
  decided_at: string | null;
}

export interface EvolutionStatus {
  busy: boolean;
  profile_id: string | null;
  profile_name: string | null;
  lock_owner: string | null;
  pending_proposals: number;
}

export interface AutomationStatus {
  active: boolean;
  kind: "site_check" | "warmup" | "evolution" | null;
  label: string | null;
  profile_id: string | null;
  profile_name: string | null;
}

export interface AutomationHours {
  // Local-time "HH-HH" range (may wrap midnight); null = no restriction.
  hours: string | null;
  open_now: boolean;
}

export interface SiteCheckSite {
  id: string;
  name: string;
  url: string;
  criteria: string;
}

export interface SiteCheckResult {
  site: string;
  name: string;
  url: string;
  criteria: string;
  status: SiteCheckStatus;
  summary: string;
  details: string[];
  screenshot: string | null;
  seconds: number;
  /** "site" for public detection sites, "local" for the Manager's own probe items. */
  source?: "site" | "local";
  /** Caveat for verdicts that depend on the egress IP's reputation. */
  ip_note?: string | null;
}

export interface SiteCheckCounts {
  pass: number;
  warn: number;
  fail: number;
  unknown: number;
  error: number;
  total: number;
}

export interface SiteCheckDiffChange {
  site: string;
  name?: string | null;
  from: SiteCheckStatus | null;
  to: SiteCheckStatus | null;
  summary?: string | null;
}

export interface SiteCheckDiff {
  previous_id?: string | null;
  previous_created_at?: string | null;
  changes: SiteCheckDiffChange[];
}

export interface SiteCheckState {
  phase: "idle" | "launching" | "checking" | "closing" | "done" | "failed";
  profile_id?: string;
  profile_name?: string;
  site?: string | null;
  index?: number;
  total?: number;
  results?: SiteCheckResult[];
  report_id?: string;
  overall?: "pass" | "warn" | "fail";
  error?: string;
}

export interface SiteCheckReportSummary {
  id: string;
  created_at: string | null;
  overall: "pass" | "warn" | "fail" | null;
  profile_id?: string | null;
  profile_name: string | null;
  host_os: string | null;
  passed: number;
  total: number;
  counts?: SiteCheckCounts;
}

export interface SiteCheckReport {
  id: string;
  created_at: string;
  overall: "pass" | "warn" | "fail";
  environment: Record<string, unknown>;
  results: SiteCheckResult[];
  /** Per-status tallies; absent on reports written before they were recorded. */
  summary?: SiteCheckCounts;
  /** Egress-IP caveat for the whole report; absent on older reports. */
  egress_note?: string;
  /** Status changes vs the previous report of the same profile (detail view only). */
  diff?: SiteCheckDiff | null;
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

export type IpQualityStatus = "flagged" | "suspicious" | "clean" | "unknown";

export interface IpQuality {
  verdict: IpQualityStatus;
  summary: string;
  signals: { source: string; status: IpQualityStatus; detail: string }[];
  links: { name: string; url: string }[];
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
  connection_mode?: "direct" | "proxy" | null;
  /** Whether the exit IP is known as a proxy, VPN or datacenter address. */
  ip_quality?: IpQuality | null;
  /** Every exit IP this test saw; more than one of a family = rotating. */
  exit_ips?: string[];
  rotating_ip?: boolean;
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

export interface BackupItem {
  name: string;
  kind: "full" | "auto";
  /** Who made a full backup: by hand, on the weekly schedule, or before an update. */
  origin?: "manual" | "auto" | "pre-update" | "snapshot";
  size: number;
  created_at: string;
}

export interface AutoBackupSettings {
  enabled: boolean;
  interval_days: number;
  keep: number;
  copy_dir: string | null;
}

export interface AutoBackupStatus extends AutoBackupSettings {
  default_copy_dir: string;
  last_at: string | null;
  next_due_at: string | null;
  last_error: string | null;
  last_copy: string | null;
  waiting_for_browsers: boolean;
}

export interface BackupListResult {
  backups: BackupItem[];
  location: string;
}

export interface BackupRestoreResult {
  ok: boolean;
  profiles: number;
  previous_data: string;
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

  /** The person takes over from an AI agent: parks the lease on "human" and cuts its CDP sockets. */
  takeoverProfile: (id: string) =>
    request<{ lease: AgentLease | null; cdp_connections_closed: number }>(
      `/api/profiles/${id}/lease/takeover`,
      { method: "POST", body: JSON.stringify({}) },
    ),

  /** The person hands the profile back to agents. */
  releaseProfileLease: (id: string) =>
    request<{ released: boolean }>(`/api/profiles/${id}/lease`, { method: "DELETE" }),

  getStatus: () => request<SystemStatus>("/api/status"),

  updateManager: () =>
    request<ManagerUpdateResult>("/api/update", { method: "POST" }),

  updateBrowser: () =>
    request<BrowserUpdateResult>("/api/browser/update", { method: "POST" }),

  mergeCookies: (text: string, existing: string | null, domain: string | null) =>
    request<CookieMergeResult>("/api/cookies/merge", {
      method: "POST",
      body: JSON.stringify({ text, existing, domain }),
    }),

  pullProfileCookies: (id: string) =>
    request<CookiePullResult>(`/api/profiles/${id}/cookies/pull`, { method: "POST" }),

  cookieExportUrl: (id: string, format: CookieExportFormat) =>
    `/api/profiles/${encodeURIComponent(id)}/cookies/export?format=${format}`,

  /** Fetch the export as a file; surfaces the server's error instead of
   *  downloading an error page when the browser is not readable. */
  downloadCookieExport: async (id: string, format: CookieExportFormat, filename: string) => {
    const res = await fetch(api.cookieExportUrl(id, format));
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new ApiError(res.status, body.detail || res.statusText);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } finally {
      URL.revokeObjectURL(url);
    }
  },

  getAppUpdate: () => request<AppUpdateState>("/api/app/update"),

  startAppUpdate: () => request<AppUpdateState>("/api/app/update", { method: "POST" }),

  dismissAppUpdateResult: () => request<{ ok: boolean }>("/api/app/update/result", { method: "DELETE" }),

  listSiteCheckSites: () => request<SiteCheckSite[]>("/api/site-checks/sites"),

  startSiteCheck: (profileId: string) =>
    request<SiteCheckState>(`/api/profiles/${profileId}/site-check`, { method: "POST" }),

  getSiteCheckState: () => request<SiteCheckState>("/api/site-checks/current"),

  listSiteCheckReports: () => request<SiteCheckReportSummary[]>("/api/site-checks"),

  getSiteCheckReport: (id: string) => request<SiteCheckReport>(`/api/site-checks/${encodeURIComponent(id)}`),

  deleteSiteCheckReport: (id: string) =>
    request<{ ok: boolean }>(`/api/site-checks/${encodeURIComponent(id)}`, { method: "DELETE" }),

  siteCheckFileUrl: (id: string, name: string) =>
    `/api/site-checks/${encodeURIComponent(id)}/files/${encodeURIComponent(name)}`,

  siteCheckDownloadUrl: (id: string) => `/api/site-checks/${encodeURIComponent(id)}/download`,

  listWarmupTargets: () => request<WarmupTarget[]>("/api/warmup/targets"),

  getProfileWarmup: (profileId: string) =>
    request<WarmupInfo>(`/api/profiles/${encodeURIComponent(profileId)}/warmup`),

  runProfileWarmupNow: (profileId: string) =>
    request<{ ok: boolean; started: boolean }>(
      `/api/profiles/${encodeURIComponent(profileId)}/warmup/run`,
      { method: "POST" },
    ),

  getWarmupScripts: (profileId: string) =>
    request<WarmupScriptsInfo>(`/api/profiles/${encodeURIComponent(profileId)}/warmup/scripts`),

  generateWarmupScripts: (profileId: string) =>
    request<{ ok: boolean; started: boolean }>(
      `/api/profiles/${encodeURIComponent(profileId)}/warmup/scripts/generate`,
      { method: "POST" },
    ),

  approveWarmupScriptBatch: (profileId: string, batchId: string) =>
    request<{ ok: boolean; status: string; count: number }>(
      `/api/profiles/${encodeURIComponent(profileId)}/warmup/scripts/batches/${encodeURIComponent(batchId)}/approve`,
      { method: "POST" },
    ),

  rejectWarmupScriptBatch: (profileId: string, batchId: string) =>
    request<{ ok: boolean; status: string; count: number }>(
      `/api/profiles/${encodeURIComponent(profileId)}/warmup/scripts/batches/${encodeURIComponent(batchId)}/reject`,
      { method: "POST" },
    ),

  getLlmSettings: () => request<LlmSettings>("/api/settings/llm"),

  getMcpMode: () => request<{ mode: McpMode }>("/api/settings/mcp"),

  setMcpMode: (mode: McpMode) =>
    request<{ mode: McpMode }>("/api/settings/mcp", {
      method: "PUT",
      body: JSON.stringify({ mode }),
    }),

  listAgentTokens: () => request<AgentTokenList>("/api/agent/tokens"),

  createAgentToken: (name: string, scope: AgentTokenScope) =>
    request<AgentTokenCreated>("/api/agent/tokens", {
      method: "POST",
      body: JSON.stringify({ name, scope }),
    }),

  revokeAgentToken: (id: string) =>
    request<{ ok: boolean }>(`/api/agent/tokens/${id}`, { method: "DELETE" }),

  listMcpAudit: (limit = 30) => request<McpAuditEntry[]>(`/api/mcp/audit?limit=${limit}`),

  updateLlmSettings: (data: LlmSettingsUpdate) =>
    request<LlmSettings>("/api/settings/llm", {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  getAutomationStatus: () => request<AutomationStatus>("/api/automation/status"),

  getAutomationHours: () => request<AutomationHours>("/api/automation/hours"),

  updateAutomationHours: (hours: string | null) =>
    request<AutomationHours>("/api/automation/hours", {
      method: "PUT",
      body: JSON.stringify({ hours }),
    }),

  getEvolutionStatus: () => request<EvolutionStatus>("/api/evolution/status"),

  listEvolutionProposals: (status?: string) =>
    request<EvolutionProposal[]>(`/api/evolution/proposals${status ? `?status=${encodeURIComponent(status)}` : ""}`),

  approveEvolutionProposal: (id: string) =>
    request<EvolutionProposal>(`/api/evolution/proposals/${encodeURIComponent(id)}/approve`, { method: "POST" }),

  dismissEvolutionProposal: (id: string) =>
    request<EvolutionProposal>(`/api/evolution/proposals/${encodeURIComponent(id)}/dismiss`, { method: "POST" }),

  listEvolutionLogs: (profileId?: string, limit = 30) =>
    request<EvolutionLogEntry[]>(
      `/api/evolution/logs?limit=${limit}${profileId ? `&profile_id=${encodeURIComponent(profileId)}` : ""}`,
    ),

  runEvolutionNow: (profileId: string) =>
    request<{ ok: boolean; started: boolean }>(
      `/api/profiles/${encodeURIComponent(profileId)}/evolution/run`,
      { method: "POST" },
    ),

  getKernel: () => request<KernelOverview>("/api/kernel"),

  checkKernel: () => request<KernelCheckResult>("/api/kernel/check", { method: "POST" }),

  updateKernel: () => request<BrowserUpdateResult>("/api/kernel/update", { method: "POST" }),

  saveKernelSettings: (settings: KernelSettings) =>
    request<KernelOverview>("/api/kernel/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),

  saveLicenseKey: (licenseKey: string) =>
    request<KernelOverview>("/api/kernel/license", {
      method: "POST",
      body: JSON.stringify({ license_key: licenseKey }),
    }),

  removeLicenseKey: () =>
    request<KernelOverview>("/api/kernel/license", { method: "DELETE" }),

  deleteKernel: (name: string) =>
    request<{ ok: boolean; freed_bytes: number }>(`/api/kernel/versions/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),

  getPreflight: (id: string, launchMode: LaunchMode = "manual") =>
    request<PreflightResult>(`/api/profiles/${id}/preflight?launch_mode=${launchMode}`),

  exportConfiguration: () => request<Record<string, unknown>>("/api/configuration/export"),

  importConfiguration: (backup: Record<string, unknown>) =>
    request<ConfigurationImportResult>("/api/configuration/import", {
      method: "POST",
      body: JSON.stringify(backup),
    }),

  listBackups: () => request<BackupListResult>("/api/backups"),

  getAutoBackup: () => request<AutoBackupStatus>("/api/backups/auto"),

  saveAutoBackup: (settings: AutoBackupSettings) =>
    request<AutoBackupStatus>("/api/backups/auto", { method: "PUT", body: JSON.stringify(settings) }),

  runAutoBackup: () =>
    request<{ ok: boolean; name: string; copy: string | null; copy_error: string | null; status: AutoBackupStatus }>(
      "/api/backups/auto/run",
      { method: "POST" },
    ),

  createBackup: () => request<BackupItem>("/api/backups", { method: "POST" }),

  backupDownloadUrl: (name: string) => `/api/backups/full/${encodeURIComponent(name)}/download`,

  restoreBackup: (item: Pick<BackupItem, "kind" | "name">) =>
    request<BackupRestoreResult>(
      `/api/backups/${item.kind}/${encodeURIComponent(item.name)}/restore`,
      { method: "POST" },
    ),

  restoreBackupFile: (file: File) =>
    request<BackupRestoreResult>("/api/backups/restore-upload", {
      method: "POST",
      headers: { "Content-Type": "application/zip" },
      body: file,
    }),

  deleteBackup: (item: Pick<BackupItem, "kind" | "name">) =>
    request<{ ok: boolean }>(`/api/backups/${item.kind}/${encodeURIComponent(item.name)}`, {
      method: "DELETE",
    }),

  revealBackups: () => request<{ ok: boolean; location: string }>("/api/backups/reveal", { method: "POST" }),

  getFingerprintReport: (id: string) =>
    request<FingerprintReport>(`/api/profiles/${id}/fingerprint-report`),

  getLinkability: () => request<LinkabilityResult>("/api/linkability"),

  createDisposable: (data: DisposableCreateData = {}) =>
    request<Profile>("/api/profiles/disposable", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  draftFromSentence: (sentence: string) =>
    request<SentenceDraftResult>("/api/profiles/from-sentence/draft", {
      method: "POST",
      body: JSON.stringify({ sentence }),
    }),

  createFromSentence: (data: { sentence: string; assembled: SentenceAssembled }) =>
    request<SentenceCreateResult>("/api/profiles/from-sentence", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getSentenceOptions: () => request<SentenceOptions>("/api/profiles/from-sentence/options"),

  listDeviceTemplates: () => request<DeviceTemplateSummary[]>("/api/device-templates"),

  burnProfile: (id: string) =>
    request<BurnResult>(`/api/profiles/${id}/burn`, {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    }),

  testProxy: (proxy: string | null) =>
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
