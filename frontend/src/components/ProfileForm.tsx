import { ChevronDown, Globe, Loader2, RefreshCw, Save, SlidersHorizontal, Trash2, Wifi, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Profile, type ProfileCreateData, type ProxyTestResult } from "../lib/api";
import {
  applyDeviceProfile,
  DEFAULT_DEVICE_PROFILE_ID,
  DEVICE_PROFILE_FAMILIES,
  DEVICE_PROFILES,
  getDeviceProfile,
  randomFingerprintSeed,
} from "../lib/deviceProfiles";

interface ProfileFormProps {
  profile: Profile | null; // null = create mode
  onSave: (data: ProfileCreateData) => Promise<void>;
  onDelete?: () => Promise<void>;
  onCancel: () => void;
  onDraftChange?: (data: ProfileCreateData) => void;
}

const RESOLUTION_PRESETS: Record<string, { width: number; height: number }> = {
  "1280 × 720 (原生窗口)": { width: 1280, height: 720 },
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

const TAG_COLORS = [
  "#6366f1", // indigo
  "#22c55e", // green
  "#f59e0b", // amber
  "#ef4444", // red
  "#06b6d4", // cyan
  "#a855f7", // purple
  "#f97316", // orange
  "#ec4899", // pink
];

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
};

type ProxyScheme = "http" | "https" | "socks5";
type EditableBrowserEngine = "system_chrome" | "cloakbrowser";

interface ProxyParts {
  scheme: ProxyScheme;
  host: string;
  port: string;
  username: string;
  password: string;
}

const PROXY_SCHEMES: ProxyScheme[] = ["http", "https", "socks5"];

const DEFAULT_PROXY_PARTS: ProxyParts = {
  scheme: "http",
  host: "",
  port: "",
  username: "",
  password: "",
};

function createDefaultForm(): ProfileCreateData {
  return applyDeviceProfile({
    name: "",
    humanize: false,
    human_preset: "default",
    headless: false,
    geoip: false,
    clipboard_sync: true,
    auto_launch: false,
    launch_args: [],
    tags: [],
  }, getDeviceProfile(DEFAULT_DEVICE_PROFILE_ID));
}

function isProxyScheme(value: string): value is ProxyScheme {
  return PROXY_SCHEMES.includes(value as ProxyScheme);
}

