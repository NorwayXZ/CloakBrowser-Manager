/**
 * The editor's rules as pure functions, carried over from the current panel's
 * ProfileForm: how a profile becomes form state, how fields depend on each
 * other, and what is sent on save. parity.test.tsx checks that, for the same
 * profile, this produces byte-for-byte the payload the current editor sends.
 */
import type { Profile } from "../profiles/types";
import {
  applyDeviceProfile,
  getDefaultDeviceProfileId,
  getDeviceProfile,
  getDeviceProfilesForPlatform,
  getDevicePlatformForHost,
  randomFingerprintSeed,
  type DevicePlatform,
  type DeviceProfilePreset,
} from "./deviceProfiles";
import type { EditorForm, HostOS, ProxyTestResult } from "./types";

// ── Choices ─────────────────────────────────────────────────────────────────

export const BROWSER_LANGUAGES: [string, string][] = [
  ["", "跟随上面的语言 / 出口 IP"],
  ["zh-CN", "简体中文（zh-CN）"],
  ["zh-TW", "繁體中文（zh-TW）"],
  ["en-US", "English（en-US）"],
];

export const RESOLUTION_PRESETS: Record<string, { width: number; height: number }> = {
  "1280 × 720 (原生窗口)": { width: 1280, height: 720 },
  "1920 × 1080 (Windows 常见)": { width: 1920, height: 1080 },
  "1920 × 1200 (Windows 笔记本)": { width: 1920, height: 1200 },
  "2256 × 1504 (Surface / 高分屏笔记本)": { width: 2256, height: 1504 },
  "2880 × 1800 (Windows 高分屏笔记本)": { width: 2880, height: 1800 },
  "2560 × 1600 (MacBook Air/Pro 13)": { width: 2560, height: 1600 },
  "2560 × 1664 (MacBook Air 13)": { width: 2560, height: 1664 },
  "2880 × 1864 (MacBook Air 15)": { width: 2880, height: 1864 },
  "3024 × 1964 (MacBook Pro 14)": { width: 3024, height: 1964 },
  "3456 × 2234 (MacBook Pro 16)": { width: 3456, height: 2234 },
  "4480 × 2520 (iMac 24)": { width: 4480, height: 2520 },
  "2560 × 1440 (外接 QHD)": { width: 2560, height: 1440 },
  "3840 × 2160 (外接 4K)": { width: 3840, height: 2160 },
  "5120 × 2880 (外接 5K)": { width: 5120, height: 2880 },
};

const appleGpu = (chip: string) => ({
  vendor: "Google Inc. (Apple)",
  renderer: `ANGLE (Apple, ANGLE Metal Renderer: ${chip}, Unspecified Version)`,
});

export const GPU_PRESETS: Record<string, { vendor: string; renderer: string }> = {
  ...Object.fromEntries(
    [
      "Apple M1", "Apple M1 Pro", "Apple M1 Max", "Apple M1 Ultra",
      "Apple M2", "Apple M2 Pro", "Apple M2 Max", "Apple M2 Ultra",
      "Apple M3", "Apple M3 Pro", "Apple M3 Max", "Apple M3 Ultra",
      "Apple M4", "Apple M4 Pro", "Apple M4 Max",
      "Apple M5", "Apple M5 Pro", "Apple M5 Max",
    ].map((chip) => [chip, appleGpu(chip)]),
  ),
  "Windows Intel Iris Xe": {
    vendor: "Google Inc. (Intel)",
    renderer: "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
  },
  "Windows Intel Arc Graphics": {
    vendor: "Google Inc. (Intel)",
    renderer: "ANGLE (Intel, Intel(R) Arc(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
  },
  "Windows Intel UHD 770": {
    vendor: "Google Inc. (Intel)",
    renderer: "ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0, D3D11)",
  },
  "Windows NVIDIA RTX 3060": {
    vendor: "Google Inc. (NVIDIA)",
    renderer: "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
  },
  "Windows NVIDIA RTX 4060": {
    vendor: "Google Inc. (NVIDIA)",
    renderer: "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
  },
  "Windows NVIDIA RTX 4060 Laptop": {
    vendor: "Google Inc. (NVIDIA)",
    renderer: "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Laptop GPU Direct3D11 vs_5_0 ps_5_0, D3D11)",
  },
  "Windows AMD Radeon RX 6600": {
    vendor: "Google Inc. (AMD)",
    renderer: "ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)",
  },
};

