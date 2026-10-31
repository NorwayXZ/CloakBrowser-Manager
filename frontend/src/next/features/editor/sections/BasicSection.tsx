import { Download, FileDown, Plus } from "lucide-react";
import { forwardRef, useState } from "react";
import { Banner, Button, FormField, Hint, Input, Section, Select, Textarea } from "../../../ui";
import type { ProfileGroup } from "../../profiles/types";
import { downloadCookieExport, editorApi } from "../api";
import { getDeviceProfileFamiliesForPlatform, getDeviceProfilesForPlatform, getDevicePlatformForHost } from "../deviceProfiles";
import { ACCOUNT_PLATFORM_OPTIONS, defaultCookieDomain, normalizeFormEngine, platformLabel, selectedDevice } from "../model";
import type { CookieExportFormat, HostOS } from "../types";
import type { Editor } from "../useEditor";

const COOKIE_FORMAT_LABELS = { json: "JSON", netscape: "Netscape", header: "Name=Value" } as const;

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export const BasicSection = forwardRef<HTMLInputElement, {
  editor: Editor;
  profileId: string | null;
  groups: ProfileGroup[];
  hostOS: HostOS | null;
  nameError: string | null;
  onNameChange: () => void;
  /** The Apple device the kernel builds from this seed, once a launch has seen it. */
  seedDeviceLabel?: string | null;
}>(function BasicSection({ editor, profileId, groups, hostOS, nameError, onNameChange, seedDeviceLabel }, nameRef) {
  const { form, set } = editor;
  const engine = normalizeFormEngine(form.browser_engine);
  const platform = getDevicePlatformForHost(hostOS);
  const presets = getDeviceProfilesForPlatform(platform);
  const device = selectedDevice(form, hostOS);
  // On a Mac the kernel derives a whole Apple device from the seed and
  // ignores the template picked here.
  const seedDerived = hostOS === "macos" && platform === "macos" && engine === "cloakbrowser";

  return (
    <Section id="form-basic" title="基础设置" description="名称、分组、账号平台只用于管理；浏览器、设备型号、User-Agent、Cookie 和启动页面会影响实际打开的浏览器。">
      <div className="grid max-w-form grid-cols-1 gap-4 md:grid-cols-2">
        <FormField label="名称" required error={nameError ?? undefined} description="只用于你自己识别这个环境，不会写进网页指纹。" className="md:col-span-2">
          <Input
            ref={nameRef}
            value={form.name}
            placeholder="例如 Amazon Seller #1"
            onChange={(event) => {
              set("name", event.target.value);
              onNameChange();
            }}
          />
        </FormField>
        <FormField label="分组" description="新增分组在环境列表左侧的分组栏里。">
          <Select value={form.group_name || "未分组"} onChange={(event) => set("group_name", event.target.value)}>
            <option value="未分组">未分组</option>
            {groups.filter((group) => group.name !== "未分组").map((group) => (
              <option key={group.id} value={group.name}>
                {group.name}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="账号平台" description="在列表里显示这个环境对应哪个平台的账号，可以从建议里选，也可以自己写。">
          <Input list="account-platform-options" value={form.account_platform ?? ""} placeholder="例如 阿里云 / Amazon" onChange={(event) => set("account_platform", event.target.value || null)} />
        </FormField>
        <datalist id="account-platform-options">
          {ACCOUNT_PLATFORM_OPTIONS.map((option) => (
            <option key={option} value={option} />
          ))}
        </datalist>
        <FormField
          label="浏览器"
          description={
            <Hint>
              {engine === "system_chrome"
                ? "日常启动始终不打开外部 CDP。系统 Chrome 会使用语言参数和进程时区，但能否完整生效由本机 Chrome 决定，启动自检会如实报告。"
                : "日常启动直接运行 CloakBrowser 二进制，不打开外部 CDP；语言和时区由底层参数统一应用到主页面、iframe 与 Worker。"}
            </Hint>
          }
        >
          <Select value={engine} onChange={(event) => editor.changeEngine(event.target.value as "system_chrome" | "cloakbrowser")}>
            <option value="system_chrome">稳定原生（系统 Chrome）</option>
            <option value="cloakbrowser">防检测浏览器（CloakBrowser）</option>
          </Select>
        </FormField>
        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-fg">操作系统</span>
          <span className="inline-flex h-8 w-fit items-center rounded border border-border bg-surface-2 px-2.5 text-sm text-fg">{platformLabel(platform)}</span>
          <span className="text-xs text-fg-3">按当前电脑锁定：只提供同系统的设备型号，避免跨系统设备型号互相矛盾。</span>
        </div>
        <FormField
          label="设备型号"
          className="md:col-span-2"
          description={
            seedDerived
              ? `在这台 Mac 上，内核按稳定种子生成整套 Apple 设备（GPU、核心数、内存），这里的选择只作记录、不会生效。网站实际看到：${seedDeviceLabel ?? "首次打开后显示"}。`
              : "一键套用同平台的屏幕、CPU、GPU 组合；稳定原生下主要用作记录，防检测浏览器会写入可控参数。"
          }
        >
          <Select value={device.id} onChange={(event) => editor.changeDevice(event.target.value)}>
            {getDeviceProfileFamiliesForPlatform(platform).map((family) => (
              <optgroup key={family} label={family}>
                {presets.filter((preset) => preset.family === family).map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </Select>
        </FormField>
        <FormField label="User-Agent" className="md:col-span-2" description="建议留空，跟随真实浏览器；手动改错版本、系统或架构，反而会和真实能力对不上。">
          <Input mono className="text-xs" value={form.user_agent ?? ""} placeholder="留空则跟随真实浏览器" onChange={(event) => set("user_agent", event.target.value || null)} />
        </FormField>
        <FormField label="启动页面" className="md:col-span-2" description="没有恢复上次的标签页时打开这些网址；留空会打开本地的 IP、时间、语言自检页。">
          <Textarea
            mono
            rows={3}
            className="text-xs"
            spellCheck={false}
            value={editor.state.startupUrlsText}
            placeholder={"每行一个网址，例如：\nhttps://ip.skk.moe/\nhttps://pixelscan.net/fingerprint-check"}
            onChange={(event) => editor.setStartupUrlsText(event.target.value)}
          />
        </FormField>
        <div className="md:col-span-2">
          <CookieField editor={editor} profileId={profileId} />
        </div>
        <FormField label="备注" className="md:col-span-2" description="只保存在 Manager 里，记录账号用途、注意事项或代理来源。">
          <Textarea rows={3} value={form.notes ?? ""} placeholder="可选，写一些这个环境的用途…" onChange={(event) => set("notes", event.target.value || null)} />
        </FormField>
      </div>
    </Section>
  );
});

type Notice = { tone: "success" | "danger"; text: string } | null;

function CookieField({ editor, profileId }: { editor: Editor; profileId: string | null }) {
  const { form, set } = editor;
  const [merge, setMerge] = useState<{ text: string; domain: string } | null>(null);
  const [merging, setMerging] = useState(false);
  const [mergeNotice, setMergeNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState<"pull" | "export" | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [format, setFormat] = useState<CookieExportFormat>("json");

  const pull = async () => {
    if (!profileId) return;
    setBusy("pull");
    setNotice(null);
    try {
      const result = await editorApi.pullCookies(profileId);
      set("cookies_json", result.cookies_json);
      setNotice({
        tone: "success",
        text: result.count > 0 ? `已从浏览器导回 ${result.count} 条 Cookie，已填入上方文本框；点保存后写入配置` : "浏览器里目前没有 Cookie",
      });
    } catch (error) {
      setNotice({ tone: "danger", text: message(error) });
    } finally {
      setBusy(null);
    }
  };

  const exportFile = async () => {
    if (!profileId) return;
    setBusy("export");
    setNotice(null);
    try {
      const safeName = (form.name || "profile").replace(/[^\w\- ]+/g, "_").trim() || "profile";
      await downloadCookieExport(profileId, format, `${safeName}-cookies.${format === "json" ? "json" : "txt"}`);
      setNotice({ tone: "success", text: "Cookie 文件已开始下载" });
    } catch (error) {
      setNotice({ tone: "danger", text: message(error) });
    } finally {
      setBusy(null);
    }
  };

  const runMerge = async () => {
    if (!merge) return;
    setMerging(true);
    setMergeNotice(null);
    try {
      const result = await editorApi.mergeCookies(merge.text, form.cookies_json ?? null, merge.domain.trim() || null);
      set("cookies_json", result.cookies_json);
      setMerge({ text: "", domain: merge.domain });
      setMergeNotice({ tone: "success", text: `已合并 ${result.added} 条（${COOKIE_FORMAT_LABELS[result.format]}），现在共 ${result.total} 条` });
    } catch (error) {
      setMergeNotice({ tone: "danger", text: message(error) });
    } finally {
      setMerging(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <FormField
        label="Cookie"
        description={
          <Hint>
            Cookie 随配置保存；日常启动通过环境专用的本地扩展导入一次，调试启动通过浏览器上下文导入，之后由同一个用户数据目录保存登录状态。浏览器里新产生的 Cookie 不会自动出现在这里，可以用“从浏览器导回 Cookie”读回（浏览器需要正在运行）。
          </Hint>
        }
      >
        <Textarea
          mono
          rows={4}
          className="text-xs"
          spellCheck={false}
          value={form.cookies_json ?? ""}
          placeholder={"支持 JSON、Netscape（cookies.txt）格式，保存时自动转成 JSON。\nName=Value 格式要指定网站，请用下面的「合并 Cookie」。"}
          onChange={(event) => set("cookies_json", event.target.value || null)}
        />
      </FormField>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          icon={<Plus className="h-3.5 w-3.5" />}
          aria-expanded={merge !== null}
          onClick={() => {
            setMerge((current) => (current ? null : { text: "", domain: defaultCookieDomain(form) }));
            setMergeNotice(null);
          }}
        >
          合并 Cookie
        </Button>
        {profileId && (
          <>
            <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} loading={busy === "pull"} disabled={busy !== null} onClick={() => void pull()}>
              从浏览器导回 Cookie
            </Button>
            <span className="ml-auto flex items-center gap-2">
              <Select aria-label="导出格式" className="w-44" value={format} onChange={(event) => setFormat(event.target.value as CookieExportFormat)}>
                <option value="json">Cookie-Editor JSON</option>
                <option value="netscape">cookies.txt</option>
              </Select>
              <Button size="sm" icon={<FileDown className="h-3.5 w-3.5" />} loading={busy === "export"} disabled={busy !== null} onClick={() => void exportFile()}>
                导出 Cookie
              </Button>
            </span>
          </>
        )}
      </div>
      {notice && <p className={notice.tone === "danger" ? "text-sm text-danger" : "text-sm text-success"} role={notice.tone === "danger" ? "alert" : "status"}>{notice.text}</p>}
      {merge && (
        <div className="flex flex-col gap-2 rounded-md border border-border bg-surface-2 p-3">
          <Textarea
            mono
            rows={3}
            className="text-xs"
            spellCheck={false}
            aria-label="要合并的 Cookie"
            value={merge.text}
            placeholder="粘贴要加进来的 Cookie：JSON、Netscape 或 Name=Value（如 sid=abc; lang=zh）"
            onChange={(event) => {
              setMerge({ ...merge, text: event.target.value });
              setMergeNotice(null);
            }}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Input className="w-64" aria-label="Cookie 所属网站" value={merge.domain} placeholder="网站域名（Name=Value 格式必填）" onChange={(event) => setMerge({ ...merge, domain: event.target.value })} />
            <Button size="sm" variant="primary" loading={merging} disabled={!merge.text.trim()} onClick={() => void runMerge()}>
              合并
            </Button>
          </div>
          {mergeNotice &&
            (mergeNotice.tone === "danger" ? <Banner tone="danger">{mergeNotice.text}</Banner> : <p className="text-sm text-success" role="status">{mergeNotice.text}</p>)}
          <p className="text-xs text-fg-3">同一网站、路径和名称的 Cookie 会被新的替换，其余保留。</p>
        </div>
      )}
    </div>
  );
}
