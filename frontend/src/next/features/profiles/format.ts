/**
 * How a profile is described in the list and the detail panel. Pure functions,
 * carried over from the current panel so both show the same words.
 */
import type { AgentLease, Profile, ProfileCreate } from "./types";

export const UNGROUPED = "未分组";

/** proxy_geo is a free-form dict on the backend; these are the keys the panel reads. */
export interface ProxyGeo {
  ip?: string | null;
  country?: string | null;
  country_code?: string | null;
  region?: string | null;
  city?: string | null;
}

export function geoOf(profile: Pick<Profile, "proxy_geo">): ProxyGeo | null {
  return (profile.proxy_geo as ProxyGeo | null | undefined) ?? null;
}

export function groupOf(profile: Pick<Profile, "group_name">): string {
  return profile.group_name?.trim() || UNGROUPED;
}

/** The agent lease of a running profile, if an agent holds it or the person took over. */
export function leaseOf(profile: Pick<Profile, "agent_lease">): AgentLease | null {
  const lease = profile.agent_lease as AgentLease | null | undefined;
  return lease?.holder ? lease : null;
}

export function isRunning(profile: Pick<Profile, "status">): boolean {
  return profile.status === "running";
}

const LINK_SCHEMES = new Set(["VLESS", "VMESS", "TROJAN", "SS"]);

/** 直连 / HTTP / HTTPS / SOCKS5 / VLESS / VMESS / TROJAN / SS / 代理 */
export function proxyType(profile: Pick<Profile, "proxy">): string {
  const value = profile.proxy?.trim();
  if (!value) return "直连";
  const scheme = value.split(":", 1)[0]?.toUpperCase() ?? "";
  if (LINK_SCHEMES.has(scheme) || scheme === "SOCKS5" || scheme === "HTTPS" || scheme === "HTTP") return scheme;
  return "代理";
}