export const ACCOUNT_PLATFORM_OPTIONS = ["阿里云", "Amazon", "Google", "PayPal", "Facebook", "TikTok", "Shopify", "Stripe", "Cloudflare", "其他"];

export const WINDOWS_PLATFORM_VERSIONS: [string, string][] = [
  ["10.0.0", "Windows 10"],
  ["15.0.0", "Windows 11 22H2 / 23H2"],
  ["19.0.0", "Windows 11 24H2 及以上"],
];

export const MAC_PLATFORM_VERSIONS: [string, string][] = [
  ["14.7.0", "macOS 14 Sonoma"],
  ["15.6.0", "macOS 15 Sequoia"],
  ["26.0.0", "macOS 26 Tahoe"],
];

export const SECTIONS = [
  { id: "basic", label: "基础设置" },
  { id: "proxy", label: "代理信息" },
  { id: "fingerprint", label: "指纹配置" },
  { id: "more-fingerprint", label: "更多指纹" },
  { id: "advanced", label: "高级设置" },
] as const;

export function platformLabel(platform: DevicePlatform): string {
  return platform === "windows" ? "Windows" : "macOS";
}

// ── Proxy ───────────────────────────────────────────────────────────────────

export type ProxyKind = "none" | "custom" | "xray";
export type ProxyScheme = "http" | "https" | "socks5";
export type EditableEngine = "system_chrome" | "cloakbrowser";

export interface ProxyParts {
  kind: ProxyKind;
  scheme: ProxyScheme;
  host: string;
  port: string;
  username: string;
  password: string;
  raw: string;
}

const PROXY_SCHEMES: ProxyScheme[] = ["http", "https", "socks5"];

export const DEFAULT_PROXY_PARTS: ProxyParts = { kind: "none", scheme: "http", host: "", port: "", username: "", password: "", raw: "" };

function isProxyScheme(value: string): value is ProxyScheme {
  return PROXY_SCHEMES.includes(value as ProxyScheme);
}

export function parseProxy(raw?: string | null): ProxyParts {
  const value = raw?.trim();
  if (!value) return { ...DEFAULT_PROXY_PARTS };

  const scheme = value.split(":", 1)[0]?.toLowerCase();
  if (scheme && ["ss", "vmess", "vless", "trojan"].includes(scheme)) {
    return { ...DEFAULT_PROXY_PARTS, kind: "xray", raw: value };
  }

  if (value.includes("://")) {
    try {
      const url = new URL(value);
      const directScheme = url.protocol.replace(":", "");
      if (isProxyScheme(directScheme)) {
        return {
          kind: "custom",
          scheme: directScheme,
          host: url.hostname,
          port: url.port,
          username: decodeURIComponent(url.username),
          password: decodeURIComponent(url.password),
          raw: "",
        };
      }
    } catch {
      // Fall back to raw parsing below.
    }
  }

  const parts = value.split(":");
  if (parts.length === 4) {
    const [host, port, username, password] = parts;
    return { kind: "custom", scheme: "http", host: host ?? "", port: port ?? "", username: username ?? "", password: password ?? "", raw: "" };
  }
  if (parts.length === 2) {
    const [host, port] = parts;
    return { kind: "custom", scheme: "http", host: host ?? "", port: port ?? "", username: "", password: "", raw: "" };
  }
  return { ...DEFAULT_PROXY_PARTS, host: value };
}

