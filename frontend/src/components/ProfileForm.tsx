import { ArrowLeft, ClipboardCheck, Download, FileDown, Globe, Loader2, MousePointer2, Plus, RefreshCw, Save, Settings2, Trash2, Wifi, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { AutomationHoursHint } from "./AutomationHours";
import { WarmupScriptsSection } from "./WarmupScriptsSection";
import {
  api,
  type CookieExportFormat,
  type CookieMergeResult,
  type FingerprintOptions,
  type HostOS,
  type Profile,
  type ProfileCreateData,
  type ProfileGroup,
  type ProxyPreset,
  type IpQuality,
  type IpQualityStatus,
  type ProxyTestResult,
  type WarmupInfo,
  type WarmupTarget,
} from "../lib/api";
import {
  applyDeviceProfile,
  type DevicePlatform,
  getDefaultDeviceProfileId,
  getDeviceProfileFamiliesForPlatform,
  getDeviceProfilesForPlatform,
  getDevicePlatformForHost,
  getDeviceProfile,
  randomFingerprintSeed,
} from "../lib/deviceProfiles";

interface ProfileFormProps {
  profile: Profile | null; // null = create mode
  groups?: ProfileGroup[];
  proxyPresets?: ProxyPreset[];
  onSave: (data: ProfileCreateData) => Promise<void>;
  onDelete?: () => Promise<void>;
  onCancel: () => void;
  onDraftChange?: (data: ProfileCreateData) => void;
  hostOS?: HostOS | null;
  /** This computer's screen [width, height], when the backend can read it. */
  hostScreen?: number[] | null;
}

const IP_QUALITY_STYLE: Record<IpQualityStatus, { box: string; label: string }> = {
  flagged: { box: "border-red-200 bg-red-50 text-red-800", label: "已被标记" },
  suspicious: { box: "border-amber-200 bg-amber-50 text-amber-800", label: "有风险" },
  clean: { box: "border-emerald-200 bg-emerald-50 text-emerald-800", label: "未标记" },
  unknown: { box: "border-slate-200 bg-slate-50 text-slate-700", label: "无法判断" },
};

function IpQualityPanel({ quality }: { quality: IpQuality }) {
  const style = IP_QUALITY_STYLE[quality.verdict];
  return (
    <div className={`rounded-md border p-3 text-xs ${style.box}`} data-testid="ip-quality">
      <div className="font-medium">IP 质量：{style.label}</div>
      <div className="mt-1">{quality.summary}</div>
      <ul className="mt-2 space-y-0.5">
        {quality.signals.map((signal) => (
          <li key={signal.source}>
            {signal.source}：{IP_QUALITY_STYLE[signal.status].label} · {signal.detail}
          </li>
        ))}
      </ul>
      {quality.links.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>手动再查：</span>
          {quality.links.map((link) => (
            <a key={link.name} href={link.url} target="_blank" rel="noreferrer" className="underline">
              {link.name}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

const BROWSER_LANGUAGES: [string, string][] = [
  ["", "跟随上面的语言 / 出口 IP"],
  ["zh-CN", "简体中文（zh-CN）"],
  ["zh-TW", "繁體中文（zh-TW）"],
  ["en-US", "English（en-US）"],
];

const RESOLUTION_PRESETS: Record<string, { width: number; height: number }> = {
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

const GPU_PRESETS: Record<string, { vendor: string; renderer: string }> = {
  "Apple M1": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)",
  },
  "Apple M1 Pro": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M1 Pro, Unspecified Version)",
  },
  "Apple M1 Max": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M1 Max, Unspecified Version)",
  },
  "Apple M1 Ultra": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M1 Ultra, Unspecified Version)",
  },
  "Apple M2": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)",
  },
  "Apple M2 Pro": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M2 Pro, Unspecified Version)",
  },
  "Apple M2 Max": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M2 Max, Unspecified Version)",
  },
  "Apple M2 Ultra": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M2 Ultra, Unspecified Version)",
  },
  "Apple M3": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)",
  },
  "Apple M3 Pro": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Pro, Unspecified Version)",
  },
  "Apple M3 Max": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Max, Unspecified Version)",
  },
  "Apple M3 Ultra": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Ultra, Unspecified Version)",
  },
  "Apple M4": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M4, Unspecified Version)",
  },
  "Apple M4 Pro": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M4 Pro, Unspecified Version)",
  },
  "Apple M4 Max": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M4 Max, Unspecified Version)",
  },
  "Apple M5": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M5, Unspecified Version)",
  },
  "Apple M5 Pro": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M5 Pro, Unspecified Version)",
  },
  "Apple M5 Max": {
    vendor: "Google Inc. (Apple)",
    renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M5 Max, Unspecified Version)",
  },
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

type ProxyKind = "none" | "custom" | "xray";
type ProxyScheme = "http" | "https" | "socks5";
type EditableBrowserEngine = "system_chrome" | "cloakbrowser";

interface ProxyParts {
  kind: ProxyKind;
  scheme: ProxyScheme;
  host: string;
  port: string;
  username: string;
  password: string;
  raw: string;
}

const PROXY_SCHEMES: ProxyScheme[] = ["http", "https", "socks5"];

const ACCOUNT_PLATFORM_OPTIONS = [
  "阿里云",
  "Amazon",
  "Google",
  "PayPal",
  "Facebook",
  "TikTok",
  "Shopify",
  "Stripe",
  "Cloudflare",
  "其他",
];

const DEFAULT_PROXY_PARTS: ProxyParts = {
  kind: "none",
  scheme: "http",
  host: "",
  port: "",
  username: "",
  password: "",
  raw: "",
};

function FieldNote({ children }: { children: ReactNode }) {
  return <div className="mt-1 text-xs leading-5 text-slate-500">{children}</div>;
}

function SectionIntro({ children }: { children: ReactNode }) {
  return (
    <div className="mb-5 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
      {children}
    </div>
  );
}

const WINDOWS_PLATFORM_VERSIONS: [string, string][] = [
  ["10.0.0", "Windows 10"],
  ["15.0.0", "Windows 11 22H2 / 23H2"],
  ["19.0.0", "Windows 11 24H2 及以上"],
];

const MAC_PLATFORM_VERSIONS: [string, string][] = [
  ["14.7.0", "macOS 14 Sonoma"],
  ["15.6.0", "macOS 15 Sequoia"],
  ["26.0.0", "macOS 26 Tahoe"],
];

const FORM_SECTIONS: [string, string][] = [
  ["basic", "基础设置"],
  ["proxy", "代理信息"],
  ["fingerprint", "指纹配置"],
  ["more-fingerprint", "更多指纹"],
  ["advanced", "高级设置"],
];

interface CookieMergeState {
  text: string;
  domain: string;
  busy: boolean;
  notice: { tone: "success" | "error"; text: string } | null;
}

