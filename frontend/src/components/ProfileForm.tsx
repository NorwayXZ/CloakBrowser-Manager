import { ArrowLeft, ClipboardCheck, Globe, Loader2, MousePointer2, Plus, RefreshCw, Save, Settings2, Trash2, Wifi, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import {
  api,
  type HostOS,
  type Profile,
  type ProfileCreateData,
  type ProfileGroup,
  type ProxyPreset,
  type ProxyTestResult,
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
}

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

type ProxyKind = "direct" | "xray";
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
  kind: "direct",
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

function platformLabel(platform: DevicePlatform): string {
  return platform === "windows" ? "Windows" : "macOS";
}

function createDefaultForm(hostOS?: HostOS | null): ProfileCreateData {
  return applyDeviceProfile({
    name: "",
    browser_engine: "cloakbrowser",
    humanize: true,
    human_preset: "default",
    headless: false,
    geoip: false,
    clipboard_sync: true,
    auto_launch: false,
    group_name: "未分组",
    account_platform: null,
    cookies_json: null,
    startup_urls: [],
    launch_args: [],
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
          kind: "direct",
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
      kind: "direct",
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
      kind: "direct",
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
}: ProfileFormProps) {
  const isEdit = profile !== null;
  const allowedPlatform = getDevicePlatformForHost(hostOS);

  const [form, setForm] = useState<ProfileCreateData>(() => createDefaultForm(hostOS));
  const [proxyParts, setProxyParts] = useState<ProxyParts>(() => parseProxy(profile?.proxy));
  const [proxyTest, setProxyTest] = useState<ProxyTestResult | null>(null);
  const [proxyTestError, setProxyTestError] = useState<string | null>(null);
  const [testingProxy, setTestingProxy] = useState(false);

  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [launchArgInput, setLaunchArgInput] = useState("");
  const [launchArgsOpen, setLaunchArgsOpen] = useState(false);
  const [startupUrlsText, setStartupUrlsText] = useState("");
  const [draftProfileId, setDraftProfileId] = useState<string | null>(null);

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
        humanize: profile.humanize,
        human_preset: profile.human_preset,
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const safeForm = form.platform === allowedPlatform && form.device_profile === selectedDeviceProfile.id
        ? form
        : applyDeviceProfile(form, selectedDeviceProfile);
      await onSave(safeForm);
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
    set("proxy", next.kind === "xray" ? (next.raw.trim() || null) : buildProxy(next));
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
    set("proxy", kind === "xray" ? (next.raw.trim() || null) : buildProxy(next));
    setProxyTest(null);
    setProxyTestError(null);
  };

  const applyProxyGeo = (result: ProxyTestResult | null = proxyTest) => {
    if (!result) return;
    if (result.timezone) set("timezone", result.timezone);
    if (result.suggested_locale) set("locale", result.suggested_locale);
  };

  const handleProxyTest = async () => {
    if (!form.proxy) {
      setProxyTest(null);
      setProxyTestError("请先填写代理主机和端口");
      return;
    }
    setTestingProxy(true);
    setProxyTest(null);
    setProxyTestError(null);
    try {
      const result = await api.testProxy(form.proxy);
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
  const proxyGeoFallbackLabel = form.geoip ? "代理 IP 自动覆盖" : "代理 IP 自动补全";
  const effectiveTimezonePreview = form.timezone
    || proxyTest?.timezone
    || (form.proxy ? proxyGeoFallbackLabel : "未设置");
  const effectiveLocalePreview = form.locale
    || proxyTest?.suggested_locale
    || (form.proxy ? proxyGeoFallbackLabel : "未设置");

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

  const updateStartupUrls = (value: string) => {
    setStartupUrlsText(value);
    set("startup_urls", value
      .split(/\r?\n/)
      .map((url) => url.trim())
      .filter(Boolean));
  };

  const proxyLabel = proxyParts.kind === "xray"
    ? (proxyParts.raw ? proxyParts.raw.split("://", 1)[0]?.toUpperCase() ?? "Xray" : "Xray 链接")
    : proxyParts.scheme.toUpperCase();

  const summaryRows = [
    ["浏览器", currentEngine === "system_chrome" ? "Google Chrome 原生" : "CloakBrowser / Chromium"],
    ["系统", platformLabel(allowedPlatform)],
    ["画像", selectedDeviceProfile.name],
    ["账号平台", form.account_platform || "未设置"],
    ["User-Agent", form.user_agent || "跟随真实浏览器"],
    ["代理", form.proxy ? `${proxyLabel} · 已配置` : "未配置"],
    ["启动页面", (form.startup_urls ?? []).length > 0 ? `${form.startup_urls?.length} 个网址` : "默认自检页"],
    ["时区", effectiveTimezonePreview],
    ["语言", effectiveLocalePreview],
    ["分辨率", `${form.screen_width ?? 1920} × ${form.screen_height ?? 1080}`],
    ["Canvas", currentEngine === "system_chrome" ? "真实" : "按画像"],
    ["WebGL 图像", currentEngine === "system_chrome" ? "真实" : "按画像"],
    ["WebGL 元数据", summaryGpu],
    ["CPU", summaryCpu],
    ["资料夹", isEdit ? "独立保存" : "创建后生成"],
  ];

  const fingerprintPreviewRows = [
    ["运行模式", currentEngine === "system_chrome" ? "系统 Chrome 原生" : "CloakBrowser 画像"],
    ["操作系统", platformLabel(allowedPlatform)],
    ["设备画像", selectedDeviceProfile.name],
    ["CPU / 芯片", selectedDeviceProfile.chip],
    ["屏幕", `${form.screen_width ?? selectedDeviceProfile.screen_width} × ${form.screen_height ?? selectedDeviceProfile.screen_height}`],
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

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="grid min-h-full grid-cols-[minmax(0,1fr)_360px] gap-6 px-6 py-6">
          <div className="space-y-6">
            {(
              <>
                <section className="rounded-md border border-border bg-white p-5">
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
                        className="input min-h-28 max-w-3xl resize-y text-xs"
                        value={form.cookies_json ?? ""}
                        onChange={(e) => set("cookies_json", e.target.value || null)}
                        placeholder='粘贴 Cookie JSON，例如 [{"name":"sid","value":"...","domain":".example.com","path":"/"}]'
                        spellCheck={false}
                      />
                      <FieldNote>Cookie 会随配置保存；调试启动或伪装画像启动时会尝试导入，日常原生手动启动只保存不强行注入。</FieldNote>
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
              <section className="rounded-md border border-border bg-white p-5">
                <div className="mb-2 text-sm font-semibold text-slate-900">代理信息</div>
                <SectionIntro>
                  代理决定出口 IP，也会影响时区和语言建议。普通 HTTP/HTTPS/SOCKS5 直接填主机端口；VLESS、VMess、Trojan、Shadowsocks 使用 Xray 链接。
                </SectionIntro>
                <div className="grid max-w-3xl grid-cols-[120px_minmax(0,1fr)] items-start gap-x-5 gap-y-4">
                  <label className="pt-2 text-right text-sm font-medium text-slate-600">代理方式</label>
                  <div>
                    <div className="flex max-w-xl rounded-md bg-slate-100 p-1">
                      {[
                        ["direct", "自定义"],
                        ["xray", "Xray 链接"],
                      ].map(([kind, label]) => (
                        <button
                          key={kind}
                          type="button"
                          onClick={() => updateProxyKind(kind as ProxyKind)}
                          className={`h-9 flex-1 rounded text-sm font-medium ${
                            proxyParts.kind === kind ? "bg-white text-accent shadow-sm" : "text-slate-600"
                          }`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    <FieldNote>自定义适合已有 HTTP/HTTPS/SOCKS5 代理；Xray 链接会启动本地内核并转成本机 SOCKS5 给浏览器使用。</FieldNote>
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

                  {proxyParts.kind === "xray" ? (
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

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">代理检测</label>
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={handleProxyTest}
                        disabled={testingProxy || !form.proxy}
                        className="btn-secondary flex items-center gap-1.5 disabled:opacity-60"
                      >
                        {testingProxy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
                        <span>{testingProxy ? "检查中..." : "检查代理"}</span>
                      </button>
                      <span className="break-all text-xs text-slate-500">
                        {form.proxy ? form.proxy : "填写代理后可检查出口 IP、国家、时区和语言"}
                      </span>
                    </div>
                    <FieldNote>保存前建议先检查一次；检查结果可以一键写入时区和语言。即使不点“应用”，启动时也会尽量跟随代理地区。</FieldNote>
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
                    <FieldNote>左边填 IANA 时区，例如 Asia/Taipei；右边填浏览器语言，例如 zh-TW 或 en-US。留空时会先跟随代理地区，手动填写会作为优先值。</FieldNote>
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
                      根据代理 IP 自动匹配时区和语言区域
                    </label>
                    <FieldNote>勾选后会强制覆盖上面的手动值；不勾选时，只要时区/语言留空，启动时也会尽量跟随代理。</FieldNote>
                  </div>
                </div>
              </section>
            )}

            {(
              <section className="rounded-md border border-border bg-white p-5">
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
                      value={currentResolution}
                      onChange={(e) => {
                        const preset = RESOLUTION_PRESETS[e.target.value];
                        if (preset) {
                          set("screen_width", preset.width);
                          set("screen_height", preset.height);
                        }
                      }}
                    >
                      {Object.keys(RESOLUTION_PRESETS).map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                      <option value="custom">自定义</option>
                    </select>
                    <div className="mt-1 text-xs text-slate-500">分辨率要和设备画像匹配，例如 Windows 笔记本常见 1920 × 1200，MacBook Pro 14 常见 3024 × 1964。</div>
                  </div>

                  {currentResolution === "custom" && (
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

                  <label className="pt-2 text-right text-sm font-medium text-slate-600">GPU 预设</label>
                  <div>
                    <select
                      className="input max-w-xl"
                      value=""
                      onChange={(e) => {
                        if (e.target.value) applyGpuPreset(e.target.value);
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

            {(
              <section className="rounded-md border border-border bg-white p-5">
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
