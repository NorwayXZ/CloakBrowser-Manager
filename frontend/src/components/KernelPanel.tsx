import { CheckCircle2, Cpu, Download, HardDrive, RefreshCw, Save, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type KernelOverview, type KernelSettings } from "../lib/api";
import { formatBytes } from "./BackupPanel";

interface KernelPanelProps {
  runningCount: number;
}

type Notice = { tone: "success" | "info" | "error"; text: string };
type Busy = "load" | "check" | "update" | "save" | "delete" | null;

export function licenseText(license: KernelOverview["license"]): { label: string; detail: string } {
  switch (license.tier) {
    case "paid":
      return {
        label: `付费授权${license.plan ? `（${license.plan}）` : ""}`,
        detail: `使用 Pro 内核，可以锁定或回退版本${license.expires ? `；到期时间 ${license.expires}` : ""}。`,
      };
    case "free":
      return {
        label: "免费 GitHub 密钥",
        detail: "自动使用最新 Pro 内核，但不能锁定版本；同时运行的浏览器数量由官方限制。",
      };
    case "none":
      return {
        label: "未登录授权",
        detail: "使用公开发布的免费内核，版本比 Pro 内核旧。登录免费 GitHub 密钥即可用最新内核。",
      };
    case "invalid":
      return { label: "授权无效", detail: "密钥未通过官方验证，当前退回免费内核。" };
    default:
      return { label: "授权状态未知", detail: "暂时无法连上授权服务器，按上次结果运行。" };
  }
}