const COOKIE_FORMAT_LABELS: Record<CookieMergeResult["format"], string> = {
  json: "JSON",
  netscape: "Netscape",
  header: "Name=Value",
};

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-border bg-slate-50 p-0.5">
      {options.map(([option, text]) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={value === option}
          onClick={() => onChange(option)}
          className={`rounded px-3 py-1.5 text-sm ${
            value === option ? "bg-white font-medium text-accent shadow-sm" : "text-slate-600 hover:text-slate-900"
          }`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

function OptionCheckbox({
  checked,
  onChange,
  title,
  note,
  disabled = false,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  title: string;
  note: string;
  disabled?: boolean;
}) {
  return (
    <label className={`flex items-start gap-3 text-sm ${disabled ? "text-slate-400" : "text-slate-800"}`}>
      <input
        type="checkbox"
        className="mt-0.5"
        checked={checked && !disabled}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <span className="font-medium">{title}</span>
        <span className="mt-0.5 block text-xs leading-5 text-slate-500">{note}</span>
      </span>
    </label>
  );
}

function platformLabel(platform: DevicePlatform): string {
  return platform === "windows" ? "Windows" : "macOS";
}

function createDefaultForm(hostOS?: HostOS | null): ProfileCreateData {
  return applyDeviceProfile({
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
    // 新建画像的推荐预设（2026-10-21 实测：关噪声对检测分数净正面，
    // 50 GB 配额消除 BrowserScan 的无痕模式扣分）；可随时在下方切回「自动」。
    fingerprint_options: { noise: false, storage_quota_mb: 50000 },
    tags: [],
  }, getDeviceProfile(getDefaultDeviceProfileId(hostOS)));
}

function isProxyScheme(value: string): value is ProxyScheme {
  return PROXY_SCHEMES.includes(value as ProxyScheme);
}

function parseProxy(raw?: string | null): ProxyParts {
  const value = raw?.trim();
  if (!value) return { ...DEFAULT_PROXY_PARTS };

  const scheme = value.split(":", 1)[0]?.toLowerCase();
  if (scheme && ["ss", "vmess", "vless", "trojan"].includes(scheme)) {
    return {
      ...DEFAULT_PROXY_PARTS,
      kind: "xray",
      raw: value,
    };
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
    return {
      kind: "custom",
      scheme: "http",
      host: host ?? "",
      port: port ?? "",
      username: username ?? "",
      password: password ?? "",
      raw: "",
    };
  }
  if (parts.length === 2) {
    const [host, port] = parts;
    return {
      kind: "custom",
      scheme: "http",
      host: host ?? "",
      port: port ?? "",
      username: "",
      password: "",
      raw: "",
    };
  }

  return { ...DEFAULT_PROXY_PARTS, host: value };
}

function buildProxy(parts: ProxyParts): string | null {
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
  if (host.includes(":") && !host.startsWith("[") && !host.endsWith("]")) {
    host = `[${host}]`;
  }

  const username = parts.username.trim();
  const password = parts.password.trim();
  const auth = username || password
    ? `${encodeURIComponent(username)}:${encodeURIComponent(password)}@`
    : "";

  return `${parts.scheme}://${auth}${host}:${port}`;
}

function proxyFromParts(parts: ProxyParts): string | null {
  if (parts.kind === "none") return null;
  if (parts.kind === "xray") return parts.raw.trim() || null;
  return buildProxy(parts);
}

function normalizeFormEngine(value?: string | null): EditableBrowserEngine {
  return value === "cloakbrowser" ? "cloakbrowser" : "system_chrome";
}

export function ProfileForm({
  profile,
  groups = [],
  proxyPresets = [],
  onSave,
  onDelete,
  onCancel,
  onDraftChange,
  hostOS,
  hostScreen,
}: ProfileFormProps) {
  const isEdit = profile !== null;
  const allowedPlatform = getDevicePlatformForHost(hostOS);

  const [form, setForm] = useState<ProfileCreateData>(() => createDefaultForm(hostOS));
  const [proxyParts, setProxyParts] = useState<ProxyParts>(() => parseProxy(profile?.proxy));
  const [proxyTest, setProxyTest] = useState<ProxyTestResult | null>(null);
  const [proxyTestError, setProxyTestError] = useState<string | null>(null);
  const [testingProxy, setTestingProxy] = useState(false);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [launchArgInput, setLaunchArgInput] = useState("");
  const [launchArgsOpen, setLaunchArgsOpen] = useState(false);
  const [startupUrlsText, setStartupUrlsText] = useState("");
  const [draftProfileId, setDraftProfileId] = useState<string | null>(null);
  const [cookieMerge, setCookieMerge] = useState<CookieMergeState | null>(null);
  const [cookieBusy, setCookieBusy] = useState<"pull" | "export" | null>(null);
  const [cookieNotice, setCookieNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [cookieExportFormat, setCookieExportFormat] = useState<CookieExportFormat>("json");
  const [warmupInfo, setWarmupInfo] = useState<WarmupInfo | null>(null);
  const [warmupCatalog, setWarmupCatalog] = useState<WarmupTarget[]>([]);
  const [warmupRunning, setWarmupRunning] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.listWarmupTargets().then((targets) => {
      if (!cancelled) setWarmupCatalog(targets);
    }).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!profile) {
      setWarmupInfo(null);
      return;
    }
    let cancelled = false;
    api.getProfileWarmup(profile.id).then((info) => {
      if (!cancelled) setWarmupInfo(info);
    }).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [profile?.id]);

  useEffect(() => {
    if (profile) {
      const browserEngine = normalizeFormEngine(profile.browser_engine);
      const deviceProfile = getDeviceProfile(profile.device_profile);
      const baseForm: ProfileCreateData = {
        name: profile.name,
        browser_engine: browserEngine,
        device_profile: deviceProfile.id,
        fingerprint_seed: profile.fingerprint_seed,
        proxy: profile.proxy,
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
        fingerprint_options: profile.fingerprint_options ?? {},
        notes: profile.notes,
        tags: profile.tags ?? [],
      };
      const coercedDeviceProfile = deviceProfile.platform === allowedPlatform
        ? deviceProfile
        : getDeviceProfile(getDefaultDeviceProfileId(allowedPlatform));
      setForm(
        (baseForm.platform === allowedPlatform && deviceProfile.platform === allowedPlatform)
          ? baseForm
          : applyDeviceProfile(baseForm, coercedDeviceProfile),
      );
      setStartupUrlsText((profile.startup_urls ?? []).join("\n"));
      setProxyParts(parseProxy(profile.proxy));
      setDraftProfileId(profile.id);
      setLaunchArgsOpen((profile.launch_args ?? []).length > 0);
    } else {
      setForm(createDefaultForm(hostOS));
      setStartupUrlsText("");
      setProxyParts({ ...DEFAULT_PROXY_PARTS });
      setDraftProfileId(null);
      setLaunchArgsOpen(false);
    }
    setProxyTest(null);
    setProxyTestError(null);
  }, [allowedPlatform, hostOS, profile?.id]);

  useEffect(() => {
    if (profile && draftProfileId === profile.id) {
      onDraftChange?.(form);
    }
  }, [draftProfileId, form, onDraftChange, profile]);

  const set = <K extends keyof ProfileCreateData>(key: K, value: ProfileCreateData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const defaultCookieDomain = (() => {
    const firstUrl = (form.startup_urls ?? [])[0];
    if (!firstUrl) return "";
    try {
      return new URL(firstUrl.includes("://") ? firstUrl : `https://${firstUrl}`).hostname.replace(/^www\./, "");
    } catch {
      return "";
    }
  })();

  const handlePullCookies = async () => {
    if (!profile) return;
    setCookieBusy("pull");
    setCookieNotice(null);
    try {
      const result = await api.pullProfileCookies(profile.id);
      set("cookies_json", result.cookies_json);
      setCookieNotice({
        tone: "success",
        text: result.count > 0
          ? `已从浏览器导回 ${result.count} 条 Cookie，已填入上方文本框；点保存后写入配置`
          : "浏览器里目前没有 Cookie",
      });
    } catch (err) {
      setCookieNotice({ tone: "error", text: err instanceof Error ? err.message : "导回 Cookie 失败" });
    } finally {
      setCookieBusy(null);
    }
  };

  const handleExportCookies = async () => {
    if (!profile) return;
    setCookieBusy("export");
    setCookieNotice(null);
    try {
      const safeName = (form.name || "profile").replace(/[^\w\- ]+/g, "_").trim() || "profile";
      const extension = cookieExportFormat === "json" ? "json" : "txt";
      await api.downloadCookieExport(profile.id, cookieExportFormat, `${safeName}-cookies.${extension}`);
      setCookieNotice({ tone: "success", text: "Cookie 文件已开始下载" });
    } catch (err) {
      setCookieNotice({ tone: "error", text: err instanceof Error ? err.message : "导出 Cookie 失败" });
    } finally {
      setCookieBusy(null);
    }
  };

  const handleMergeCookies = async () => {
    if (!cookieMerge) return;
    setCookieMerge({ ...cookieMerge, busy: true, notice: null });
    try {
      const result = await api.mergeCookies(cookieMerge.text, form.cookies_json ?? null, cookieMerge.domain.trim() || null);
      set("cookies_json", result.cookies_json);
      setCookieMerge({
        text: "",
        domain: cookieMerge.domain,
        busy: false,
        notice: { tone: "success", text: `已合并 ${result.added} 条（${COOKIE_FORMAT_LABELS[result.format]}），现在共 ${result.total} 条` },
      });
    } catch (err) {
      setCookieMerge({
        ...cookieMerge,
        busy: false,
        notice: { tone: "error", text: err instanceof Error ? err.message : "合并失败" },
      });
    }
  };

  const fingerprintOptions: FingerprintOptions = form.fingerprint_options ?? {};
  const setOption = <K extends keyof FingerprintOptions>(key: K, value: FingerprintOptions[K]) => {
    setForm((prev) => ({ ...prev, fingerprint_options: { ...(prev.fingerprint_options ?? {}), [key]: value } }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      const safeForm = form.platform === allowedPlatform && form.device_profile === selectedDeviceProfile.id
        ? form
        : applyDeviceProfile(form, selectedDeviceProfile);
      await onSave(form.proxy ? safeForm : { ...safeForm, proxy: null });
    } catch (err) {
      // Surface the failure inline: the list view's error banner is hidden
      // behind this full-screen form, so without this the user sees nothing.
      setSaveError(err instanceof Error && err.message ? err.message : "保存失败，请检查输入后重试");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!onDelete) return;
    if (!confirm("确定删除这个浏览器吗？删除后会进入回收站，7 天内可以恢复。")) return;
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
    }
  };

  const applyGpuPreset = (name: string) => {
    const preset = GPU_PRESETS[name];
    if (preset) {
      set("gpu_vendor", preset.vendor);
      set("gpu_renderer", preset.renderer);
    }
  };

  const randomizeSeed = () => {
    set("fingerprint_seed", randomFingerprintSeed());
  };

  const randomizeDeviceProfile = () => {
    const defaultProfileId = getDefaultDeviceProfileId(allowedPlatform);
    const platformProfiles = getDeviceProfilesForPlatform(allowedPlatform);
    const profilePool = platformProfiles.filter((preset) => (
      preset.id !== defaultProfileId && preset.id !== form.device_profile
    ));
    const fallbackPool = platformProfiles.filter((preset) => preset.id !== defaultProfileId);
    const pool = profilePool.length > 0 ? profilePool : fallbackPool;
    const nextProfile = pool[Math.floor(Math.random() * pool.length)] ?? getDeviceProfile(defaultProfileId);
    setForm((prev) => applyDeviceProfile(
      { ...prev, fingerprint_seed: randomFingerprintSeed() },
      nextProfile,
    ));
  };

  const updateProxyPart = <K extends keyof ProxyParts>(key: K, value: ProxyParts[K]) => {
    const next = { ...proxyParts, [key]: value };
    setProxyParts(next);
    set("proxy", proxyFromParts(next));
    setProxyTest(null);
    setProxyTestError(null);
  };

  const updateProxyKind = (kind: ProxyKind) => {
    const next = {
      ...proxyParts,
      kind,
      raw: kind === "xray" ? proxyParts.raw : "",
    };
    setProxyParts(next);
    set("proxy", proxyFromParts(next));
    setProxyTest(null);
    setProxyTestError(null);
  };

  const applyProxyGeo = (result: ProxyTestResult | null = proxyTest) => {
    if (!result) return;
    if (result.timezone) set("timezone", result.timezone);
    if (result.suggested_locale) set("locale", result.suggested_locale);
  };

  const handleProxyTest = async () => {
    if (proxyParts.kind !== "none" && !form.proxy) {
      setProxyTest(null);
      setProxyTestError("请先填写代理主机和端口");
      return;
    }
    setTestingProxy(true);
    setProxyTest(null);
    setProxyTestError(null);
    try {
      const result = await api.testProxy(form.proxy ?? null);
      setProxyTest(result);
      if (form.geoip) {
        applyProxyGeo(result);
      }
    } catch (err) {
      setProxyTestError(err instanceof Error ? err.message : "代理测试失败");
    } finally {
      setTestingProxy(false);
    }
  };

  const currentResolution = Object.entries(RESOLUTION_PRESETS).find(
    ([, v]) => v.width === form.screen_width && v.height === form.screen_height,
  )?.[0] ?? "custom";

  const currentEngine = normalizeFormEngine(form.browser_engine);
  const realScreen = hostScreen && hostScreen.length === 2 ? hostScreen : null;
  // Sites read the real display through CSS media queries, so a CloakBrowser
  // profile follows it unless a custom size was chosen.
  const screenFollowsDisplay = currentEngine === "cloakbrowser"
    && realScreen !== null
    && (form.fingerprint_options?.screen ?? "real") === "real";
  const screenLabel = screenFollowsDisplay && realScreen
    ? `跟随电脑 ${realScreen[0]} × ${realScreen[1]}`
    : `${form.screen_width ?? 1920} × ${form.screen_height ?? 1080}`;
  const platformProfiles = getDeviceProfilesForPlatform(allowedPlatform);
  const platformFamilies = getDeviceProfileFamiliesForPlatform(allowedPlatform);
  const rawSelectedDeviceProfile = getDeviceProfile(form.device_profile);
  const selectedDeviceProfile = rawSelectedDeviceProfile.platform === allowedPlatform
    ? rawSelectedDeviceProfile
    : getDeviceProfile(getDefaultDeviceProfileId(allowedPlatform));
  const rendererName = form.gpu_renderer?.split("Renderer: ")[1] ?? form.gpu_renderer;
  const summaryCpu = currentEngine === "system_chrome"
    ? "真实设备"
    : form.hardware_concurrency ? `${form.hardware_concurrency} 线程` : "按画像";
  const summaryGpu = currentEngine === "system_chrome"
    ? "真实设备"
    : form.gpu_renderer?.includes("Renderer: ")
    ? rendererName?.replace(", Unspecified Version)", ")")
    : form.gpu_renderer ?? "真实设备";
  const proxyGeoFallbackLabel = form.geoip ? "出口 IP 自动覆盖" : "出口 IP 自动补全";
  const effectiveTimezonePreview = form.timezone
    || proxyTest?.timezone
    || proxyGeoFallbackLabel;
  const effectiveLocalePreview = form.fingerprint_options?.language
    || form.locale
    || proxyTest?.suggested_locale
    || proxyGeoFallbackLabel;

  const handleDeviceProfileChange = (id: string) => {
    const nextProfile = platformProfiles.find((preset) => preset.id === id) ?? getDeviceProfile(getDefaultDeviceProfileId(allowedPlatform));
    setForm((prev) => applyDeviceProfile(prev, nextProfile));
  };

  const handleEngineChange = (engine: "system_chrome" | "cloakbrowser") => {
    setForm((prev) => applyDeviceProfile(
      { ...prev, browser_engine: engine },
      selectedDeviceProfile.platform === allowedPlatform
        ? selectedDeviceProfile
        : getDeviceProfile(getDefaultDeviceProfileId(allowedPlatform)),
    ));
  };

  const addLaunchArg = () => {
    const arg = launchArgInput.trim();
    if (!arg) return;
    if ((form.launch_args ?? []).includes(arg)) return;
    set("launch_args", [...(form.launch_args ?? []), arg]);
    setLaunchArgsOpen(true);
    setLaunchArgInput("");
  };

  const removeLaunchArg = (idx: number) => {
    set("launch_args", (form.launch_args ?? []).filter((_, i) => i !== idx));
  };

  const extensionPaths = (form.launch_args ?? [])
    .filter((arg) => arg.startsWith("--load-extension="))
    .flatMap((arg) => arg.slice("--load-extension=".length).split(","))
    .map((path) => path.trim())
    .filter(Boolean);

  const updateExtensionPaths = (value: string) => {
    const paths = value.split(/\r?\n/).map((path) => path.trim()).filter(Boolean);
    const args = (form.launch_args ?? []).filter((arg) => !arg.startsWith("--load-extension="));
    if (paths.length > 0) args.push(`--load-extension=${paths.join(",")}`);
    set("launch_args", args);
  };

  const updateStartupUrls = (value: string) => {
    setStartupUrlsText(value);
    set("startup_urls", value
      .split(/\r?\n/)
      .map((url) => url.trim())
      .filter(Boolean));
  };

  const proxyLabel = proxyParts.kind === "none"
    ? "直连"
    : proxyParts.kind === "xray"
    ? (proxyParts.raw ? proxyParts.raw.split("://", 1)[0]?.toUpperCase() ?? "Xray" : "Xray 链接")
    : proxyParts.scheme.toUpperCase();

  const exitPlace = [proxyTest?.city, proxyTest?.country].filter(Boolean).join(" · ");
  const geolocationMode = fingerprintOptions.geolocation ?? "ip";
  const webrtcMode = fingerprintOptions.webrtc ?? "proxy";
  const cloakOnlyRows: [string, string][] = currentEngine === "cloakbrowser"
    ? [
        ["浏览器品牌", fingerprintOptions.brand
          ? `${fingerprintOptions.brand}${fingerprintOptions.brand_version ? ` ${fingerprintOptions.brand_version}` : ""}`
          : "Chrome（跟随内核）"],
        ["WebRTC", webrtcMode === "custom"
          ? `指定 ${fingerprintOptions.webrtc_ip || "（未填）"}`
          : form.proxy ? `出口 IP${proxyTest?.ip ? ` ${proxyTest.ip}` : ""}` : "真实（直连）"],
        ["地理位置", geolocationMode === "block"
          ? "禁止"
          : geolocationMode === "real"
          ? "真实"
          : `基于 IP${exitPlace ? `（${exitPlace}）` : ""}`],
        ["指纹噪声", fingerprintOptions.noise == null ? "自动" : fingerprintOptions.noise ? "开启" : "关闭"],
        ["跨电脑 Cookie", fingerprintOptions.portable_cookies ? "开启" : "关闭"],
      ]
    : [];

  const summaryRows = [
    ["浏览器", currentEngine === "system_chrome" ? "Google Chrome 原生" : "CloakBrowser / Chromium"],
    ["系统", platformLabel(allowedPlatform)],
    ["画像", selectedDeviceProfile.name],
    ["账号平台", form.account_platform || "未设置"],
    ["User-Agent", form.user_agent || "跟随真实浏览器"],
    ["代理", form.proxy ? `${proxyLabel} · 已配置` : "直连 · 本地网络"],
    ...(proxyTest?.ip ? [["出口 IP", exitPlace ? `${proxyTest.ip}（${exitPlace}）` : proxyTest.ip]] : []),
    ["启动页面", (form.startup_urls ?? []).length > 0 ? `${form.startup_urls?.length} 个网址` : "默认自检页"],
    ["时区", effectiveTimezonePreview],
    ["语言", effectiveLocalePreview],
    ["分辨率", screenLabel],
    ["Canvas", currentEngine === "system_chrome" ? "真实" : "按画像"],
    ["WebGL 图像", currentEngine === "system_chrome" ? "真实" : "按画像"],
    ["WebGL 元数据", summaryGpu],
    ["CPU", summaryCpu],
    ...cloakOnlyRows,
    ["资料夹", isEdit ? "独立保存" : "创建后生成"],
  ];

  const fingerprintPreviewRows = [
    ["运行模式", currentEngine === "system_chrome" ? "系统 Chrome 原生" : "CloakBrowser 画像"],
    ["操作系统", platformLabel(allowedPlatform)],
    ["设备画像", selectedDeviceProfile.name],
    ["CPU / 芯片", selectedDeviceProfile.chip],
    ["屏幕", screenFollowsDisplay ? screenLabel : `${form.screen_width ?? selectedDeviceProfile.screen_width} × ${form.screen_height ?? selectedDeviceProfile.screen_height}`],
    ["CPU", summaryCpu],
    ["GPU", summaryGpu],
    ["语言/时区", `${effectiveLocalePreview} / ${effectiveTimezonePreview}`],
    ["Canvas / Audio", currentEngine === "system_chrome" ? "真实浏览器输出" : "按同一画像稳定输出"],
  ];

  return (
    <form onSubmit={handleSubmit} className="flex h-screen flex-col bg-surface-0 text-slate-900">
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-border bg-white px-5">
        <div className="flex items-center gap-3">
          <button type="button" onClick={onCancel} className="btn-secondary px-2.5" title="返回环境管理">
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div>
            <h2 className="text-lg font-semibold tracking-tight">{isEdit ? "编辑浏览器" : "新建浏览器"}</h2>
            <div className="text-xs text-slate-500">{form.name || "未命名"} · {currentEngine === "system_chrome" ? "稳定原生" : "伪装画像"}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isEdit && onDelete && (
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleting}
              className="btn-danger flex items-center gap-1.5"
            >
              <Trash2 className="h-3.5 w-3.5" />
              <span>{deleting ? "删除中..." : "删除"}</span>
            </button>
          )}
          <button type="button" onClick={onCancel} className="btn-secondary">取消</button>
          <button type="submit" disabled={saving} className="btn-primary flex items-center gap-1.5">
            <Save className="h-3.5 w-3.5" />
            <span>{saving ? "保存中..." : isEdit ? "保存" : "创建"}</span>
          </button>
        </div>
      </div>

      {saveError && (
        <div className="shrink-0 border-b border-red-200 bg-red-50 px-5 py-2.5 text-sm text-red-700">
          <span className="font-medium">保存失败：</span>
          {saveError}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="grid min-h-full grid-cols-[minmax(0,1fr)_360px] gap-6 px-6 py-6">
          <div className="space-y-6">
            <nav aria-label="表单分区" className="sticky top-0 z-10 -mx-1 flex gap-1 rounded-md border border-border bg-white/95 p-1 shadow-sm backdrop-blur">
              {FORM_SECTIONS.map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className="rounded px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50 hover:text-accent"
                  onClick={() => document.getElementById(`form-${id}`)?.scrollIntoView?.({ behavior: "smooth", block: "start" })}
                >
                  {label}
                </button>
              ))}
            </nav>
            {(
              <>
                <section id="form-basic" className="scroll-mt-16 rounded-md border border-border bg-white p-5">
                  <div className="mb-2 text-sm font-semibold text-slate-900">基础设置</div>
                  <SectionIntro>
                    这里保存这个浏览器的身份信息。名称、分组、账号平台用于管理列表；浏览器模式、当前系统画像、User-Agent、Cookie 和启动页面会影响实际启动后的浏览器表现。
                  </SectionIntro>
                  <div className="grid max-w-3xl grid-cols-[120px_minmax(0,1fr)] items-start gap-x-5 gap-y-4">
                    <label className="pt-2 text-right text-sm font-medium text-slate-600">名称</label>
                    <div>
                      <input
                        className="input"
                        value={form.name}
                        onChange={(e) => set("name", e.target.value)}
                        placeholder="例如 Amazon Seller #1"
                        required
                      />
                      <FieldNote>只用于你自己识别这个浏览器，不会写入网页指纹。</FieldNote>
                    </div>

                    <label className="pt-2 text-right text-sm font-medium text-slate-600">分组</label>
                    <div>
                      <select
                        className="input max-w-xs"
                        value={form.group_name || "未分组"}
                        onChange={(e) => set("group_name", e.target.value)}
                      >
                        <option value="未分组">未分组</option>
                        {groups.map((group) => (
                          <option key={group.id} value={group.name}>{group.name}</option>
                        ))}
                      </select>
                      <FieldNote>用于左侧分组和列表筛选；需要新增分组时，在“分组管理”里创建。</FieldNote>
                    </div>

                    <label className="pt-2 text-right text-sm font-medium text-slate-600">账号平台</label>
                    <div>
                      <input
                        className="input max-w-xs"
                        list="account-platform-options"
                        value={form.account_platform ?? ""}
                        onChange={(e) => set("account_platform", e.target.value || null)}
                        placeholder="例如 阿里云 / Amazon"
                      />
                      <datalist id="account-platform-options">
                        {ACCOUNT_PLATFORM_OPTIONS.map((platform) => (
                          <option key={platform} value={platform} />
                        ))}
                      </datalist>
                      <FieldNote>用于列表页展示这个浏览器对应哪个平台账号；可以从建议里选，也可以自己输入。</FieldNote>
                    </div>

                    <label className="pt-2 text-right text-sm font-medium text-slate-600">浏览器</label>
                    <div>
                      <select
                        className="input max-w-xs"
                        value={currentEngine}
                        onChange={(e) => handleEngineChange(e.target.value as "system_chrome" | "cloakbrowser")}
                      >
                        <option value="system_chrome">稳定原生（系统 Chrome）</option>
                        <option value="cloakbrowser">伪装画像（CloakBrowser）</option>
                      </select>
                      <div className="mt-1 text-xs text-accent">
                        {currentEngine === "system_chrome"
                          ? "日常启动始终不打开外部 CDP。系统 Chrome 会使用语言参数和进程时区，但能否完整生效由本机 Chrome 决定，启动自检会如实报告。"
                          : "日常启动直接运行 CloakBrowser 二进制，不打开外部 CDP；语言和时区由底层参数统一应用到主页面、iframe 与 Worker。"}
                      </div>
                    </div>

                    <label className="pt-2 text-right text-sm font-medium text-slate-600">操作系统</label>
                    <div>
                      <div className="inline-flex items-center rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700">
                        {platformLabel(allowedPlatform)}
                      </div>
                      <FieldNote>已按当前电脑隔离：macOS 只显示 macOS 画像，Windows 只显示 Windows 画像，避免跨系统画像互相打架。</FieldNote>
                    </div>

                    <label className="pt-2 text-right text-sm font-medium text-slate-600">设备画像</label>
                    <div>
                      <select
                        className="input max-w-xl"
                        value={selectedDeviceProfile.id}
                        onChange={(e) => handleDeviceProfileChange(e.target.value)}
                      >
                        {platformFamilies.map((family) => (
                          <optgroup key={family} label={family}>
                            {platformProfiles.filter((preset) => preset.family === family).map((preset) => (
                              <option key={preset.id} value={preset.id}>{preset.name}</option>
                            ))}
                          </optgroup>
                        ))}
                      </select>
                      <FieldNote>一键套用屏幕、CPU、GPU 等同平台设备组合；原生模式主要作为管理元信息，伪装画像模式会写入可控参数。</FieldNote>
                    </div>

                    <label className="pt-2 text-right text-sm font-medium text-slate-600">User-Agent</label>
                    <div>
                      <input
                        className="input max-w-3xl font-mono text-xs"
                        value={form.user_agent ?? ""}
                        onChange={(e) => set("user_agent", e.target.value || null)}
                        placeholder="留空则跟随真实浏览器"
                      />
                      <FieldNote>建议留空跟随真实 Chrome；手动改错版本、系统或架构，反而会让 UA 和真实能力不一致。</FieldNote>
                    </div>

                    <label className="pt-2 text-right text-sm font-medium text-slate-600">启动页面</label>
                    <div>
                      <textarea
                        className="input min-h-24 max-w-3xl resize-y font-mono text-xs"
                        value={startupUrlsText}
                        onChange={(e) => updateStartupUrls(e.target.value)}
                        placeholder={"每行一个网址，例如：\nhttps://ip.skk.moe/\nhttps://pixelscan.net/fingerprint-check"}
                        spellCheck={false}
                      />
                      <FieldNote>没有恢复上次标签页时打开这些页面；留空会打开本地 IP、时间、语言自检页。</FieldNote>
                    </div>

                    <label className="pt-2 text-right text-sm font-medium text-slate-600">Cookie</label>
                    <div>
                      <textarea
                        className="input min-h-28 max-w-3xl resize-y font-mono text-xs"
                        value={form.cookies_json ?? ""}
                        onChange={(e) => set("cookies_json", e.target.value || null)}
                        placeholder={"支持 JSON、Netscape（cookies.txt）格式，保存时自动转成 JSON。\nName=Value 格式要指定网站，请用下面的「合并 Cookie」。"}
                        spellCheck={false}
                      />
                      <div className="mt-2 max-w-3xl">
                        <FieldNote>Cookie 会随配置保存；普通启动通过画像专用的本地扩展导入一次，调试启动通过浏览器上下文导入，之后由同一用户数据目录保存登录状态。浏览器里新产生的 Cookie 不会自动出现在这里，可用下面的「从浏览器导回 Cookie」读回（浏览器需正在运行：普通模式通过本地扩展导回，调试模式通过浏览器上下文导回）。</FieldNote>
                      </div>
                      <div className="mt-2 flex max-w-3xl flex-wrap items-center gap-2">
                        <button
                          type="button"
                          className="btn-secondary flex shrink-0 items-center gap-1 px-2.5 text-xs"
                          onClick={() => setCookieMerge((prev) => (prev ? null : { text: "", domain: defaultCookieDomain, busy: false, notice: null }))}
                        >
                          <Plus className="h-3.5 w-3.5" />
                          <span>合并 Cookie</span>
                        </button>
                        {profile && (
                          <>
                            <button
                              type="button"
                              className="btn-secondary flex shrink-0 items-center gap-1 px-2.5 text-xs disabled:opacity-60"
                              disabled={cookieBusy !== null}
                              onClick={() => void handlePullCookies()}
                            >
                              <Download className="h-3.5 w-3.5" />
                              <span>{cookieBusy === "pull" ? "导回中..." : "从浏览器导回 Cookie"}</span>
                            </button>
                            <span className="ml-auto flex shrink-0 items-center gap-2">
                              <select
                                className="input w-auto px-2 py-1 text-xs"
                                aria-label="导出格式"
                                value={cookieExportFormat}
                                onChange={(e) => setCookieExportFormat(e.target.value as CookieExportFormat)}
                              >
                                <option value="json">Cookie-Editor JSON</option>
                                <option value="netscape">cookies.txt</option>
                              </select>
                              <button
                                type="button"
                                className="btn-secondary flex items-center gap-1 px-2.5 text-xs disabled:opacity-60"
                                disabled={cookieBusy !== null}
                                onClick={() => void handleExportCookies()}
                              >
                                <FileDown className="h-3.5 w-3.5" />
                                <span>{cookieBusy === "export" ? "导出中..." : "导出 Cookie"}</span>
                              </button>
                            </span>
                          </>
                        )}
                      </div>
                      {cookieNotice && (
                        <div className={`mt-1.5 max-w-3xl text-xs ${cookieNotice.tone === "error" ? "text-red-600" : "text-emerald-700"}`}>
                          {cookieNotice.text}
                        </div>
                      )}
                      {cookieMerge && (
                        <div className="mt-2 max-w-3xl space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3">
                          <textarea
                            className="input min-h-24 w-full resize-y font-mono text-xs"
                            value={cookieMerge.text}
                            onChange={(e) => setCookieMerge({ ...cookieMerge, text: e.target.value, notice: null })}
                            placeholder={"粘贴要加进来的 Cookie：JSON、Netscape 或 Name=Value（如 sid=abc; lang=zh）"}
                            spellCheck={false}
                          />
                          <div className="flex flex-wrap items-center gap-2">
                            <input
                              className="input w-64 text-xs"
                              value={cookieMerge.domain}
                              onChange={(e) => setCookieMerge({ ...cookieMerge, domain: e.target.value })}
                              placeholder="网站域名（Name=Value 格式必填）"
                            />
                            <button
                              type="button"
                              className="btn-primary px-3 text-xs disabled:opacity-60"
                              disabled={cookieMerge.busy || !cookieMerge.text.trim()}
                              onClick={() => void handleMergeCookies()}
                            >
                              {cookieMerge.busy ? "合并中..." : "合并"}
                            </button>
                            {cookieMerge.notice && (
                              <span className={`text-xs ${cookieMerge.notice.tone === "error" ? "text-red-600" : "text-emerald-700"}`}>
                                {cookieMerge.notice.text}
                              </span>
                            )}
                          </div>
                          <FieldNote>同一网站、路径和名称的 Cookie 会被新的替换，其余保留。</FieldNote>
                        </div>
                      )}
                    </div>

                    <label className="pt-2 text-right text-sm font-medium text-slate-600">备注</label>
                    <div>
                      <textarea
                        className="input min-h-20 max-w-3xl resize-y"
                        value={form.notes ?? ""}
                        onChange={(e) => set("notes", e.target.value || null)}
                        placeholder="可选，写一些这个浏览器的用途..."
                      />
                      <FieldNote>只保存在 Manager 里，方便记录账号用途、注意事项或代理来源。</FieldNote>
                    </div>
                  </div>
                </section>
              </>
            )}

            {(
              <section id="form-proxy" className="scroll-mt-16 rounded-md border border-border bg-white p-5">
                <div className="mb-2 text-sm font-semibold text-slate-900">代理信息</div>
                <SectionIntro>
                  直连会使用当前电脑的本地网络，不启动代理或 Xray。普通 HTTP/HTTPS/SOCKS5 填主机端口；VLESS、VMess、Trojan、Shadowsocks 使用 Xray 链接。
                </SectionIntro>
                <div className="grid max-w-3xl grid-cols-[120px_minmax(0,1fr)] items-start gap-x-5 gap-y-4">
                  <label className="pt-2 text-right text-sm font-medium text-slate-600">代理方式</label>
                  <div>
                    <div className="flex max-w-xl rounded-md bg-slate-100 p-1">
                      {[
                        ["none", "直连"],
                        ["custom", "自定义代理"],
                        ["xray", "Xray 链接"],
                      ].map(([kind, label]) => (
                        <button
                          key={kind}
                          type="button"
                          onClick={() => updateProxyKind(kind as ProxyKind)}
                          aria-pressed={proxyParts.kind === kind}
                          className={`h-9 flex-1 rounded text-sm font-medium ${
                            proxyParts.kind === kind ? "bg-white text-accent shadow-sm" : "text-slate-600"
                          }`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    <FieldNote>直连不添加任何代理启动参数；自定义代理适合 HTTP/HTTPS/SOCKS5；Xray 链接会启动本地内核并转成本机 SOCKS5。</FieldNote>
                  </div>

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">已保存代理</label>
                  <div>
                    <select
                      className="input max-w-xl"
                      value=""
                      onChange={(e) => {
                        const preset = proxyPresets.find((item) => item.id === e.target.value);
                        if (!preset) return;
                        set("proxy", preset.proxy);
                        setProxyParts(parseProxy(preset.proxy));
                        setProxyTest(null);
                        setProxyTestError(null);
                      }}
                    >
                      <option value="">选择保存的代理...</option>
                      {proxyPresets.map((preset) => (
                        <option key={preset.id} value={preset.id}>{preset.name} · {preset.mode.toUpperCase()}</option>
                      ))}
                    </select>
                    <FieldNote>从“代理管理”保存的代理会出现在这里，选择后会自动填入当前浏览器。</FieldNote>
                  </div>

                  {proxyParts.kind === "none" ? (
                    <>
                      <label className="pt-2 text-right text-sm font-medium text-slate-600">连接状态</label>
                      <div className="flex max-w-xl items-start gap-3 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                        <Wifi className="mt-0.5 h-4 w-4 shrink-0" />
                        <div>
                          <div className="font-medium">直连已启用</div>
                          <div className="mt-1 text-xs leading-5 text-emerald-700">浏览器直接使用当前电脑的网络出口，不经过已保存代理，也不会启动 Xray。</div>
                        </div>
                      </div>
                    </>
                  ) : proxyParts.kind === "xray" ? (
                    <>
                      <label className="pt-2 text-right text-sm font-medium text-slate-600">代理链接</label>
                      <div>
                        <textarea
                          className="input min-h-28 max-w-3xl resize-y font-mono text-xs"
                          value={proxyParts.raw}
                          onChange={(e) => updateProxyPart("raw", e.target.value)}
                          placeholder="粘贴 ss://、vmess://、vless:// 或 trojan:// 链接"
                          spellCheck={false}
                        />
                        <div className="mt-1 text-xs text-slate-500">启动时会为这个浏览器创建独立的本机 SOCKS5 通道。</div>
                      </div>
                    </>
                  ) : (
                    <>
                      <label className="pt-2 text-right text-sm font-medium text-slate-600">代理类型</label>
                      <div>
                        <select
                          className="input max-w-sm"
                          value={proxyParts.scheme}
                          onChange={(e) => updateProxyPart("scheme", e.target.value as ProxyScheme)}
                        >
                          <option value="http">HTTP</option>
                          <option value="https">HTTPS</option>
                          <option value="socks5">SOCKS5</option>
                        </select>
                        <FieldNote>浏览器原生支持这三类代理；带账号密码的 SOCKS5 会自动走本地桥接，避免 Chrome 认证不稳定。</FieldNote>
                      </div>

                      <label className="pt-2 text-right text-sm font-medium text-slate-600">主机:端口</label>
                      <div>
                        <div className="grid max-w-xl grid-cols-[1fr_120px] gap-3">
                          <input
                            className="input"
                            value={proxyParts.host}
                            onChange={(e) => updateProxyPart("host", e.target.value)}
                            placeholder="192.168.100.1"
                          />
                          <input
                            className="input no-spin"
                            value={proxyParts.port}
                            onChange={(e) => updateProxyPart("port", e.target.value)}
                            placeholder="1090"
                          />
                        </div>
                        <FieldNote>软路由 Passwall、本机 Xray 或机场面板给出的可用地址都填这里；局域网地址要保证本机能连通。</FieldNote>
                      </div>

                      <label className="pt-2 text-right text-sm font-medium text-slate-600">代理账号</label>
                      <div>
                        <input
                          className="input max-w-xl"
                          value={proxyParts.username}
                          onChange={(e) => updateProxyPart("username", e.target.value)}
                          placeholder="可选"
                        />
                        <FieldNote>没有认证就留空；这里会自动拼进代理地址，不需要手动写 user:pass@。</FieldNote>
                      </div>

                      <label className="pt-2 text-right text-sm font-medium text-slate-600">代理密码</label>
                      <div>
                        <input
                          className="input max-w-xl"
                          type="password"
                          value={proxyParts.password}
                          onChange={(e) => updateProxyPart("password", e.target.value)}
                          placeholder="可选"
                        />
                        <FieldNote>密码只用于代理认证；保存后会写入本地配置数据库，请不要把项目目录公开上传。</FieldNote>
                      </div>
                    </>
                  )}

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">出口检测</label>
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={handleProxyTest}
                        disabled={testingProxy || (proxyParts.kind !== "none" && !form.proxy)}
                        className="btn-secondary flex items-center gap-1.5 disabled:opacity-60"
                      >
                        {testingProxy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
                        <span>{testingProxy ? "检查中..." : proxyParts.kind === "none" ? "检查直连出口" : "检查代理"}</span>
                      </button>
                      <span className="break-all text-xs text-slate-500">
                        {form.proxy ? form.proxy : "使用当前电脑网络检测公网 IP、国家、时区和语言"}
                      </span>
                    </div>
                    <FieldNote>保存前可以先检查一次；直连和代理都会在启动时重新检测出口。时区/语言留空时自动补全，开启“跟随出口 IP”时强制覆盖手动值。</FieldNote>
                    {proxyTestError && <div className="text-xs text-red-600">{proxyTestError}</div>}
                    {proxyTest && (
                      <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">
                        <div className="flex flex-wrap gap-x-4 gap-y-1">
                          <span>出口 IP：{proxyTest.ip ?? "未知"}</span>
                          <span>国家：{proxyTest.country ?? "未知"}</span>
                          <span>时区：{proxyTest.timezone ?? "未知"}</span>
                          <span>建议语言：{proxyTest.suggested_locale ?? "未知"}</span>
                        </div>
                        <button
                          type="button"
                          onClick={() => applyProxyGeo()}
                          disabled={!proxyTest.timezone && !proxyTest.suggested_locale}
                          className="mt-2 inline-flex items-center gap-1.5 text-accent disabled:opacity-60"
                        >
                          <Globe className="h-3.5 w-3.5" />
                          <span>应用到时区和语言</span>
                        </button>
                      </div>
                    )}
                    {proxyTest?.ip_quality && <IpQualityPanel quality={proxyTest.ip_quality} />}
                  </div>

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">时区语言</label>
                  <div>
                    <div className="grid max-w-xl grid-cols-2 gap-3">
                      <input
                        className="input"
                        value={form.timezone ?? ""}
                        onChange={(e) => set("timezone", e.target.value || null)}
                        placeholder="Asia/Shanghai"
                      />
                      <input
                        className="input"
                        value={form.locale ?? ""}
                        onChange={(e) => set("locale", e.target.value || null)}
                        placeholder="zh-CN"
                      />
                    </div>
                    <FieldNote>左边填 IANA 时区，例如 Asia/Hong_Kong；右边填浏览器语言，例如 zh-HK。留空时按当前出口 IP 自动补全；手动填写时仅在开启“跟随出口 IP”后被覆盖。</FieldNote>
                  </div>

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">跟随 IP</label>
                  <div>
                    <label className="flex items-center gap-2 text-sm text-slate-700">
                      <input
                        type="checkbox"
                        checked={form.geoip ?? false}
                        onChange={(e) => set("geoip", e.target.checked)}
                        className="rounded border-slate-300"
                      />
                      根据出口 IP 自动匹配时区和语言区域
                    </label>
                    <FieldNote>适用于直连和代理。勾选后强制覆盖手动值；不勾选时，只要时区或语言留空，启动时也会按出口地区自动补全。</FieldNote>
                  </div>

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">浏览器语言</label>
                  <div>
                    <select
                      className="input max-w-xl"
                      aria-label="浏览器语言"
                      value={fingerprintOptions.language ?? ""}
                      onChange={(e) => setOption("language", e.target.value || null)}
                    >
                      {BROWSER_LANGUAGES.map(([value, label]) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </select>
                    <FieldNote>
                      想看懂菜单和设置页时选中文：浏览器界面、网页读到的语言和日期格式会一起换成中文，时区仍按出口 IP。只换界面、网页语言留日语会被检测网站判为语言不一致，所以三者一起换。也可以在浏览器设置页「语言」里加中文：放在第一位后浏览器会在几秒内自动重启，整个浏览器（含菜单）变成中文，标签页会恢复；放在后面只作备用语言，可配合 Google 翻译。
                    </FieldNote>
                  </div>
                </div>
              </section>
            )}

            {(
              <section id="form-fingerprint" className="scroll-mt-16 rounded-md border border-border bg-white p-5">
                <div className="mb-2 text-sm font-semibold text-slate-900">指纹配置</div>
                <div className="mb-5 rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-800">
                  设备画像决定当前系统下的屏幕、CPU、GPU 这些看得见的参数；稳定种子只决定同一画像里的 Canvas / Audio 等稳定细节。改完需要保存并重新启动浏览器才会影响实际打开的浏览器。
                </div>
                <div className="mb-5 grid max-w-3xl grid-cols-2 gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs">
                  {fingerprintPreviewRows.map(([label, value]) => (
                    <div key={label} className="grid grid-cols-[86px_minmax(0,1fr)] gap-2 rounded bg-white px-3 py-2">
                      <span className="text-slate-400">{label}</span>
                      <span className="break-words font-medium text-slate-700">{value}</span>
                    </div>
                  ))}
                </div>
                <div className="grid max-w-3xl grid-cols-[120px_minmax(0,1fr)] items-start gap-x-5 gap-y-4">
                  <label className="pt-2 text-right text-sm font-medium text-slate-600">稳定种子</label>
                  <div>
                    <div className="flex max-w-sm gap-2">
                      <input
                        className="input flex-1 no-spin"
                        type="number"
                        value={form.fingerprint_seed ?? ""}
                        onChange={(e) => set("fingerprint_seed", e.target.value ? Number(e.target.value) : null)}
                        placeholder="自动随机"
                      />
                      <button type="button" onClick={randomizeSeed} className="btn-secondary px-2.5" title="重新生成稳定种子">
                        <RefreshCw className="h-4 w-4" />
                      </button>
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {currentEngine === "cloakbrowser"
                        ? "它不会改变上面的设备画像、CPU、GPU 或分辨率；只让同一套画像的细节输出保持稳定。想换整套画像，用右侧概要里的“随机设备画像”。"
                        : "原生模式使用真实 Chrome 和真实硬件输出，这个值主要用于记录，不会强行改变你的真实 CPU、GPU 或 Canvas。"}
                    </div>
                  </div>

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">分辨率</label>
                  <div>
                    <select
                      className="input max-w-xl"
                      aria-label="分辨率"
                      value={screenFollowsDisplay ? "real" : currentResolution}
                      onChange={(e) => {
                        if (e.target.value === "real") {
                          setOption("screen", "real");
                          return;
                        }
                        setOption("screen", "custom");
                        const preset = RESOLUTION_PRESETS[e.target.value];
                        if (preset) {
                          set("screen_width", preset.width);
                          set("screen_height", preset.height);
                        }
                      }}
                    >
                      {currentEngine === "cloakbrowser" && realScreen && (
                        <option value="real">跟随电脑屏幕 {realScreen[0]} × {realScreen[1]}（推荐）</option>
                      )}
                      {Object.keys(RESOLUTION_PRESETS).map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                      <option value="custom">自定义</option>
                    </select>
                    <div className="mt-1 text-xs text-slate-500">
                      {screenFollowsDisplay
                        ? "每次启动时读取这台电脑主显示器的分辨率。检测网站能通过 CSS 媒体查询读到真实屏幕，自定义的分辨率和它对不上会被判为指纹不一致。"
                        : "这里填写浏览器看到的逻辑分辨率，不是 Retina 面板物理像素。例如 MacBook Pro 14 默认常见 1512 × 982。"}
                    </div>
                  </div>

                  {!screenFollowsDisplay && currentResolution === "custom" && (
                    <>
                      <label className="pt-2 text-right text-sm font-medium text-slate-600">宽高</label>
                      <div>
                        <div className="grid max-w-sm grid-cols-2 gap-3">
                          <input
                            className="input no-spin"
                            type="number"
                            value={form.screen_width ?? 1920}
                            onChange={(e) => set("screen_width", Number(e.target.value))}
                          />
                          <input
                            className="input no-spin"
                            type="number"
                            value={form.screen_height ?? 1080}
                            onChange={(e) => set("screen_height", Number(e.target.value))}
                          />
                        </div>
                        <FieldNote>自定义宽高会直接影响窗口尺寸和 screen 相关字段，建议只填真实设备常见比例。</FieldNote>
                      </div>
                    </>
                  )}

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">CPU</label>
                  <div>
                    <input
                      className="input max-w-sm no-spin"
                      type="number"
                      value={form.hardware_concurrency ?? ""}
                      onChange={(e) => set("hardware_concurrency", e.target.value ? Number(e.target.value) : null)}
                      placeholder="按画像或真实设备"
                    />
                    <div className="mt-1 text-xs text-slate-500">留空表示稳定原生使用真实 CPU；伪装画像会按当前系统画像预设推荐线程数。</div>
                  </div>

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">浏览器内存</label>
                  <div>
                    <select
                      className="input max-w-sm"
                      value={form.device_memory ?? ""}
                      onChange={(e) => set("device_memory", e.target.value ? Number(e.target.value) : null)}
                    >
                      <option value="">按真实设备</option>
                      <option value="2">2 GB</option>
                      <option value="4">4 GB</option>
                      <option value="8">8 GB</option>
                    </select>
                    <div className="mt-1 text-xs text-slate-500">Chrome 的 navigator.deviceMemory 只暴露粗略值并且最高为 8 GB；画像默认使用 8，不虚构 16/32/64 GB。</div>
                  </div>

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">GPU 预设</label>
                  <div>
                    <select
                      className="input max-w-xl"
                      value=""
                      onChange={(e) => {
                        const name = e.target.value;
                        if (name) applyGpuPreset(name);
                        // Reset the control so the same preset can be applied
                        // again even after the field already holds its value.
                        e.target.value = "";
                      }}
                    >
                      <option value="">选择预设...</option>
                      {Object.keys(GPU_PRESETS).map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                    </select>
                    <div className="mt-1 text-xs text-slate-500">GPU 预设会同时填充厂商和渲染器，避免厂商、芯片和 WebGL 信息互相打架。</div>
                  </div>

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">GPU 厂商</label>
                  <div>
                    <input
                      className="input max-w-3xl"
                      value={form.gpu_vendor ?? ""}
                      onChange={(e) => set("gpu_vendor", e.target.value || null)}
                      placeholder="按画像或真实设备"
                    />
                    <div className="mt-1 text-xs text-slate-500">通常不用手动改；只有选择伪装画像并且明确知道目标设备时才建议填写。</div>
                  </div>

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">GPU 渲染器</label>
                  <div>
                    <input
                      className="input max-w-3xl"
                      value={form.gpu_renderer ?? ""}
                      onChange={(e) => set("gpu_renderer", e.target.value || null)}
                      placeholder="按画像或真实设备"
                    />
                    <div className="mt-1 text-xs text-slate-500">这是 WebGL 元数据里最显眼的硬件信息，必须和当前系统画像保持一致。</div>
                  </div>
                </div>
              </section>
            )}

            {currentEngine === "cloakbrowser" ? (
              <section id="form-more-fingerprint" className="scroll-mt-16 rounded-md border border-border bg-white p-5">
                <div className="mb-2 text-sm font-semibold text-slate-900">更多指纹</div>
                <SectionIntro>
                  这些是 CloakBrowser 内核自带的额外伪装项，全部留默认时由内核按稳定种子自动生成，已经是一套一致的指纹；只在明确知道需要时才改。
                </SectionIntro>
                <div className="grid max-w-3xl grid-cols-[120px_minmax(0,1fr)] items-start gap-x-5 gap-y-4">
                  <label className="pt-2 text-right text-sm font-medium text-slate-600">浏览器品牌</label>
                  <div>
                    <div className="flex max-w-xl gap-2">
                      <select
                        className="input w-44"
                        value={fingerprintOptions.brand ?? ""}
                        onChange={(e) => setOption("brand", (e.target.value || null) as FingerprintOptions["brand"])}
                      >
                        <option value="">Chrome（默认）</option>
                        <option value="Edge">Microsoft Edge</option>
                        <option value="Opera">Opera</option>
                        <option value="Vivaldi">Vivaldi</option>
                      </select>
                      <input
                        className="input flex-1"
                        value={fingerprintOptions.brand_version ?? ""}
                        onChange={(e) => setOption("brand_version", e.target.value || null)}
                        placeholder="品牌版本号，留空跟随内核"
                      />
                    </div>
                    <FieldNote>改的是 User-Agent 和 Client Hints 里的浏览器名称与版本，内核本身不变。</FieldNote>
                  </div>

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">系统版本</label>
                  <div>
                    <input
                      className="input max-w-sm"
                      list="platform-version-options"
                      value={fingerprintOptions.platform_version ?? ""}
                      onChange={(e) => setOption("platform_version", e.target.value.trim() || null)}
                      placeholder="留空由内核决定"
                    />
                    <datalist id="platform-version-options">
                      {(form.platform === "macos" ? MAC_PLATFORM_VERSIONS : WINDOWS_PLATFORM_VERSIONS).map(([value, label]) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </datalist>
                    <FieldNote>
                      {form.platform === "macos"
                        ? "Client Hints 里的 macOS 版本，例如 15.6.0 表示 macOS 15。"
                        : "Client Hints 里的 Windows 版本：10.0.0 是 Windows 10，13.0.0 以上是 Windows 11。"}
                    </FieldNote>
                  </div>

                  <label className="pt-1.5 text-right text-sm font-medium text-slate-600">地理位置</label>
                  <div>
                    <Segmented
                      label="地理位置"
                      value={fingerprintOptions.geolocation ?? "ip"}
                      options={[["ip", "基于 IP"], ["block", "禁止"], ["real", "真实"]]}
                      onChange={(value) => setOption("geolocation", value)}
                    />
                    <FieldNote>
                      {(fingerprintOptions.geolocation ?? "ip") === "ip"
                        ? "网页请求定位时，调试启动返回出口 IP 所在城市的坐标；普通启动改不了坐标，会直接拒绝定位，不暴露真实位置。"
                        : (fingerprintOptions.geolocation ?? "ip") === "block"
                        ? "所有网站请求定位都直接拒绝。"
                        : "和普通 Chrome 一样，网站请求时由你决定是否给出电脑的真实位置。用代理时不建议。"}
                    </FieldNote>
                  </div>

                  <label className="pt-1.5 text-right text-sm font-medium text-slate-600">WebRTC</label>
                  <div>
                    <Segmented
                      label="WebRTC"
                      value={fingerprintOptions.webrtc ?? "proxy"}
                      options={[["proxy", "跟随出口 IP"], ["custom", "指定 IP"]]}
                      onChange={(value) => setForm((prev) => ({
                        ...prev,
                        fingerprint_options: {
                          ...(prev.fingerprint_options ?? {}),
                          webrtc: value,
                          webrtc_ip: value === "custom" ? prev.fingerprint_options?.webrtc_ip ?? "" : null,
                        },
                      }))}
                    />
                    {fingerprintOptions.webrtc === "custom" && (
                      <input
                        className="input mt-2 max-w-sm"
                        value={fingerprintOptions.webrtc_ip ?? ""}
                        onChange={(e) => setOption("webrtc_ip", e.target.value)}
                        placeholder="例如 203.0.113.9"
                      />
                    )}
                    <FieldNote>
                      {fingerprintOptions.webrtc === "custom"
                        ? "网页通过 WebRTC 看到的公网 IP 固定为这里填的地址。"
                        : "用代理时网页通过 WebRTC 看到的是代理出口 IP，防止泄露真实 IP；直连时保持真实。"}
                    </FieldNote>
                  </div>

                  <label className="pt-1.5 text-right text-sm font-medium text-slate-600">指纹噪声</label>
                  <div>
                    <Segmented
                      label="指纹噪声"
                      value={fingerprintOptions.noise == null ? "auto" : fingerprintOptions.noise ? "on" : "off"}
                      options={[["auto", "自动"], ["on", "开启"], ["off", "关闭"]]}
                      onChange={(value) => setOption("noise", value === "auto" ? null : value === "on")}
                    />
                    <FieldNote>噪声让每个画像的 Canvas、WebGL、音频输出各不相同。实测多数现代检测器对噪声净扣分，新建画像默认关闭；想回到内核默认可随时切换回「自动」；macOS 画像默认关闭。</FieldNote>
                  </div>

                  <label className="pt-1.5 text-right text-sm font-medium text-slate-600">存储配额</label>
                  <div>
                    <Segmented
                      label="存储配额"
                      value={fingerprintOptions.storage_quota_mb == null ? "auto" : "custom"}
                      options={[["auto", "按种子自动"], ["custom", "自定义"]]}
                      onChange={(value) => setOption("storage_quota_mb", value === "auto" ? null : 50000)}
                    />
                    {fingerprintOptions.storage_quota_mb != null && (
                      <input
                        className="input mt-2 max-w-sm no-spin"
                        type="number"
                        min={100}
                        value={fingerprintOptions.storage_quota_mb}
                        onChange={(e) => setOption("storage_quota_mb", e.target.value ? Number(e.target.value) : null)}
                        placeholder="单位 MB"
                      />
                    )}
                    <FieldNote>navigator.storage.estimate() 报告的磁盘配额，单位 MB。真实电脑通常是几十 GB 以上；新建画像默认 50000（≈50 GB），实测可消除 BrowserScan 的无痕模式扣分。</FieldNote>
                  </div>

                  <label className="pt-1.5 text-right text-sm font-medium text-slate-600">任务栏高度</label>
                  <div>
                    <Segmented
                      label="任务栏高度"
                      value={fingerprintOptions.taskbar_height == null ? "auto" : "custom"}
                      options={[["auto", form.platform === "macos" ? "系统默认（95）" : "系统默认（48）"], ["custom", "自定义"]]}
                      onChange={(value) => setOption("taskbar_height", value === "auto" ? null : form.platform === "macos" ? 95 : 48)}
                    />
                    {fingerprintOptions.taskbar_height != null && (
                      <input
                        className="input mt-2 max-w-sm no-spin"
                        type="number"
                        min={0}
                        max={300}
                        value={fingerprintOptions.taskbar_height}
                        onChange={(e) => setOption("taskbar_height", e.target.value ? Number(e.target.value) : null)}
                        placeholder="单位像素"
                      />
                    )}
                    <FieldNote>决定 screen.availHeight 比屏幕高度少多少像素，一般不用改。</FieldNote>
                  </div>

                  <label className="pt-0.5 text-right text-sm font-medium text-slate-600">兼容选项</label>
                  <div className="space-y-3">
                    {form.platform === "windows" && (
                      <OptionCheckbox
                        checked={fingerprintOptions.speech_voices ?? true}
                        onChange={(value) => setOption("speech_voices", value)}
                        title="Windows 语音列表"
                        note="让 speechSynthesis 报告和真实 Windows Chrome 一样的语音。某个网站因此异常时再关闭。"
                      />
                    )}
                    <OptionCheckbox
                      checked={fingerprintOptions.allow_3p_cookies ?? false}
                      onChange={(value) => setOption("allow_3p_cookies", value)}
                      title="允许第三方 Cookie"
                      note="只在 reCAPTCHA、单点登录或支付验证一直转圈完成不了时打开。"
                    />
                    <OptionCheckbox
                      checked={fingerprintOptions.transparent_proxy ?? false}
                      onChange={(value) => setOption("transparent_proxy", value)}
                      disabled={!form.proxy}
                      title="透明代理"
                      note={form.proxy ? "更隐蔽的代理连接方式，用于换了好几个代理都被网站识别的情况。" : "需要先设置代理。"}
                    />
                    <OptionCheckbox
                      checked={fingerprintOptions.portable_cookies ?? false}
                      onChange={(value) => setOption("portable_cookies", value)}
                      title="跨电脑 Cookie"
                      note="用和电脑无关的密钥加密 Cookie，把画像搬到另一台电脑（例如从 Mac 到 Windows）后登录还在。只对开启之后保存的 Cookie 有效，新画像建议一开始就打开。"
                    />
                    {form.platform === "windows" && hostOS === "linux" && (
                      <OptionCheckbox
                        checked={fingerprintOptions.windows_font_metrics ?? false}
                        onChange={(value) => setOption("windows_font_metrics", value)}
                        title="Windows 字体度量"
                        note="Linux 上伪装 Windows 时对齐字体尺寸，需要先装好 Windows 字体。"
                      />
                    )}
                  </div>
                </div>
              </section>
            ) : (
              <section id="form-more-fingerprint" className="scroll-mt-16 rounded-md border border-border bg-white px-5 py-4 text-xs leading-5 text-slate-500">
                「稳定原生」使用电脑上的 Google Chrome 和真实硬件，不支持浏览器品牌、WebRTC IP 等额外伪装项；需要时把浏览器切换为「伪装画像」。
              </section>
            )}

            {(
              <section id="form-advanced" className="scroll-mt-16 rounded-md border border-border bg-white p-5">
                <div className="mb-2 text-sm font-semibold text-slate-900">高级设置</div>
                <SectionIntro>
                  默认已经按日常本地使用调好：真人操作辅助和 VNC 剪贴板同步会自动开启；启动参数属于工程级选项，不清楚用途就保持为空。
                </SectionIntro>
                <div className="space-y-6">
                  <div className="grid max-w-3xl grid-cols-[120px_minmax(0,1fr)] items-start gap-x-5 gap-y-4">
                    <label className="pt-2 text-right text-sm font-medium text-slate-600">行为辅助</label>
                    <div className="space-y-3">
                      <div className="border-b border-slate-100 pb-3">
                        <label className="flex items-start gap-3 text-sm text-slate-800">
                          <input
                            type="checkbox"
                            checked={form.humanize ?? false}
                            onChange={(e) => set("humanize", e.target.checked)}
                            className="mt-1 rounded border-slate-300"
                          />
                          <span className="min-w-0">
                            <span className="flex items-center gap-1.5 font-medium">
                              <MousePointer2 className="h-4 w-4 text-accent" />
                              模拟真人鼠标、键盘和滚动行为
                            </span>
                            <span className="mt-1 block text-xs leading-5 text-slate-500">
                              新建浏览器默认开启，让 Manager 控制和 VNC 远程操作更自然平滑；它不等于保证通过网站风控。
                            </span>
                          </span>
                        </label>
                      </div>
                      {form.humanize && (
                        <div className="grid max-w-xl grid-cols-[92px_minmax(0,1fr)] items-center gap-3">
                          <div className="text-xs font-medium text-slate-500">行为速度</div>
                          <select
                            className="input"
                            value={form.human_preset}
                            onChange={(e) => set("human_preset", e.target.value)}
                          >
                            <option value="default">默认（正常速度）</option>
                            <option value="careful">谨慎（更慢、更稳）</option>
                          </select>
                        </div>
                      )}
                      <div className="border-b border-slate-100 py-3">
                        <label className="flex items-start gap-3 text-sm text-slate-800">
                          <input
                            type="checkbox"
                            checked={form.clipboard_sync ?? true}
                            onChange={(e) => set("clipboard_sync", e.target.checked)}
                            className="mt-1 rounded border-slate-300"
                          />
                          <span className="min-w-0">
                            <span className="flex items-center gap-1.5 font-medium">
                              <ClipboardCheck className="h-4 w-4 text-accent" />
                              默认启用 VNC 剪贴板同步
                            </span>
                            <span className="mt-1 block text-xs leading-5 text-slate-500">
                              用远程/VNC 画面时，可以在本机和浏览器之间复制粘贴文本；本机原生 Chrome 窗口基本无感，保持开启即可。
                            </span>
                          </span>
                        </label>
                      </div>
                      <div className="pt-3">
                        <label className="flex items-start gap-3 text-sm text-slate-800">
                          <input
                            type="checkbox"
                            checked={form.auto_launch ?? false}
                            onChange={(e) => set("auto_launch", e.target.checked)}
                            className="mt-1 rounded border-slate-300"
                          />
                          <span className="min-w-0">
                            <span className="font-medium">Manager 启动后自动打开</span>
                            <span className="mt-1 block text-xs leading-5 text-slate-500">
                              只有常用固定浏览器才建议开启；否则 Manager 启动时会自动把这个浏览器拉起来。
                            </span>
                          </span>
                        </label>
                      </div>
                      <div className="pt-3">
                        <label className="flex items-start gap-3 text-sm text-slate-800">
                          <input
                            type="checkbox"
                            checked={form.warmup_enabled ?? false}
                            onChange={(e) => set("warmup_enabled", e.target.checked)}
                            className="mt-1 rounded border-slate-300"
                          />
                          <span className="min-w-0">
                            <span className="font-medium">养号（定时自动浏览养护）</span>
                            <span className="mt-1 block text-xs leading-5 text-slate-500">
                              开启后，Manager 会按计划在后台无头打开这个浏览器（不弹出窗口、不打扰你），像真人一样浏览与它地区相符的站点和下方勾选的目标平台，让第一方 Cookie 自然积累年龄。全程不登录、不下单、不发帖，只浏览与搜索；浏览器正在使用或授权并发已满时自动跳过。
                            </span>
                          </span>
                        </label>
                        {form.warmup_enabled && (
                          <div className="mt-3 space-y-3 pl-7">
                            <label className="flex items-center gap-2 text-sm text-slate-700">
                              每天最多
                              <select
                                className="input w-24"
                                value={form.warmup_daily_max ?? 1}
                                onChange={(e) => set("warmup_daily_max", Number(e.target.value))}
                              >
                                {[1, 2, 3].map((n) => (
                                  <option key={n} value={n}>{n} 次</option>
                                ))}
                              </select>
                            </label>
                            <div>
                              <div className="text-sm font-medium text-slate-800">画像人格（可选）</div>
                              <p className="mt-1 text-xs leading-5 text-slate-500">
                                一句话描述这个画像的人设；AI 养号编排会按它编排一周剧本的主题和搜索词，不填则按地区与语言生成通用剧本。
                              </p>
                              <input
                                className="input mt-2 w-full max-w-md"
                                value={form.warmup_persona ?? ""}
                                maxLength={200}
                                onChange={(e) => set("warmup_persona", e.target.value)}
                                placeholder="如：32 岁，台北，喜欢摄影和手冲咖啡"
                              />
                            </div>
                            <div>
                              <div className="text-sm font-medium text-slate-800">定向养护平台</div>
                              <p className="mt-1 text-xs leading-5 text-slate-500">
                                定向养护：在目标平台留下并积累第一方 Cookie 年龄（如 Facebook 的 datr、Amazon 的 session-id），让后续正式使用时不像全新设备。
                              </p>
                              <div className="mt-2 flex flex-wrap gap-2">
                                {warmupCatalog.map((target) => {
                                  const active = (form.warmup_targets ?? []).includes(target.id);
                                  return (
                                    <button
                                      key={target.id}
                                      type="button"
                                      onClick={() => {
                                        const current = form.warmup_targets ?? [];
                                        set("warmup_targets", active ? current.filter((t) => t !== target.id) : [...current, target.id]);
                                      }}
                                      className={active ? "rounded-full bg-accent px-3 py-1 text-xs font-medium text-white" : "rounded-full border border-slate-300 px-3 py-1 text-xs text-slate-600"}
                                    >
                                      {target.name}
                                    </button>
                                  );
                                })}
                                {warmupCatalog.length === 0 && (
                                  <span className="text-xs text-slate-400">平台目录加载中…</span>
                                )}
                              </div>
                            </div>
                            {profile && warmupInfo && (
                              <div className="rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600">
                                <div>
                                  创建于 {warmupInfo.age.created_at?.slice(0, 10) ?? "—"}
                                  {warmupInfo.age.age_days != null && `（${warmupInfo.age.age_days} 天）`}
                                  {" · "}已养号 {warmupInfo.age.warmup_sessions} 次
                                  {" · "}最近活动 {warmupInfo.age.last_warmup_at ? warmupInfo.age.last_warmup_at.slice(0, 16).replace("T", " ") : "暂无"}
                                </div>
                                {warmupInfo.runs.length > 0 && (
                                  <ul className="mt-2 space-y-1">
                                    {warmupInfo.runs.slice(0, 5).map((run) => (
                                      <li key={run.id}>
                                        {run.started_at.slice(0, 16).replace("T", " ")}
                                        {" · "}{run.status === "ok" ? "完成" : run.status === "skipped" ? "跳过" : "失败"}
                                        {run.status === "ok" && ` · ${run.pages_visited} 页`}
                                        {run.reason && ` · ${run.reason}`}
                                      </li>
                                    ))}
                                  </ul>
                                )}
                                <button
                                  type="button"
                                  disabled={warmupRunning || warmupInfo.warming}
                                  onClick={async () => {
                                    setWarmupRunning(true);
                                    try {
                                      await api.runProfileWarmupNow(profile.id);
                                      const info = await api.getProfileWarmup(profile.id);
                                      setWarmupInfo(info);
                                    } catch {
                                      // 下次打开表单时会看到最新状态
                                    } finally {
                                      setWarmupRunning(false);
                                    }
                                  }}
                                  className="mt-2 rounded border border-slate-300 px-3 py-1 text-xs text-slate-700 disabled:opacity-50"
                                >
                                  {warmupInfo.warming ? "正在养号…" : "立即养一次"}
                                </button>
                                <div className="mt-2">
                                  <AutomationHoursHint />
                                </div>
                                <WarmupScriptsSection profileId={profile.id} />
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>

                    <label className="pt-2 text-right text-sm font-medium text-slate-600">颜色偏好</label>
                    <div>
                      <select
                        className="input max-w-sm"
                        value={form.color_scheme ?? ""}
                        onChange={(e) => set("color_scheme", e.target.value || null)}
                      >
                        <option value="">跟随系统</option>
                        <option value="light">浅色</option>
                        <option value="dark">深色</option>
                        <option value="no-preference">无偏好</option>
                      </select>
                      <FieldNote>对应网页里的 prefers-color-scheme 偏好；不确定就选跟随系统。</FieldNote>
                    </div>

                    <label className="pt-2 text-right text-sm font-medium text-slate-600">扩展目录</label>
                    <div>
                      <textarea
                        className="input min-h-24 max-w-2xl resize-y font-mono text-xs"
                        value={extensionPaths.join("\n")}
                        onChange={(event) => updateExtensionPaths(event.target.value)}
                        placeholder={hostOS === "windows" ? "每行一个目录，例如 C:\\Extensions\\MyExtension" : "每行一个目录，例如 /Users/name/Extensions/MyExtension"}
                        spellCheck={false}
                      />
                      <FieldNote>每行填写一个已经解压的 Chrome 扩展目录。Manager 会自动生成启动参数；扩展目录移动或删除后需要在这里同步修改。</FieldNote>
                    </div>

                    <label className="pt-2 text-right text-sm font-medium text-slate-600">高级启动</label>
                    <div>
                      <details
                        className="group max-w-2xl border-t border-slate-100 pt-3"
                        open={launchArgsOpen}
                        onToggle={(e) => setLaunchArgsOpen(e.currentTarget.open)}
                      >
                        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium text-slate-700">
                          <span className="flex items-center gap-1.5">
                            <Settings2 className="h-4 w-4 text-slate-400" />
                            启动参数
                          </span>
                          <span className="text-xs font-normal text-slate-400 group-open:hidden">展开</span>
                          <span className="hidden text-xs font-normal text-slate-400 group-open:inline">收起</span>
                        </summary>
                        <div className="mt-3">
                          {(form.launch_args ?? []).length > 0 && (
                            <div className="mb-3 flex flex-wrap gap-1.5">
                              {(form.launch_args ?? []).map((arg, idx) => (
                                <span
                                  key={idx}
                                  className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-700"
                                >
                                  {arg}
                                  <button type="button" onClick={() => removeLaunchArg(idx)} className="hover:opacity-70" title="移除启动参数">
                                    <X className="h-3 w-3" />
                                  </button>
                                </span>
                              ))}
                            </div>
                          )}
                          <div className="flex gap-2">
                            <input
                              className="input flex-1 font-mono"
                              value={launchArgInput}
                              onChange={(e) => setLaunchArgInput(e.target.value)}
                              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addLaunchArg(); } }}
                              placeholder="--load-extension=/path/to/extension"
                            />
                            <button type="button" onClick={addLaunchArg} className="btn-secondary px-2.5" title="添加启动参数">
                              <Plus className="h-4 w-4" />
                            </button>
                          </div>
                          <FieldNote>
                            这里会把参数直接追加给 Chrome，常见用途是加载本地扩展或临时实验开关；普通用户留空最稳。
                          </FieldNote>
                        </div>
                      </details>
                    </div>
                  </div>
                </div>
              </section>
            )}
          </div>

          <aside className="sticky top-6 h-[calc(100vh-140px)] overflow-y-auto rounded-md border border-border bg-white p-5">
            <div className="mb-4 flex items-center justify-between border-b border-border pb-3">
              <div className="text-base font-semibold text-slate-900">概要</div>
              {currentEngine === "cloakbrowser" ? (
                <button type="button" onClick={randomizeDeviceProfile} className="text-sm font-medium text-accent">
                  随机设备画像
                </button>
              ) : (
                <span className="text-xs text-slate-400">原生模式使用真实设备</span>
              )}
            </div>
            <div className="space-y-3 text-sm">
              {summaryRows.map(([label, value]) => (
                <div key={label} className="grid grid-cols-[92px_minmax(0,1fr)] gap-3">
                  <div className="text-slate-400">{label}</div>
                  <div className="break-words text-right font-medium text-slate-700">{value}</div>
                </div>
              ))}
            </div>
          </aside>
        </div>
      </div>
    </form>
  );
}