/** The exit IP when known, else the proxy host:port; never the credentials. */
export function proxyHost(profile: Pick<Profile, "proxy" | "proxy_geo">): string {
  const value = profile.proxy?.trim();
  const ip = geoOf(profile)?.ip;
  if (!value) return ip ?? "本地网络";
  if (ip) return ip;
  try {
    const url = new URL(value);
    return `${url.hostname}${url.port ? `:${url.port}` : ""}`;
  } catch {
    if (!value.includes("://")) {
      // host:port[:user:pass] — show host:port only.
      const parts = (value.split("@").pop() ?? value).split(":");
      return parts.slice(0, 2).join(":");
    }
    const rest = value.split("://", 2)[1] ?? "";
    return rest.split(/[?#]/, 1)[0]?.split("@").pop() || "已配置";
  }
}

export function locationText(profile: Pick<Profile, "proxy" | "proxy_geo">): string {
  const geo = geoOf(profile);
  if (!geo) return profile.proxy ? "打开后检测" : "启动时检测本地出口";
  const country = [geo.country_code, geo.country].filter(Boolean).join(" - ");
  const city = [geo.region, geo.city].filter(Boolean).join(" / ");
  return [country, city].filter(Boolean).join(" · ") || "未知地区";
}

export function engineLabel(profile: Pick<Profile, "browser_engine">): string {
  return profile.browser_engine === "cloakbrowser" ? "防检测浏览器" : "稳定原生";
}

export function hasLaunchFailure(profile: Pick<Profile, "status" | "last_exit_reason">): boolean {
  const reason = profile.last_exit_reason;
  return !isRunning(profile) && Boolean(reason?.startsWith("异常退出") || reason?.startsWith("启动失败"));
}

const EXIT_CODE_REASONS: Record<string, string> = {
  "异常退出（代码 76）": "授权并发已满，请先关闭其他防检测浏览器",
  "异常退出（代码 77）": "CloakBrowser 授权无效或已过期",
  "异常退出（代码 78）": "CloakBrowser 授权服务器连接失败",
  "异常退出（代码 79）": "本地授权配置异常",
};

/** Why the last launch failed, in words; license exit codes 76–79 are translated. */
export function launchFailureReason(profile: Pick<Profile, "last_exit_reason">): string {
  const reason = profile.last_exit_reason;
  if (!reason) return "上一次启动未成功";
  return EXIT_CODE_REASONS[reason] ?? reason;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
}

export type LastState = { kind: "running" | "failed" | "idle"; text: string };

export function lastState(profile: Profile): LastState {
  if (isRunning(profile)) return { kind: "running", text: "运行中" };
  if (hasLaunchFailure(profile)) return { kind: "failed", text: "上次启动失败" };
  return { kind: "idle", text: formatDateTime(profile.last_opened_at || profile.updated_at) };
}

/** Search covers name, proxy, notes, UA, locale, timezone and tags, like the current panel. */
export function matchesSearch(profile: Profile, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const haystack = [
    profile.name,
    profile.proxy ?? "",
    profile.notes ?? "",
    profile.user_agent ?? "",
    profile.locale ?? "",
    profile.timezone ?? "",
    profile.account_platform ?? "",
    (profile.tags ?? []).map((tag) => tag.tag).join(" "),
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(q);
}

export const ALL_GROUPS = "__all__";

export function filterProfiles(profiles: Profile[], query: string, group: string): Profile[] {
  return profiles.filter((profile) => (group === ALL_GROUPS || groupOf(profile) === group) && matchesSearch(profile, query));
}

export function countByGroup(profiles: Profile[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const profile of profiles) counts.set(groupOf(profile), (counts.get(groupOf(profile)) ?? 0) + 1);
  return counts;
}

/**
 * The create payload for "复制": same configuration, a new name, a fresh
 * fingerprint seed (null lets the backend pick one) and auto launch off,
 * exactly as the current panel does.
 */
export function duplicatePayload(profile: Profile): ProfileCreate {
  const engine = profile.browser_engine;
  return {
    name: `${profile.name} 副本`,
    browser_engine: engine === "cloakbrowser" || engine === "system_chrome" || engine === "auto" ? engine : "auto",
    device_profile: profile.device_profile,
    fingerprint_seed: null,
    proxy: profile.proxy,
    timezone: profile.timezone,
    locale: profile.locale,
    platform: profile.platform as ProfileCreate["platform"],
    user_agent: profile.user_agent,
    screen_width: profile.screen_width,
    screen_height: profile.screen_height,
    gpu_vendor: profile.gpu_vendor,
    gpu_renderer: profile.gpu_renderer,
    hardware_concurrency: profile.hardware_concurrency,
    device_memory: profile.device_memory,
    humanize: profile.humanize,
    human_preset: profile.human_preset,
    headless: profile.headless,
    geoip: profile.geoip,
    clipboard_sync: profile.clipboard_sync,
    auto_launch: false,
    group_name: profile.group_name,
    account_platform: profile.account_platform,
    cookies_json: profile.cookies_json,
    startup_urls: profile.startup_urls,
    color_scheme: profile.color_scheme,
    launch_args: profile.launch_args,
    fingerprint_options: profile.fingerprint_options ?? {},
    notes: profile.notes,
    tags: profile.tags,
  } as ProfileCreate;
}

export const DISPOSABLE_REGIONS: { code: string; label: string }[] = [
  { code: "US", label: "美国" },
  { code: "JP", label: "日本" },
  { code: "GB", label: "英国" },
  { code: "DE", label: "德国" },
  { code: "FR", label: "法国" },
  { code: "NL", label: "荷兰" },
  { code: "TW", label: "台湾" },
  { code: "HK", label: "香港" },
  { code: "SG", label: "新加坡" },
  { code: "KR", label: "韩国" },
  { code: "AU", label: "澳大利亚" },
  { code: "CA", label: "加拿大" },
];


/** "Apple M4 Pro · 14 核 · 32 GB" once a launch has seen the seed's device; null otherwise. */
export function seedDeviceLabel(profile: { seed_device?: { [key: string]: unknown } | null } | null): string | null {
  const label = profile?.seed_device?.label;
  return typeof label === "string" && label ? label : null;
}