export function buildProxy(parts: ProxyParts): string | null {
  let host = parts.host.trim();
  const port = parts.port.trim();
  if (!host || !port) return null;
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(host)) {
    try {
      host = new URL(host).hostname;
    } catch {
      // Keep the original value and let backend validation report the error.
    }
  }
  if (host.includes(":") && !host.startsWith("[") && !host.endsWith("]")) host = `[${host}]`;
  const username = parts.username.trim();
  const password = parts.password.trim();
  const auth = username || password ? `${encodeURIComponent(username)}:${encodeURIComponent(password)}@` : "";
  return `${parts.scheme}://${auth}${host}:${port}`;
}

export function proxyFromParts(parts: ProxyParts): string | null {
  if (parts.kind === "none") return null;
  if (parts.kind === "xray") return parts.raw.trim() || null;
  return buildProxy(parts);
}

export function proxyLabel(parts: ProxyParts): string {
  if (parts.kind === "none") return "直连";
  if (parts.kind === "xray") return parts.raw ? parts.raw.split("://", 1)[0]?.toUpperCase() ?? "Xray" : "Xray 链接";
  return parts.scheme.toUpperCase();
}

// ── Form state ──────────────────────────────────────────────────────────────

export function normalizeFormEngine(value?: string | null): EditableEngine {
  return value === "cloakbrowser" ? "cloakbrowser" : "system_chrome";
}

export function createDefaultForm(hostOS?: HostOS | null): EditorForm {
  return applyDeviceProfile(
    {
      name: "",
      browser_engine: "cloakbrowser",
      humanize: true,
      human_preset: "default",
      warmup_enabled: false,
      warmup_daily_max: 1,
      warmup_targets: [],
      warmup_persona: "",
      headless: false,
      geoip: true,
      clipboard_sync: true,
      auto_launch: false,
      group_name: "未分组",
      account_platform: null,
      cookies_json: null,
      startup_urls: [],
      launch_args: [],
      // Recommended preset for new profiles (measured 2026-10-21): noise off
      // scores better with detectors, a 50 GB quota removes BrowserScan's
      // private-mode penalty. Both can be switched back to "自动".
      fingerprint_options: { noise: false, storage_quota_mb: 50000 },
      tags: [],
    },
    getDeviceProfile(getDefaultDeviceProfileId(hostOS)),
  );
}

export interface EditorState {
  form: EditorForm;
  proxyParts: ProxyParts;
  startupUrlsText: string;
  launchArgsOpen: boolean;
}