function parseProxy(raw?: string | null): ProxyParts {
  const value = raw?.trim();
  if (!value) return { ...DEFAULT_PROXY_PARTS };

  if (value.includes("://")) {
    try {
      const url = new URL(value);
      const scheme = url.protocol.replace(":", "");
      if (isProxyScheme(scheme)) {
        return {
          scheme,
          host: url.hostname,
          port: url.port,
          username: decodeURIComponent(url.username),
          password: decodeURIComponent(url.password),
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
      scheme: "http",
      host: host ?? "",
      port: port ?? "",
      username: username ?? "",
      password: password ?? "",
    };
  }
  if (parts.length === 2) {
    const [host, port] = parts;
    return { scheme: "http", host: host ?? "", port: port ?? "", username: "", password: "" };
  }

  return { ...DEFAULT_PROXY_PARTS, host: value };
}

function buildProxy(parts: ProxyParts): string | null {
  const host = parts.host.trim();
  const port = parts.port.trim();
  if (!host || !port) return null;

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

export function ProfileForm({ profile, onSave, onDelete, onCancel, onDraftChange }: ProfileFormProps) {
  const isEdit = profile !== null;

  const [form, setForm] = useState<ProfileCreateData>(() => createDefaultForm());
  const [proxyParts, setProxyParts] = useState<ProxyParts>(() => parseProxy(profile?.proxy));
  const [proxyTest, setProxyTest] = useState<ProxyTestResult | null>(null);
  const [proxyTestError, setProxyTestError] = useState<string | null>(null);
  const [testingProxy, setTestingProxy] = useState(false);

  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [tagInput, setTagInput] = useState("");
  const [tagColor, setTagColor] = useState<string | null>("#6366f1");
  const [launchArgInput, setLaunchArgInput] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [draftProfileId, setDraftProfileId] = useState<string | null>(null);

  useEffect(() => {
    if (profile) {
      const browserEngine = normalizeFormEngine(profile.browser_engine);
      const deviceProfile = getDeviceProfile(profile.device_profile);
      setForm({
        name: profile.name,
        browser_engine: browserEngine,
        device_profile: deviceProfile.id,
        fingerprint_seed: profile.fingerprint_seed,
        proxy: profile.proxy,
        timezone: profile.timezone,
        locale: profile.locale,
        platform: "macos",
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
        color_scheme: profile.color_scheme,
        launch_args: profile.launch_args ?? [],
        notes: profile.notes,
        tags: profile.tags ?? [],
      });
      setProxyParts(parseProxy(profile.proxy));
      setDraftProfileId(profile.id);
    } else {
      setForm(createDefaultForm());
      setProxyParts({ ...DEFAULT_PROXY_PARTS });
      setDraftProfileId(null);
    }
    setProxyTest(null);
    setProxyTestError(null);
    setAdvancedOpen(false);
  }, [profile?.id]);

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
      await onSave(form);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!onDelete) return;
    if (!confirm("确定删除这个配置吗？浏览器数据会被永久移除。")) return;
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

  const updateProxyPart = <K extends keyof ProxyParts>(key: K, value: ProxyParts[K]) => {
    const next = { ...proxyParts, [key]: value };
    setProxyParts(next);
    set("proxy", buildProxy(next));
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
  const selectedDeviceProfile = getDeviceProfile(form.device_profile);
  const rendererName = form.gpu_renderer?.split("Renderer: ")[1] ?? form.gpu_renderer;
  const summaryCpu = currentEngine === "system_chrome"
    ? "真实设备"
    : form.hardware_concurrency ? `${form.hardware_concurrency} 线程` : "按画像";
  const summaryGpu = currentEngine === "system_chrome"
    ? "真实设备"
    : form.gpu_renderer?.includes("Renderer: ")
    ? rendererName?.replace(", Unspecified Version)", ")")
    : form.gpu_renderer ?? "真实设备";

  const handleDeviceProfileChange = (id: string) => {
    setForm((prev) => applyDeviceProfile(prev, getDeviceProfile(id)));
  };

  const handleEngineChange = (engine: "system_chrome" | "cloakbrowser") => {
    setForm((prev) => applyDeviceProfile(
      { ...prev, browser_engine: engine },
      getDeviceProfile(prev.device_profile ?? DEFAULT_DEVICE_PROFILE_ID),
    ));
  };

  const addTag = () => {
    const tag = tagInput.trim();
    if (!tag) return;
    if (form.tags?.some((t) => t.tag === tag)) return;
    set("tags", [...(form.tags ?? []), { tag, color: tagColor }]);
    setTagInput("");
  };

  const removeTag = (tag: string) => {
    set("tags", (form.tags ?? []).filter((t) => t.tag !== tag));
  };

  const addLaunchArg = () => {
    const arg = launchArgInput.trim();
    if (!arg) return;
    if ((form.launch_args ?? []).includes(arg)) return;
    set("launch_args", [...(form.launch_args ?? []), arg]);
    setLaunchArgInput("");
  };

  const removeLaunchArg = (idx: number) => {
    set("launch_args", (form.launch_args ?? []).filter((_, i) => i !== idx));
  };

  return (
    <form onSubmit={handleSubmit} className="p-6 max-w-2xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">
            {isEdit ? "编辑配置" : "新建配置"}
          </h2>
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
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={onCancel} className="btn-secondary">
            取消
          </button>
          <button type="submit" disabled={saving} className="btn-primary flex items-center gap-1.5">
            <Save className="h-3.5 w-3.5" />
            <span>{saving ? "保存中..." : isEdit ? "保存" : "创建"}</span>
          </button>
        </div>
      </div>

      <div className="space-y-5">
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">基础信息</h3>
          <div className="space-y-3">
            <div>
              <label className="label">配置名称</label>
              <input
                className="input"
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder="例如 Amazon Seller #1"
                required
              />
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="label">浏览器模式</label>
                <select
                  className="input"
                  value={currentEngine}
                  onChange={(e) => handleEngineChange(e.target.value as "system_chrome" | "cloakbrowser")}
                >
                  <option value="system_chrome">稳定原生</option>
                  <option value="cloakbrowser">伪装画像</option>
                </select>
              </div>
              <div>
                <label className="label">Apple Silicon 画像</label>
                <select
                  className="input"
                  value={selectedDeviceProfile.id}
                  onChange={(e) => handleDeviceProfileChange(e.target.value)}
                >
                  {DEVICE_PROFILE_FAMILIES.map((family) => (
                    <optgroup key={family} label={family}>
                      {DEVICE_PROFILES.filter((preset) => preset.family === family).map((preset) => (
                        <option key={preset.id} value={preset.id}>{preset.name}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
              <div className="rounded-md bg-surface-2 px-3 py-2">
                <div className="text-gray-500">芯片</div>
                <div className="text-gray-200">{selectedDeviceProfile.chip === "Native" ? "真实设备" : selectedDeviceProfile.chip}</div>
              </div>
              <div className="rounded-md bg-surface-2 px-3 py-2">
                <div className="text-gray-500">屏幕</div>
                <div className="text-gray-200">{form.screen_width} × {form.screen_height}</div>
              </div>
              <div className="rounded-md bg-surface-2 px-3 py-2">
                <div className="text-gray-500">CPU</div>
                <div className="text-gray-200">{summaryCpu}</div>
              </div>
              <div className="rounded-md bg-surface-2 px-3 py-2">
                <div className="text-gray-500">GPU</div>
                <div className="truncate text-gray-200" title={form.gpu_renderer ?? "真实设备"}>
                  {summaryGpu}
                </div>
              </div>
            </div>
            {currentEngine === "system_chrome" && (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
                稳定原生会使用真实 Chrome、真实 Canvas/GPU/CPU/UA；Apple Silicon 画像主要用于档案标记和窗口尺寸预设。
              </div>
            )}
            {currentEngine === "cloakbrowser" && (
              <div className="rounded-md border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-200">
                伪装画像会启用 Apple Silicon 指纹参数；当前更适合继续调试画像一致性。
              </div>
            )}
          </div>
        </section>

        <section>
          <button
            type="button"
            onClick={() => setAdvancedOpen((open) => !open)}
            className="flex w-full items-center justify-between rounded-md border border-border bg-surface-1 px-3 py-2 text-left text-sm text-gray-200 hover:bg-surface-2"
          >
            <span className="inline-flex items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 text-gray-400" />
              高级画像参数
            </span>
            <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${advancedOpen ? "rotate-180" : ""}`} />
          </button>

          {advancedOpen && (
            <div className="mt-3 space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="label">平台</label>
                  <select
                    className="input"
                    value={form.platform}
                    onChange={(e) => set("platform", e.target.value)}
                  >
                    <option value="macos">macOS</option>
                  </select>
                </div>
                <div>
                  <label className="label">指纹种子</label>
                  <div className="flex gap-2">
                    <input
                      className="input flex-1 no-spin"
                      type="number"
                      value={form.fingerprint_seed ?? ""}
                      onChange={(e) => set("fingerprint_seed", e.target.value ? Number(e.target.value) : null)}
                      placeholder="自动随机"
                    />
                    <button
                      type="button"
                      onClick={randomizeSeed}
                      className="btn-secondary px-2.5"
                      title="随机生成种子"
                    >
                      <RefreshCw className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>

              <div>
                <label className="label">屏幕分辨率</label>
                <select
                  className="input"
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
              </div>

              {currentResolution === "custom" && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="label">宽度</label>
                    <input
                      className="input no-spin"
                      type="number"
                      value={form.screen_width ?? 1920}
                      onChange={(e) => set("screen_width", Number(e.target.value))}
                    />
                  </div>
                  <div>
                    <label className="label">高度</label>
                    <input
                      className="input no-spin"
                      type="number"
                      value={form.screen_height ?? 1080}
                      onChange={(e) => set("screen_height", Number(e.target.value))}
                    />
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="label">CPU 线程数</label>
                  <input
                    className="input no-spin"
                    type="number"
                    value={form.hardware_concurrency ?? ""}
                    onChange={(e) => set("hardware_concurrency", e.target.value ? Number(e.target.value) : null)}
                    placeholder="按画像或真实设备"
                  />
                </div>
                <div>
                  <label className="label">GPU 预设</label>
                  <select
                    className="input"
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
                </div>
              </div>

              <div>
                <label className="label">GPU 厂商</label>
                <input
                  className="input"
                  value={form.gpu_vendor ?? ""}
                  onChange={(e) => set("gpu_vendor", e.target.value || null)}
                  placeholder="按画像或真实设备"
                />
              </div>

              <div>
                <label className="label">GPU 渲染器</label>
                <input
                  className="input"
                  value={form.gpu_renderer ?? ""}
                  onChange={(e) => set("gpu_renderer", e.target.value || null)}
                  placeholder="按画像或真实设备"
                />
              </div>

              <div>
                <label className="label">用户代理（User Agent）</label>
                <input
                  className="input"
                  value={form.user_agent ?? ""}
                  onChange={(e) => set("user_agent", e.target.value || null)}
                  placeholder="按浏览器二进制自动生成"
                />
              </div>
            </div>
          )}
        </section>

        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">网络与地区</h3>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">代理协议</label>
                <select
                  className="input"
                  value={proxyParts.scheme}
                  onChange={(e) => updateProxyPart("scheme", e.target.value as ProxyScheme)}
                >
                  <option value="http">HTTP</option>
                  <option value="https">HTTPS</option>
                  <option value="socks5">SOCKS5</option>
                </select>
              </div>
              <div>
                <label className="label">主机</label>
                <input
                  className="input"
                  value={proxyParts.host}
                  onChange={(e) => updateProxyPart("host", e.target.value)}
                  placeholder="proxy.example.com"
                />
              </div>
              <div>
                <label className="label">端口</label>
                <input
                  className="input no-spin"
                  value={proxyParts.port}
                  onChange={(e) => updateProxyPart("port", e.target.value)}
                  placeholder="1080"
                />
              </div>
              <div>
                <label className="label">账号</label>
                <input
                  className="input"
                  value={proxyParts.username}
                  onChange={(e) => updateProxyPart("username", e.target.value)}
                  placeholder="可选"
                />
              </div>
              <div>
                <label className="label">密码</label>
                <input
                  className="input"
                  type="password"
                  value={proxyParts.password}
                  onChange={(e) => updateProxyPart("password", e.target.value)}
                  placeholder="可选"
                />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={handleProxyTest}
                disabled={testingProxy || !form.proxy}
                className="btn-secondary flex items-center gap-1.5 disabled:opacity-60"
              >
                {testingProxy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
                <span>{testingProxy ? "测试中..." : "测试代理"}</span>
              </button>
              <div className="text-xs text-gray-500 break-all">
                {form.proxy ? `自动生成：${form.proxy}` : "填写主机和端口后会自动生成代理地址"}
              </div>
            </div>
            {proxyTestError && (
              <div className="text-xs text-red-400">{proxyTestError}</div>
            )}
            {proxyTest && (
              <div className="space-y-2">
                <div className="text-xs text-emerald-400 space-y-1">
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    <span>出口 IP：{proxyTest.ip ?? "未知"}</span>
                    <span>国家：{proxyTest.country ? `${proxyTest.country}${proxyTest.country_code ? ` (${proxyTest.country_code})` : ""}` : "未知"}</span>
                    <span>时区：{proxyTest.timezone ?? "未知"}</span>
                    <span>建议语言：{proxyTest.suggested_locale ?? "未知"}</span>
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-gray-400">
                    <span>地区：{proxyTest.region ?? "未知"}</span>
                    <span>城市：{proxyTest.city ?? "未知"}</span>
                    <span>运营商：{proxyTest.org ?? "未知"}</span>
                    <span>ASN：{proxyTest.asn ?? "未知"}</span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => applyProxyGeo()}
                  disabled={!proxyTest.timezone && !proxyTest.suggested_locale}
                  className="btn-secondary text-xs inline-flex items-center gap-1.5 disabled:opacity-60"
                >
                  <Globe className="h-3.5 w-3.5" />
                  <span>应用到时区和语言</span>
                </button>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">时区</label>
                <input
                  className="input"
                  value={form.timezone ?? ""}
                  onChange={(e) => set("timezone", e.target.value || null)}
                  placeholder="Asia/Shanghai"
                />
              </div>
              <div>
                <label className="label">语言区域</label>
                <input
                  className="input"
                  value={form.locale ?? ""}
                  onChange={(e) => set("locale", e.target.value || null)}
                  placeholder="zh-CN"
                />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.geoip ?? false}
                onChange={(e) => set("geoip", e.target.checked)}
                className="rounded border-border bg-surface-2"
              />
              根据代理 IP 自动匹配时区和语言区域（测试成功后自动回填）
            </label>
          </div>
        </section>

        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">行为设置</h3>
          <div className="space-y-3">
            <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.humanize ?? false}
                onChange={(e) => set("humanize", e.target.checked)}
                className="rounded border-border bg-surface-2"
              />
              模拟真人鼠标、键盘和滚动行为
            </label>
            {form.humanize && (
              <div>
                <label className="label">真人节奏</label>
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
            <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.clipboard_sync ?? true}
                onChange={(e) => set("clipboard_sync", e.target.checked)}
                className="rounded border-border bg-surface-2"
              />
              默认启用 VNC 剪贴板同步
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={form.auto_launch ?? false}
                onChange={(e) => set("auto_launch", e.target.checked)}
                className="rounded border-border bg-surface-2"
              />
              容器启动时自动启动
            </label>
            <div>
              <label className="label">颜色偏好</label>
              <select
                className="input"
                value={form.color_scheme ?? ""}
                onChange={(e) => set("color_scheme", e.target.value || null)}
              >
                <option value="">跟随系统</option>
                <option value="light">浅色</option>
                <option value="dark">深色</option>
                <option value="no-preference">无偏好</option>
              </select>
            </div>
          </div>
        </section>

        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">标签</h3>
          {(form.tags ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {(form.tags ?? []).map((t) => (
                <span
                  key={t.tag}
                  className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-surface-3 text-gray-300"
                  style={t.color ? { backgroundColor: `${t.color}20`, color: t.color } : undefined}
                >
                  {t.tag}
                  <button
                    type="button"
                    onClick={() => removeTag(t.tag)}
                    className="hover:opacity-70"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="flex gap-2 items-center">
            <div className="flex gap-1">
              {TAG_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setTagColor(c)}
                  className="w-4 h-4 rounded-full border-2 transition-transform"
                  style={{
                    backgroundColor: c,
                    borderColor: tagColor === c ? "#fff" : "transparent",
                    transform: tagColor === c ? "scale(1.2)" : undefined,
                  }}
                />
              ))}
            </div>
            <input
              className="input flex-1"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
              placeholder="添加标签..."
            />
            <button type="button" onClick={addTag} className="btn-secondary text-xs">
              添加
            </button>
          </div>
        </section>

        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">启动参数</h3>
          <p className="text-xs text-gray-500 mb-2">启动时传给 Chromium 的自定义参数，例如 --load-extension、--disable-features</p>
          {(form.launch_args ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {(form.launch_args ?? []).map((arg, idx) => (
                <span
                  key={idx}
                  className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-surface-3 text-gray-300 font-mono"
                >
                  {arg}
                  <button
                    type="button"
                    onClick={() => removeLaunchArg(idx)}
                    className="hover:opacity-70"
                  >
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
              placeholder="--load-extension=/data/extensions/ublock"
            />
            <button type="button" onClick={addLaunchArg} className="btn-secondary text-xs">
              添加
            </button>
          </div>
        </section>

        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">备注</h3>
          <textarea
            className="input min-h-[80px] resize-y"
            value={form.notes ?? ""}
            onChange={(e) => set("notes", e.target.value || null)}
            placeholder="可选，写一些这个 profile 的说明..."
          />
        </section>
      </div>
    </form>
  );
}
