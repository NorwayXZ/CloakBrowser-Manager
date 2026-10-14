import { Archive, Download, FolderOpen, History, RefreshCw, RotateCcw, Trash2, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type BackupItem } from "../lib/api";

interface BackupPanelProps {
  runningCount: number;
  onRefresh: () => Promise<void> | void;
}

type Notice = { tone: "success" | "error"; text: string };
type Busy = "full" | "restore" | "export" | "import" | null;

const RESTORE_WARNING =
  "恢复会用备份替换当前所有画像、Cookie 和登录状态。\n当前数据会先移到备份文件夹里的 before-restore-… 目录保存，不会删除。\n\n确定恢复吗？";

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function triggerDownload(href: string, filename: string) {
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export function BackupPanel({ runningCount, onRefresh }: BackupPanelProps) {
  const [items, setItems] = useState<BackupItem[]>([]);
  const [location, setLocation] = useState("");
  const [busy, setBusy] = useState<Busy>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const restoreInputRef = useRef<HTMLInputElement>(null);
  const configInputRef = useRef<HTMLInputElement>(null);
  const browsersRunning = runningCount > 0;
  const stopFirst = "请先关闭所有浏览器";

  const loadBackups = useCallback(async () => {
    try {
      const result = await api.listBackups();
      setItems(result.backups);
      setLocation(result.location);
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "读取备份列表失败" });
    }
  }, []);

  useEffect(() => {
    void loadBackups();
  }, [loadBackups]);

  const run = async (kind: Busy, task: () => Promise<string | null>) => {
    setBusy(kind);
    setNotice(null);
    try {
      const text = await task();
      if (text) setNotice({ tone: "success", text });
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "操作失败" });
    } finally {
      setBusy(null);
      await loadBackups();
    }
  };

  const handleCreateBackup = () =>
    run("full", async () => {
      const item = await api.createBackup();
      triggerDownload(api.backupDownloadUrl(item.name), item.name);
      return `完整备份已生成（${formatBytes(item.size)}），并开始下载。建议把下载的文件再复制到移动硬盘或网盘。`;
    });

  const restoredText = (profiles: number, previous: string) =>
    `已恢复 ${profiles} 个浏览器。原来的数据保存在：${previous}`;

  const handleRestoreItem = (item: BackupItem) => {
    const warning =
      item.kind === "auto"
        ? "自动快照只包含画像列表和设置，不包含 Cookie 等浏览器数据；浏览器数据会保持现状。\n当前数据库会先移到备份文件夹保存。\n\n确定恢复这个快照吗？"
        : RESTORE_WARNING;
    if (!confirm(warning)) return;
    void run("restore", async () => {
      const result = await api.restoreBackup(item);
      await onRefresh();
      return restoredText(result.profiles, result.previous_data);
    });
  };

  const handleRestoreFile = (file: File | null) => {
    if (restoreInputRef.current) restoreInputRef.current.value = "";
    if (!file || !confirm(RESTORE_WARNING)) return;
    void run("restore", async () => {
      const result = await api.restoreBackupFile(file);
      await onRefresh();
      return restoredText(result.profiles, result.previous_data);
    });
  };

  const handleDelete = (item: BackupItem) => {
    if (!confirm(`确定删除备份「${item.name}」吗？此操作不可恢复。`)) return;
    void run(null, async () => {
      await api.deleteBackup(item);
      return null;
    });
  };

  const handleReveal = () =>
    void run(null, async () => {
      await api.revealBackups();
      return null;
    });

  const handleExportConfiguration = () =>
    run("export", async () => {
      const backup = await api.exportConfiguration();
      const blob = new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      triggerDownload(url, `cloakbrowser-configuration-${new Date().toISOString().slice(0, 10)}.json`);
      URL.revokeObjectURL(url);
      return "配置备份已下载。文件包含代理和 Cookie，请妥善保管。";
    });

  const handleImportConfiguration = (file: File | null) => {
    if (configInputRef.current) configInputRef.current.value = "";
    if (!file) return;
    void run("import", async () => {
      const parsed: unknown = JSON.parse(await file.text());
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("备份文件格式不正确");
      }
      const result = await api.importConfiguration(parsed as Record<string, unknown>);
      await onRefresh();
      return `已导入 ${result.profiles} 个浏览器配置、${result.groups} 个新分组、${result.proxy_presets} 个代理。`;
    });
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
      <div className="max-w-4xl overflow-hidden rounded-md border border-border bg-white">
        <div className="border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold text-slate-900">完整备份（推荐）</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            包含所有浏览器的 Cookie、登录状态、历史记录、本地存储、标签页，以及画像列表、分组、代理和加密密钥。网页缓存不备份，打开网站时会自动重新生成。备份文件含账号登录信息，不要发给别人。
          </p>
        </div>
        <div className="grid gap-0 md:grid-cols-2">
          <div className="border-b border-border p-5 md:border-b-0 md:border-r">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-700">
                <Archive className="h-4 w-4" />
              </div>
              <div>
                <div className="text-sm font-semibold text-slate-900">立即备份</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">生成一个 .zip 文件，保存在备份文件夹并同时下载一份。</div>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                className="btn-primary flex items-center gap-1.5 px-4 disabled:opacity-60"
                disabled={busy !== null || browsersRunning}
                title={browsersRunning ? stopFirst : "备份全部浏览器数据"}
                onClick={() => void handleCreateBackup()}
              >
                <Archive className="h-4 w-4" />
                <span>{busy === "full" ? "备份中..." : "立即完整备份"}</span>
              </button>
              <button className="btn-secondary flex items-center gap-1.5 px-3" onClick={handleReveal} title={location}>
                <FolderOpen className="h-4 w-4" />
                <span>打开备份文件夹</span>
              </button>
            </div>
          </div>
          <div className="p-5">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-emerald-50 text-emerald-700">
                <RotateCcw className="h-4 w-4" />
              </div>
              <div>
                <div className="text-sm font-semibold text-slate-900">从备份文件恢复</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">选择之前下载的完整备份 .zip。也可以在下方列表直接恢复。</div>
              </div>
            </div>
            <input
              ref={restoreInputRef}
              type="file"
              accept="application/zip,.zip"
              className="hidden"
              onChange={(event) => handleRestoreFile(event.target.files?.[0] ?? null)}
            />
            <button
              className="btn-secondary mt-4 flex items-center gap-1.5 px-4 disabled:opacity-60"
              disabled={busy !== null || browsersRunning}
              title={browsersRunning ? stopFirst : "选择完整备份文件"}
              onClick={() => restoreInputRef.current?.click()}
            >
              <Upload className="h-4 w-4" />
              <span>{busy === "restore" ? "恢复中..." : "选择备份文件"}</span>
            </button>
          </div>
        </div>
        {browsersRunning && (
          <div className="border-t border-amber-200 bg-amber-50 px-5 py-3 text-xs leading-5 text-amber-800">
            有浏览器正在运行。为保证 Cookie 等数据完整，备份和恢复前请先关闭所有浏览器。
          </div>
        )}
      </div>

      {notice && (
        <div
          className={`max-w-4xl whitespace-pre-line break-all rounded-md border px-4 py-3 text-sm ${notice.tone === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-red-200 bg-red-50 text-red-800"}`}
        >
          {notice.text}
        </div>
      )}

      <div className="max-w-4xl overflow-hidden rounded-md border border-border bg-white">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">备份记录</h2>
            <p className="mt-0.5 text-xs text-slate-500">每次启动 Manager 会自动保存一份画像列表快照（保留最近 10 份）。</p>
          </div>
          <button className="btn-secondary flex items-center gap-1.5 px-3" onClick={() => void loadBackups()}>
            <RefreshCw className="h-4 w-4" />
            <span>刷新</span>
          </button>
        </div>
        {items.length === 0 ? (
          <div className="px-5 py-6 text-sm text-slate-500">还没有备份。</div>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {items.map((item) => (
                <tr key={`${item.kind}/${item.name}`} className="border-b border-border last:border-b-0">
                  <td className="px-5 py-2.5">
                    <div className="flex items-center gap-2">
                      {item.kind === "full" ? (
                        <Archive className="h-4 w-4 text-blue-600" />
                      ) : (
                        <History className="h-4 w-4 text-slate-400" />
                      )}
                      <span className="font-medium text-slate-800">{item.kind === "full" ? "完整备份" : "自动快照"}</span>
                    </div>
                    <div className="mt-0.5 text-xs text-slate-400">{item.name}</div>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-slate-500">{formatTime(item.created_at)}</td>
                  <td className="px-3 py-2.5 text-xs text-slate-500">{formatBytes(item.size)}</td>
                  <td className="px-5 py-2.5">
                    <div className="flex justify-end gap-1.5">
                      {item.kind === "full" && (
                        <a
                          className="btn-secondary flex items-center gap-1 px-2.5"
                          href={api.backupDownloadUrl(item.name)}
                          download={item.name}
                        >
                          <Download className="h-3.5 w-3.5" />
                          <span>下载</span>
                        </a>
                      )}
                      <button
                        className="btn-secondary flex items-center gap-1 px-2.5 disabled:opacity-60"
                        disabled={busy !== null || browsersRunning}
                        title={browsersRunning ? stopFirst : "恢复到这个备份"}
                        onClick={() => handleRestoreItem(item)}
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        <span>恢复</span>
                      </button>
                      <button
                        className="btn-secondary flex items-center gap-1 px-2.5 text-red-600 disabled:opacity-60"
                        disabled={busy !== null}
                        onClick={() => handleDelete(item)}
                        aria-label={`删除备份 ${item.name}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="max-w-4xl overflow-hidden rounded-md border border-border bg-white">
        <div className="border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold text-slate-900">只导出配置（JSON）</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            只包含浏览器配置、分组、代理和 Cookie JSON，不含登录状态和浏览记录。适合把设置迁移到另一台电脑；导入时会新建浏览器记录，同名代理会更新。
          </p>
        </div>
        <div className="flex flex-wrap gap-2 p-5">
          <button
            className="btn-secondary flex items-center gap-1.5 px-4 disabled:opacity-60"
            disabled={busy !== null}
            onClick={() => void handleExportConfiguration()}
          >
            <Download className="h-4 w-4" />
            <span>{busy === "export" ? "导出中..." : "下载配置备份"}</span>
          </button>
          <input
            ref={configInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(event) => handleImportConfiguration(event.target.files?.[0] ?? null)}
          />
          <button
            className="btn-secondary flex items-center gap-1.5 px-4 disabled:opacity-60"
            disabled={busy !== null || browsersRunning}
            title={browsersRunning ? stopFirst : "选择配置备份文件"}
            onClick={() => configInputRef.current?.click()}
          >
            <Upload className="h-4 w-4" />
            <span>{busy === "import" ? "导入中..." : "导入配置"}</span>
          </button>
        </div>
      </div>
    </section>
  );
}