/** Initial state for a new profile, or for editing `profile` on this host. */
export function initialState(profile: Profile | null, hostOS?: HostOS | null): EditorState {
  if (!profile) {
    return { form: createDefaultForm(hostOS), proxyParts: { ...DEFAULT_PROXY_PARTS }, startupUrlsText: "", launchArgsOpen: false };
  }
  const allowedPlatform = getDevicePlatformForHost(hostOS);
  const deviceProfile = getDeviceProfile(profile.device_profile);
  const baseForm: EditorForm = {
    name: profile.name,
    browser_engine: normalizeFormEngine(profile.browser_engine),
    device_profile: deviceProfile.id,
    fingerprint_seed: profile.fingerprint_seed,
    proxy: profile.proxy,
    ...(profile.proxy_id ? { proxy_id: profile.proxy_id } : {}),
    ...(profile.proxy_connection_mode === "relay" ? { proxy_connection_mode: "relay" as const, relay_id: profile.relay_id } : {}),
    timezone: profile.timezone,
    locale: profile.locale,
    platform: profile.platform,
    user_agent: profile.user_agent,
    screen_width: profile.screen_width,
    screen_height: profile.screen_height,
    gpu_vendor: profile.gpu_vendor,
    gpu_renderer: profile.gpu_renderer,
    hardware_concurrency: profile.hardware_concurrency,
    device_memory: profile.device_memory,
    humanize: profile.humanize,
    human_preset: profile.human_preset,
    warmup_enabled: Boolean(profile.warmup_enabled),
    warmup_daily_max: profile.warmup_daily_max ?? 1,
    warmup_targets: profile.warmup_targets ?? [],
    warmup_persona: profile.warmup_persona ?? "",
    headless: profile.headless,
    geoip: profile.geoip,
    clipboard_sync: profile.clipboard_sync,
    auto_launch: profile.auto_launch,
    group_name: profile.group_name || "未分组",
    account_platform: profile.account_platform,
    cookies_json: profile.cookies_json,
    startup_urls: profile.startup_urls ?? [],
    color_scheme: profile.color_scheme,
    launch_args: profile.launch_args ?? [],
    fingerprint_options: (profile.fingerprint_options ?? {}) as EditorForm["fingerprint_options"],
    notes: profile.notes,
    tags: (profile.tags ?? []) as EditorForm["tags"],
  };
  const coerced = deviceProfile.platform === allowedPlatform ? deviceProfile : getDeviceProfile(getDefaultDeviceProfileId(allowedPlatform));
  return {
    form: baseForm.platform === allowedPlatform && deviceProfile.platform === allowedPlatform ? baseForm : applyDeviceProfile(baseForm, coerced),
    proxyParts: parseProxy(profile.proxy),
    startupUrlsText: (profile.startup_urls ?? []).join("\n"),
    launchArgsOpen: (profile.launch_args ?? []).length > 0,
  };
}

/** The device preset in effect: the form's own when it fits this host, else the host default. */
export function selectedDevice(form: EditorForm, hostOS?: HostOS | null): DeviceProfilePreset {
  const allowed = getDevicePlatformForHost(hostOS);
  const raw = getDeviceProfile(form.device_profile);
  return raw.platform === allowed ? raw : getDeviceProfile(getDefaultDeviceProfileId(allowed));
}

/** What is sent on save: the device is forced onto this host's platform, and an empty proxy is null. */
export function buildPayload(form: EditorForm, hostOS?: HostOS | null): EditorForm {
  const allowed = getDevicePlatformForHost(hostOS);
  const device = selectedDevice(form, hostOS);
  const safe = form.platform === allowed && form.device_profile === device.id ? form : applyDeviceProfile(form, device);
  return form.proxy ? safe : { ...safe, proxy: null };
}

export function changeEngine(form: EditorForm, engine: EditableEngine, hostOS?: HostOS | null): EditorForm {
  return applyDeviceProfile({ ...form, browser_engine: engine }, selectedDevice(form, hostOS));
}

export function changeDevice(form: EditorForm, id: string, hostOS?: HostOS | null): EditorForm {
  const allowed = getDevicePlatformForHost(hostOS);
  const next = getDeviceProfilesForPlatform(allowed).find((preset) => preset.id === id) ?? getDeviceProfile(getDefaultDeviceProfileId(allowed));
  return applyDeviceProfile(form, next);
}

/** A different device of this host's platform, with a new seed ("随机设备画像"). */
export function randomizeDevice(form: EditorForm, hostOS?: HostOS | null, random: () => number = Math.random): EditorForm {
  const allowed = getDevicePlatformForHost(hostOS);
  const defaultId = getDefaultDeviceProfileId(allowed);
  const presets = getDeviceProfilesForPlatform(allowed);
  const pool = presets.filter((preset) => preset.id !== defaultId && preset.id !== form.device_profile);
  const fallback = presets.filter((preset) => preset.id !== defaultId);
  const choices = pool.length > 0 ? pool : fallback;
  const next = choices[Math.floor(random() * choices.length)] ?? getDeviceProfile(defaultId);
  return applyDeviceProfile({ ...form, fingerprint_seed: randomFingerprintSeed() }, next);
}

