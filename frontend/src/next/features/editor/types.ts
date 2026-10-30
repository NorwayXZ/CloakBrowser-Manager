/**
 * Shapes the editor sends and reads. EditorForm is exactly what the current
 * panel's editor sends to POST /api/profiles and PUT /api/profiles/{id} (only
 * these keys), so the backend sees the same payload from either editor; the
 * parity test holds them to that.
 */

export type HostOS = "windows" | "macos" | "linux";
export type BrowserEngine = "auto" | "system_chrome" | "cloakbrowser";

export interface FingerprintOptions {
  brand?: "Chrome" | "Edge" | "Opera" | "Vivaldi" | null;
  brand_version?: string | null;
  platform_version?: string | null;
  webrtc?: "proxy" | "custom";
  webrtc_ip?: string | null;
  geolocation?: "ip" | "block" | "real";
  noise?: boolean | null;
  screen?: "real" | "custom";
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

export interface EditorForm {
  name: string;
  browser_engine?: BrowserEngine | null;
  device_profile?: string | null;
  fingerprint_seed?: number | null;
  proxy?: string | null;
  proxy_connection_mode?: "direct" | "relay";
  relay_id?: string | null;
  proxy_id?: string | null;
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

export interface ProxyPreset {
  can_rotate_ip?: boolean;
  id: string;
  name: string;
  proxy: string;
  mode: string;
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
  proxy_connection_mode?: "direct" | "relay";
  relay_name?: string | null;
  elapsed_ms?: number | null;
  handshake_ms?: number | null;
  ip_quality?: IpQuality | null;
}

export interface CookieMergeResult {
  cookies_json: string;
  format: "json" | "netscape" | "header";
  added: number;
  total: number;
}

export interface CookiePullResult {
  cookies_json: string;
  count: number;
}

export type CookieExportFormat = "json" | "netscape";

export interface WarmupTarget {
  id: string;
  name: string;
}

export interface WarmupInfo {
  age: {
    created_at: string | null;
    age_days: number | null;
    warmup_sessions: number;
    last_warmup_at: string | null;
  };
  runs: {
    id: string;
    started_at: string;
    pages_visited: number;
    status: string;
    reason: string | null;
  }[];
  warming: boolean;
}

export interface WarmupScriptStep {
  kind: string;
  platform: string | null;
  platform_name: string | null;
  search_query: string | null;
  dwell: string;
  follow_link: boolean;
}

export interface WarmupScriptBatch {
  batch_id: string;
  created_at: string;
  status: string;
  model: string | null;
  scripts: { id: string; theme: string; steps: WarmupScriptStep[] }[];
}

export interface WarmupScriptsInfo {
  llm_configured: boolean;
  generating: boolean;
  last_generation: { status: string; error: string | null } | null;
  batches: WarmupScriptBatch[];
}

export interface AutomationHours {
  hours: string | null;
  open_now: boolean;
}
