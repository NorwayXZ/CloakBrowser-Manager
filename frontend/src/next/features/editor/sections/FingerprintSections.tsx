import { RefreshCw } from "lucide-react";
import { Checkbox, FormField, Hint, IconButton, Input, KeyValueList, Section, Segmented, Select } from "../../../ui";
import {
  currentResolution,
  fingerprintPreviewRows,
  GPU_PRESETS,
  MAC_PLATFORM_VERSIONS,
  normalizeFormEngine,
  realScreenOf,
  RESOLUTION_PRESETS,
  screenFollowsDisplay,
  WINDOWS_PLATFORM_VERSIONS,
} from "../model";
import type { FingerprintOptions, HostOS } from "../types";
import type { Editor } from "../useEditor";

const numberOrNull = (value: string) => (value ? Number(value) : null);

export function FingerprintSection({ editor, hostOS, hostScreen, isEdit }: { editor: Editor; hostOS: HostOS | null; hostScreen: number[] | null; isEdit: boolean }) {
  const { form, set, setOption } = editor;
  const engine = normalizeFormEngine(form.browser_engine);
  const real = realScreenOf(hostScreen);
  const follows = screenFollowsDisplay(form, hostScreen);
  const resolution = currentResolution(form);
  const preview = fingerprintPreviewRows({ form, proxyParts: editor.proxyParts, proxyTest: editor.proxyTest, hostOS, hostScreen, isEdit });

  return (
    <Section id="form-fingerprint" title="指纹配置" description="设备画像决定屏幕、CPU、GPU 这些看得见的参数；稳定种子只决定同一画像里 Canvas、Audio 等细节。改完要保存并重新打开浏览器才生效。">
      <div className="mb-5 max-w-form rounded-md border border-border bg-surface-2 p-3">
        <KeyValueList items={preview.map(([label, value]) => ({ label, value }))} />
      </div>
      <div className="grid max-w-form grid-cols-1 gap-4 md:grid-cols-2">
        <FormField
          label="稳定种子"
          description={
            engine === "cloakbrowser"
              ? "不改变设备画像、CPU、GPU 或分辨率，只让同一套画像的细节输出保持稳定。想换整套画像，用“概要”里的“随机设备画像”。"
              : "稳定原生使用真实 Chrome 和真实硬件，这个值主要用于记录。"
          }
        >
          <div className="flex gap-2">
            <Input
              type="number"
              inputMode="numeric"
              value={form.fingerprint_seed ?? ""}
              placeholder="自动随机"
              onChange={(event) => set("fingerprint_seed", numberOrNull(event.target.value))}
            />
            <IconButton label="重新生成稳定种子" variant="secondary" icon={<RefreshCw className="h-4 w-4" />} onClick={editor.randomizeSeed} />
          </div>
        </FormField>
        <FormField
          label="分辨率"
          description={
            follows
              ? "每次启动时读取这台电脑主显示器的分辨率。检测网站能通过 CSS 媒体查询读到真实屏幕，自定义的分辨率和它对不上会被判为不一致。"
              : "浏览器看到的逻辑分辨率，不是 Retina 屏的物理像素，例如 MacBook Pro 14 常见 1512 × 982。"
          }
        >
          <Select
            value={follows ? "real" : resolution}
            onChange={(event) => {
              if (event.target.value === "real") {
                setOption("screen", "real");
                return;
              }
              const preset = RESOLUTION_PRESETS[event.target.value];
              editor.setForm((f) => ({
                ...f,
                fingerprint_options: { ...(f.fingerprint_options ?? {}), screen: "custom" },
                ...(preset ? { screen_width: preset.width, screen_height: preset.height } : {}),
              }));
            }}
          >
            {engine === "cloakbrowser" && real && <option value="real">跟随电脑屏幕 {real[0]} × {real[1]}（推荐）</option>}
            {Object.keys(RESOLUTION_PRESETS).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
            <option value="custom">自定义</option>
          </Select>
        </FormField>
        {!follows && resolution === "custom" && (
          <div className="grid grid-cols-2 gap-2 md:col-span-2">
            <FormField label="宽" description="会直接影响窗口尺寸和 screen 相关字段，建议只填真实设备常见的比例。">
              <Input type="number" inputMode="numeric" value={form.screen_width ?? 1920} onChange={(event) => set("screen_width", Number(event.target.value))} />
            </FormField>
            <FormField label="高">
              <Input type="number" inputMode="numeric" value={form.screen_height ?? 1080} onChange={(event) => set("screen_height", Number(event.target.value))} />
            </FormField>
          </div>
        )}
        <FormField label="CPU 线程" description="留空表示稳定原生用真实 CPU；伪装画像按当前画像推荐线程数。">
          <Input type="number" inputMode="numeric" value={form.hardware_concurrency ?? ""} placeholder="按画像或真实设备" onChange={(event) => set("hardware_concurrency", numberOrNull(event.target.value))} />
        </FormField>
        <FormField label="浏览器内存" description="navigator.deviceMemory 只给出粗略值，最高 8 GB；画像默认 8，不虚构更大的值。">
          <Select value={form.device_memory ?? ""} onChange={(event) => set("device_memory", numberOrNull(event.target.value))}>
            <option value="">按真实设备</option>
            <option value="2">2 GB</option>
            <option value="4">4 GB</option>
            <option value="8">8 GB</option>
          </Select>
        </FormField>
        <FormField label="GPU 预设" className="md:col-span-2" description="同时填入厂商和渲染器，避免厂商、芯片和 WebGL 信息互相矛盾。">
          <Select
            value=""
            onChange={(event) => {
              if (event.target.value) editor.applyGpuPreset(event.target.value);
              event.target.value = "";
            }}
          >
            <option value="">选择预设…</option>
            {Object.keys(GPU_PRESETS).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="GPU 厂商" className="md:col-span-2" description="通常不用改；只有用伪装画像并且明确知道目标设备时才填。">
          <Input value={form.gpu_vendor ?? ""} placeholder="按画像或真实设备" onChange={(event) => set("gpu_vendor", event.target.value || null)} />
        </FormField>
        <FormField label="GPU 渲染器" className="md:col-span-2" description="WebGL 元数据里最显眼的硬件信息，必须和当前画像一致。">
          <Input value={form.gpu_renderer ?? ""} placeholder="按画像或真实设备" onChange={(event) => set("gpu_renderer", event.target.value || null)} />
        </FormField>
      </div>
    </Section>
  );
}

export function MoreFingerprintSection({ editor, hostOS }: { editor: Editor; hostOS: HostOS | null }) {
  const { form, setOption } = editor;
  const engine = normalizeFormEngine(form.browser_engine);
  const options: FingerprintOptions = form.fingerprint_options ?? {};
  const mac = form.platform === "macos";

  if (engine !== "cloakbrowser") {
    return (
      <Section id="form-more-fingerprint" title="更多指纹">
        <p className="text-sm text-fg-2">“稳定原生”使用电脑上的 Google Chrome 和真实硬件，不支持浏览器品牌、WebRTC IP 等额外伪装项；需要时把浏览器切换为“伪装画像”。</p>
      </Section>
    );
  }

  const geolocation = options.geolocation ?? "ip";
  return (
    <Section id="form-more-fingerprint" title="更多指纹" description="CloakBrowser 内核自带的额外伪装项。全部留默认时由内核按稳定种子生成，已经是一套一致的指纹；只在明确需要时才改。">
      <div className="grid max-w-form grid-cols-1 gap-5 md:grid-cols-2">
        <FormField label="浏览器品牌" description="改 User-Agent 和 Client Hints 里的浏览器名称，内核本身不变。">
          <Select value={options.brand ?? ""} onChange={(event) => setOption("brand", (event.target.value || null) as FingerprintOptions["brand"])}>
            <option value="">Chrome（默认）</option>
            <option value="Edge">Microsoft Edge</option>
            <option value="Opera">Opera</option>
            <option value="Vivaldi">Vivaldi</option>
          </Select>
        </FormField>
        <FormField label="品牌版本号">
          <Input value={options.brand_version ?? ""} placeholder="留空跟随内核" onChange={(event) => setOption("brand_version", event.target.value || null)} />
        </FormField>
        <FormField
          label="系统版本"
          description={mac ? "Client Hints 里的 macOS 版本，例如 15.6.0 是 macOS 15。" : "Client Hints 里的 Windows 版本：10.0.0 是 Windows 10，13.0.0 以上是 Windows 11。"}
        >
          <Input list="platform-version-options" value={options.platform_version ?? ""} placeholder="留空由内核决定" onChange={(event) => setOption("platform_version", event.target.value.trim() || null)} />
        </FormField>
        <datalist id="platform-version-options">
          {(mac ? MAC_PLATFORM_VERSIONS : WINDOWS_PLATFORM_VERSIONS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </datalist>
        <FormField
          label="地理位置"
          description={
            geolocation === "ip"
              ? "网页请求定位时，调试启动返回出口 IP 所在城市的坐标；日常启动改不了坐标，会直接拒绝，不暴露真实位置。"
              : geolocation === "block"
                ? "所有网站请求定位都直接拒绝。"
                : "和普通 Chrome 一样，由你决定是否给网站真实位置。用代理时不建议。"
          }
        >
          <Segmented label="地理位置" value={geolocation} onChange={(value) => setOption("geolocation", value)} options={[["ip", "基于 IP"], ["block", "禁止"], ["real", "真实"]]} />
        </FormField>
        <FormField
          label="WebRTC"
          className="md:col-span-2"
          description={options.webrtc === "custom" ? "网页通过 WebRTC 看到的公网 IP 固定为这里填的地址。" : "用代理时网页通过 WebRTC 看到的是代理出口 IP，防止泄露真实 IP；直连时保持真实。"}
        >
          <div className="flex flex-wrap items-center gap-2">
            <Segmented
              label="WebRTC"
              value={options.webrtc ?? "proxy"}
              options={[["proxy", "跟随出口 IP"], ["custom", "指定 IP"]]}
              onChange={(value) =>
                editor.setForm((f) => ({
                  ...f,
                  fingerprint_options: { ...(f.fingerprint_options ?? {}), webrtc: value, webrtc_ip: value === "custom" ? f.fingerprint_options?.webrtc_ip ?? "" : null },
                }))
              }
            />
            {options.webrtc === "custom" && (
              <Input mono className="w-48" aria-label="WebRTC 公网 IP" value={options.webrtc_ip ?? ""} placeholder="例如 203.0.113.9" onChange={(event) => setOption("webrtc_ip", event.target.value)} />
            )}
          </div>
        </FormField>
        <FormField label="指纹噪声" className="md:col-span-2" description={<Hint>噪声让每个画像的 Canvas、WebGL、音频输出各不相同。实测多数现代检测器对噪声净扣分，新建画像默认关闭；想回到内核默认可以切回“自动”；macOS 画像默认关闭。</Hint>}>
          <Segmented
            label="指纹噪声"
            value={options.noise == null ? "auto" : options.noise ? "on" : "off"}
            options={[["auto", "自动"], ["on", "开启"], ["off", "关闭"]]}
            onChange={(value) => setOption("noise", value === "auto" ? null : value === "on")}
          />
        </FormField>
        <FormField label="存储配额" description={<Hint>navigator.storage.estimate() 报告的磁盘配额（MB）。真实电脑通常几十 GB 以上；新建画像默认 50000（约 50 GB），实测可以消除 BrowserScan 的无痕模式扣分。</Hint>}>
          <div className="flex flex-wrap items-center gap-2">
            <Segmented
              label="存储配额"
              value={options.storage_quota_mb == null ? "auto" : "custom"}
              options={[["auto", "按种子自动"], ["custom", "自定义"]]}
              onChange={(value) => setOption("storage_quota_mb", value === "auto" ? null : 50000)}
            />
            {options.storage_quota_mb != null && (
              <Input type="number" min={100} aria-label="存储配额（MB）" className="w-32" value={options.storage_quota_mb} placeholder="单位 MB" onChange={(event) => setOption("storage_quota_mb", numberOrNull(event.target.value))} />
            )}
          </div>
        </FormField>
        <FormField label="任务栏高度" description="决定 screen.availHeight 比屏幕高度少多少像素，一般不用改。">
          <div className="flex flex-wrap items-center gap-2">
            <Segmented
              label="任务栏高度"
              value={options.taskbar_height == null ? "auto" : "custom"}
              options={[["auto", mac ? "系统默认（95）" : "系统默认（48）"], ["custom", "自定义"]]}
              onChange={(value) => setOption("taskbar_height", value === "auto" ? null : mac ? 95 : 48)}
            />
            {options.taskbar_height != null && (
              <Input type="number" min={0} max={300} aria-label="任务栏高度（像素）" className="w-24" value={options.taskbar_height} placeholder="像素" onChange={(event) => setOption("taskbar_height", numberOrNull(event.target.value))} />
            )}
          </div>
        </FormField>
        <fieldset className="flex flex-col gap-3 md:col-span-2">
          <legend className="mb-2 text-sm font-medium text-fg">兼容选项</legend>
          {form.platform === "windows" && (
            <Checkbox
              checked={options.speech_voices ?? true}
              onCheckedChange={(value) => setOption("speech_voices", value)}
              label="Windows 语音列表"
              description="让 speechSynthesis 报告和真实 Windows Chrome 一样的语音。某个网站因此异常时再关闭。"
            />
          )}
          <Checkbox checked={options.allow_3p_cookies ?? false} onCheckedChange={(value) => setOption("allow_3p_cookies", value)} label="允许第三方 Cookie" description="只在 reCAPTCHA、单点登录或支付验证一直转圈完成不了时打开。" />
          <Checkbox
            checked={(options.transparent_proxy ?? false) && Boolean(form.proxy)}
            disabled={!form.proxy}
            onCheckedChange={(value) => setOption("transparent_proxy", value)}
            label="透明代理"
            description={form.proxy ? "更隐蔽的代理连接方式，用于换了好几个代理都被网站识别的情况。" : "需要先设置代理。"}
          />
          <Checkbox
            checked={options.portable_cookies ?? false}
            onCheckedChange={(value) => setOption("portable_cookies", value)}
            label="跨电脑 Cookie"
            description="用和电脑无关的密钥加密 Cookie，把环境搬到另一台电脑后登录还在。只对开启之后保存的 Cookie 有效，新环境建议一开始就打开。"
          />
          {form.platform === "windows" && hostOS === "linux" && (
            <Checkbox checked={options.windows_font_metrics ?? false} onCheckedChange={(value) => setOption("windows_font_metrics", value)} label="Windows 字体度量" description="Linux 上伪装 Windows 时对齐字体尺寸，需要先装好 Windows 字体。" />
          )}
        </fieldset>
      </div>
    </Section>
  );
}