export function KernelPanel({ runningCount }: KernelPanelProps) {
  const [info, setInfo] = useState<KernelOverview | null>(null);
  const [draft, setDraft] = useState<KernelSettings | null>(null);
  const [latest, setLatest] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>("load");
  const [notice, setNotice] = useState<Notice | null>(null);
  const browsersRunning = runningCount > 0;

  const applyOverview = (overview: KernelOverview) => {
    setInfo(overview);
    setDraft(overview.settings);
  };

  const load = useCallback(async () => {
    try {
      applyOverview(await api.getKernel());
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "读取内核信息失败" });
    }
  }, []);

  useEffect(() => {
    void load().finally(() => setBusy(null));
  }, [load]);

  const run = async (kind: Busy, task: () => Promise<Notice | null>) => {
    setBusy(kind);
    setNotice(null);
    try {
      const result = await task();
      if (result) setNotice(result);
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "操作失败" });
    } finally {
      setBusy(null);
    }
  };

  const handleCheck = () =>
    run("check", async () => {
      const result = await api.checkKernel();
      setLatest(result.latest_version);
      if (result.pinned) {
        return { tone: "info", text: `官方最新版本是 ${result.latest_version}；当前锁定在 ${result.current_version}。` };
      }
      return result.update_available
        ? { tone: "info", text: `发现新内核 ${result.latest_version}（当前 ${result.current_version}），可以点击「立即更新」。` }
        : { tone: "success", text: `当前内核 ${result.current_version} 已是最新。` };
    });

  const handleUpdate = () =>
    run("update", async () => {
      const result = await api.updateKernel();
      await load();
      return { tone: result.updated ? "success" : "info", text: result.message };
    });

  const handleSave = () => {
    if (!draft) return;
    void run("save", async () => {
      applyOverview(await api.saveKernelSettings(draft));
      return { tone: "success", text: "内核设置已保存，下次启动浏览器时生效。" };
    });
  };

  const handleDelete = (name: string, version: string) => {
    if (!confirm(`删除内核 ${version}？\n以后如果需要，会重新下载。`)) return;
    void run("delete", async () => {
      const result = await api.deleteKernel(name);
      await load();
      return { tone: "success", text: `已删除内核 ${version}，释放 ${formatBytes(result.freed_bytes)}。` };
    });
  };

  if (!info || !draft) {
    return (
      <section className="flex-1 p-4">
        {notice ? (
          <div className="max-w-4xl rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{notice.text}</div>
        ) : (
          <div className="text-sm text-slate-500">正在读取内核信息...</div>
        )}
      </section>
    );
  }

  const license = licenseText(info.license);
  const oldKernels = info.installed_kernels.filter((kernel) => !kernel.in_use);
  const reclaimable = oldKernels.reduce((sum, kernel) => sum + kernel.size_bytes, 0);
  const settingsChanged = JSON.stringify(draft) !== JSON.stringify(info.settings);
  const pinChoices = info.installed_kernels.filter((kernel) => kernel.pro === (info.license.tier === "paid"));

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
      <div className="max-w-4xl overflow-hidden rounded-md border border-border bg-white">
        <div className="flex flex-wrap items-start justify-between gap-4 p-5">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-700">
              <Cpu className="h-5 w-5" />
            </div>
            <div>
              <div className="text-xs text-slate-500">当前使用的 CloakBrowser 内核</div>
              <div className="mt-0.5 text-xl font-semibold tracking-tight text-slate-900">
                {info.version ?? "未下载"}
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-700">{license.label}</span>
                {info.pinned && <span className="rounded bg-amber-100 px-2 py-0.5 text-amber-800">已锁定版本</span>}
                {info.settings.release_channel === "preview" && (
                  <span className="rounded bg-violet-100 px-2 py-0.5 text-violet-800">预览渠道</span>
                )}
                {!info.installed && <span className="rounded bg-red-100 px-2 py-0.5 text-red-700">首次启动时下载</span>}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="btn-secondary flex items-center gap-1.5 px-3 disabled:opacity-60"
              disabled={busy !== null}
              onClick={() => void handleCheck()}
            >
              <RefreshCw className={`h-4 w-4 ${busy === "check" ? "animate-spin" : ""}`} />
              <span>{busy === "check" ? "检查中..." : "检查更新"}</span>
            </button>
            <button
              className="btn-primary flex items-center gap-1.5 px-4 disabled:opacity-60"
              disabled={busy !== null}
              onClick={() => void handleUpdate()}
            >
              <Download className="h-4 w-4" />
              <span>{busy === "update" ? "下载并校验中..." : "立即更新"}</span>
            </button>
          </div>
        </div>
        <div className="grid gap-x-6 gap-y-1 border-t border-border bg-slate-50 px-5 py-3 text-xs text-slate-600 sm:grid-cols-2">
          <div>授权：{license.detail}</div>
          <div>官方最新：{latest ?? "点「检查更新」查看"}</div>
          <div>平台：{info.platform ?? "未知"}</div>
          <div>Wrapper：{info.wrapper_version ?? "未知"}（随 Manager 安装包更新）</div>
        </div>
        <div className="border-t border-border px-5 py-3 text-xs leading-5 text-slate-500">
          只有「伪装画像」引擎使用这个内核；「稳定原生」用的是电脑上的 Google Chrome，跟着 Chrome 自己更新。更新内核后，已打开的浏览器要关掉重开才会用上新内核。
        </div>
      </div>

      {notice && (
        <div
          className={`max-w-4xl whitespace-pre-line break-words rounded-md border px-4 py-3 text-sm ${
            notice.tone === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : notice.tone === "info"
              ? "border-blue-200 bg-blue-50 text-blue-800"
              : "border-red-200 bg-red-50 text-red-800"
          }`}
        >
          {notice.text}
        </div>
      )}

      <div className="max-w-4xl overflow-hidden rounded-md border border-border bg-white">
        <div className="border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold text-slate-900">更新方式</h2>
        </div>
        <div className="grid max-w-3xl grid-cols-[120px_minmax(0,1fr)] items-start gap-x-5 gap-y-4 p-5">
          <label className="pt-0.5 text-right text-sm font-medium text-slate-600">自动更新</label>
          <div>
            <label className="flex items-center gap-2 text-sm text-slate-800">
              <input
                type="checkbox"
                checked={draft.auto_update}
                onChange={(e) => setDraft({ ...draft, auto_update: e.target.checked })}
              />
              <span>启动浏览器时自动下载新内核</span>
            </label>
            <div className="mt-1 text-xs text-slate-500">关闭后一直用已下载的版本，需要时到这里手动更新。</div>
          </div>

          <label className="pt-2 text-right text-sm font-medium text-slate-600">更新渠道</label>
          <div>
            <select
              className="input max-w-sm"
              value={draft.release_channel}
              onChange={(e) => setDraft({ ...draft, release_channel: e.target.value as KernelSettings["release_channel"] })}
            >
              <option value="stable">稳定版（推荐）</option>
              <option value="preview">预览版</option>
            </select>
            <div className="mt-1 text-xs text-slate-500">预览版更早拿到新 Chrome 版本，但可能不稳定；没有预览版时自动用稳定版。</div>
          </div>

          <label className="pt-2 text-right text-sm font-medium text-slate-600">锁定版本</label>
          <div>
            <select
              className="input max-w-sm disabled:bg-slate-50 disabled:text-slate-400"
              value={draft.pinned_version ?? ""}
              disabled={!info.license.can_pin}
              onChange={(e) => setDraft({ ...draft, pinned_version: e.target.value || null })}
            >
              <option value="">不锁定，跟随最新</option>
              {pinChoices.map((kernel) => (
                <option key={kernel.name} value={kernel.version}>{kernel.version}</option>
              ))}
              {draft.pinned_version && !pinChoices.some((kernel) => kernel.version === draft.pinned_version) && (
                <option value={draft.pinned_version}>{draft.pinned_version}</option>
              )}
            </select>
            <div className="mt-1 text-xs text-slate-500">
              {info.license.can_pin
                ? "新内核出问题时，可以锁定到一个已下载的旧版本；锁定期间不会自动更新。"
                : "免费 GitHub 密钥总是使用最新内核，官方不允许锁定版本。"}
            </div>
          </div>

          <div />
          <div>
            <button
              className="btn-primary flex items-center gap-1.5 px-4 disabled:opacity-60"
              disabled={busy !== null || !settingsChanged}
              onClick={handleSave}
            >
              <Save className="h-4 w-4" />
              <span>{busy === "save" ? "保存中..." : "保存设置"}</span>
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-4xl overflow-hidden rounded-md border border-border bg-white">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">已下载的内核</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              {oldKernels.length > 0
                ? `${oldKernels.length} 个旧版本没在用，共 ${formatBytes(reclaimable)}，可以删除释放空间。`
                : "没有可清理的旧版本。"}
            </p>
          </div>
          <button className="btn-secondary flex items-center gap-1.5 px-3" disabled={busy !== null} onClick={() => void load()}>
            <RefreshCw className="h-4 w-4" />
            <span>刷新</span>
          </button>
        </div>
        {info.installed_kernels.length === 0 ? (
          <div className="px-5 py-6 text-sm text-slate-500">还没有下载内核，第一次启动伪装画像时会自动下载。</div>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {info.installed_kernels.map((kernel) => (
                <tr key={kernel.name} className="border-b border-border last:border-b-0">
                  <td className="px-5 py-2.5">
                    <div className="flex items-center gap-2">
                      <HardDrive className="h-4 w-4 text-slate-400" />
                      <span className="font-medium text-slate-800">{kernel.version}</span>
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{kernel.pro ? "Pro" : "免费版"}</span>
                      {kernel.in_use && (
                        <span className="flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700">
                          <CheckCircle2 className="h-3 w-3" />
                          正在使用
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-slate-500">{formatBytes(kernel.size_bytes)}</td>
                  <td className="px-5 py-2.5">
                    <div className="flex justify-end">
                      {!kernel.in_use && (
                        <button
                          className="btn-secondary flex items-center gap-1 px-2.5 text-red-600 disabled:opacity-60"
                          disabled={busy !== null || browsersRunning}
                          title={browsersRunning ? "请先关闭所有浏览器" : `删除内核 ${kernel.version}`}
                          aria-label={`删除内核 ${kernel.version}`}
                          onClick={() => handleDelete(kernel.name, kernel.version)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          <span>删除</span>
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="border-t border-border px-5 py-2.5 text-xs text-slate-400">位置：{info.cache_dir}</div>
      </div>
    </section>
  );
}