export function applyProxyGeo(form: EditorForm, result: ProxyTestResult | null): EditorForm {
  if (!result) return form;
  return {
    ...form,
    ...(result.timezone ? { timezone: result.timezone } : {}),
    ...(result.suggested_locale ? { locale: result.suggested_locale } : {}),
  };
}

export function startupUrlsFromText(text: string): string[] {
  return text.split(/\r?\n/).map((url) => url.trim()).filter(Boolean);
}

export function extensionPaths(launchArgs: string[] = []): string[] {
  return launchArgs
    .filter((arg) => arg.startsWith("--load-extension="))
    .flatMap((arg) => arg.slice("--load-extension=".length).split(","))
    .map((path) => path.trim())
    .filter(Boolean);
}

/** Replace the --load-extension argument with one built from the directories, one per line. */
export function withExtensionPaths(launchArgs: string[] = [], text: string): string[] {
  const paths = text.split(/\r?\n/).map((path) => path.trim()).filter(Boolean);
  const args = launchArgs.filter((arg) => !arg.startsWith("--load-extension="));
  if (paths.length > 0) args.push(`--load-extension=${paths.join(",")}`);
  return args;
}

export function defaultCookieDomain(form: EditorForm): string {
  const firstUrl = (form.startup_urls ?? [])[0];
  if (!firstUrl) return "";
  try {
    return new URL(firstUrl.includes("://") ? firstUrl : `https://${firstUrl}`).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export function currentResolution(form: EditorForm): string {
  return Object.entries(RESOLUTION_PRESETS).find(([, v]) => v.width === form.screen_width && v.height === form.screen_height)?.[0] ?? "custom";
}

export function realScreenOf(hostScreen?: number[] | null): [number, number] | null {
  return hostScreen && hostScreen.length === 2 ? [hostScreen[0]!, hostScreen[1]!] : null;
}

/** CloakBrowser profiles follow the computer's screen unless a custom size was chosen. */
export function screenFollowsDisplay(form: EditorForm, hostScreen?: number[] | null): boolean {
  return normalizeFormEngine(form.browser_engine) === "cloakbrowser" && realScreenOf(hostScreen) !== null && (form.fingerprint_options?.screen ?? "real") === "real";
}

// ── Summary ─────────────────────────────────────────────────────────────────

export interface SummaryContext {
  form: EditorForm;
  proxyParts: ProxyParts;
  proxyTest: ProxyTestResult | null;
  hostOS?: HostOS | null;
  hostScreen?: number[] | null;
  isEdit: boolean;
}

function screenLabel({ form, hostScreen }: SummaryContext): string {
  const real = realScreenOf(hostScreen);
  return screenFollowsDisplay(form, hostScreen) && real ? `跟随电脑 ${real[0]} × ${real[1]}` : `${form.screen_width ?? 1920} × ${form.screen_height ?? 1080}`;
}

function cpuGpu({ form }: SummaryContext) {
  const engine = normalizeFormEngine(form.browser_engine);
  const rendererName = form.gpu_renderer?.split("Renderer: ")[1] ?? form.gpu_renderer;
  return {
    cpu: engine === "system_chrome" ? "真实设备" : form.hardware_concurrency ? `${form.hardware_concurrency} 线程` : "按画像",
    gpu:
      engine === "system_chrome"
        ? "真实设备"
        : form.gpu_renderer?.includes("Renderer: ")
          ? rendererName?.replace(", Unspecified Version)", ")") ?? "按画像"
          : form.gpu_renderer ?? "真实设备",
  };
}

function timezoneLocale({ form, proxyTest }: SummaryContext) {
  const fallback = form.geoip ? "出口 IP 自动覆盖" : "出口 IP 自动补全";
  return {
    timezone: form.timezone || proxyTest?.timezone || fallback,
    locale: form.fingerprint_options?.language || form.locale || proxyTest?.suggested_locale || fallback,
  };
}

/** The right-hand 概要, row for row as in the current editor. */
export function summaryRows(ctx: SummaryContext): [string, string][] {
  const { form, proxyParts, proxyTest, hostOS, isEdit } = ctx;
  const engine = normalizeFormEngine(form.browser_engine);
  const device = selectedDevice(form, hostOS);
  const { cpu, gpu } = cpuGpu(ctx);
  const { timezone, locale } = timezoneLocale(ctx);
  const options = form.fingerprint_options ?? {};
  const exitPlace = [proxyTest?.city, proxyTest?.country].filter(Boolean).join(" · ");
  const geolocation = options.geolocation ?? "ip";
  const webrtc = options.webrtc ?? "proxy";
  const cloakOnly: [string, string][] =
    engine === "cloakbrowser"
      ? [
          ["浏览器品牌", options.brand ? `${options.brand}${options.brand_version ? ` ${options.brand_version}` : ""}` : "Chrome（跟随内核）"],
          ["WebRTC", webrtc === "custom" ? `指定 ${options.webrtc_ip || "（未填）"}` : form.proxy ? `出口 IP${proxyTest?.ip ? ` ${proxyTest.ip}` : ""}` : "真实（直连）"],
          ["地理位置", geolocation === "block" ? "禁止" : geolocation === "real" ? "真实" : `基于 IP${exitPlace ? `（${exitPlace}）` : ""}`],
          ["指纹噪声", options.noise == null ? "自动" : options.noise ? "开启" : "关闭"],
          ["跨电脑 Cookie", options.portable_cookies ? "开启" : "关闭"],
        ]
      : [];
  return [
    ["浏览器", engine === "system_chrome" ? "Google Chrome 原生" : "CloakBrowser / Chromium"],
    ["系统", platformLabel(getDevicePlatformForHost(hostOS))],
    ["画像", device.name],
    ["账号平台", form.account_platform || "未设置"],
    ["User-Agent", form.user_agent || "跟随真实浏览器"],
    ["代理", form.proxy ? `${proxyLabel(proxyParts)} · 已配置` : "直连 · 本地网络"],
    ...(proxyTest?.ip ? ([["出口 IP", exitPlace ? `${proxyTest.ip}（${exitPlace}）` : proxyTest.ip]] as [string, string][]) : []),
    ["启动页面", (form.startup_urls ?? []).length > 0 ? `${form.startup_urls?.length} 个网址` : "默认自检页"],
    ["时区", timezone],
    ["语言", locale],
    ["分辨率", screenLabel(ctx)],
    ["Canvas", engine === "system_chrome" ? "真实" : "按画像"],
    ["WebGL 图像", engine === "system_chrome" ? "真实" : "按画像"],
    ["WebGL 元数据", gpu],
    ["CPU", cpu],
    ...cloakOnly,
    ["资料夹", isEdit ? "独立保存" : "创建后生成"],
  ];
}

/** The grid at the top of 指纹配置. */
export function fingerprintPreviewRows(ctx: SummaryContext): [string, string][] {
  const { form, hostOS, hostScreen } = ctx;
  const engine = normalizeFormEngine(form.browser_engine);
  const device = selectedDevice(form, hostOS);
  const { cpu, gpu } = cpuGpu(ctx);
  const { timezone, locale } = timezoneLocale(ctx);
  return [
    ["运行模式", engine === "system_chrome" ? "系统 Chrome 原生" : "CloakBrowser 画像"],
    ["操作系统", platformLabel(getDevicePlatformForHost(hostOS))],
    ["设备画像", device.name],
    ["CPU / 芯片", device.chip],
    ["屏幕", screenFollowsDisplay(form, hostScreen) ? screenLabel(ctx) : `${form.screen_width ?? device.screen_width} × ${form.screen_height ?? device.screen_height}`],
    ["CPU", cpu],
    ["GPU", gpu],
    ["语言/时区", `${locale} / ${timezone}`],
    ["Canvas / Audio", engine === "system_chrome" ? "真实浏览器输出" : "按同一画像稳定输出"],
  ];
}
