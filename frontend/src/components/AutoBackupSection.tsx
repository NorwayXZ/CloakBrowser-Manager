import { CalendarClock, Play, Save } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type AutoBackupSettings, type AutoBackupStatus } from "../lib/api";

interface AutoBackupSectionProps {
  runningCount: number;
  onBackedUp: () => Promise<void> | void;
}

type Notice = { tone: "success" | "error"; text: string };

const INTERVAL_OPTIONS: [number, string][] = [
  [1, "每天"],
  [3, "每 3 天"],
  [7, "每周（推荐）"],
  [14, "每两周"],
  [30, "每月"],
];

function formatTime(value: string | null): string {
  if (!value) return "还没有";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function settingsOf(status: AutoBackupStatus): AutoBackupSettings {
  return {
    enabled: status.enabled,
    interval_days: status.interval_days,
    keep: status.keep,
    copy_dir: status.copy_dir,
  };
}

export function AutoBackupSection({ runningCount, onBackedUp }: AutoBackupSectionProps) {
  const [status, setStatus] = useState<AutoBackupStatus | null>(null);
  const [draft, setDraft] = useState<AutoBackupSettings | null>(null);
  const [copyEnabled, setCopyEnabled] = useState(true);
  const [busy, setBusy] = useState<"save" | "run" | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const apply = (next: AutoBackupStatus) => {
    setStatus(next);
    setDraft(settingsOf(next));
    setCopyEnabled(Boolean(next.copy_dir));
  };

  const load = useCallback(async () => {
    try {
      apply(await api.getAutoBackup());
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "读取自动备份设置失败" });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!status || !draft) {
    return null;
  }

  const effectiveDraft: AutoBackupSettings = {
    ...draft,
    copy_dir: copyEnabled ? (draft.copy_dir?.trim() || status.default_copy_dir) : null,
  };
  const changed = JSON.stringify(effectiveDraft) !== JSON.stringify(settingsOf(status));

  const handleSave = async () => {
    setBusy("save");
    setNotice(null);
    try {
      apply(await api.saveAutoBackup(effectiveDraft));
      setNotice({ tone: "success", text: "自动备份设置已保存。" });
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "保存失败" });
    } finally {
      setBusy(null);
    }
  };

  const handleRun = async () => {
    setBusy("run");
    setNotice(null);
    try {
      const result = await api.runAutoBackup();
      apply(result.status);
      await onBackedUp();
      setNotice(
        result.copy_error
          ? { tone: "error", text: result.copy_error }
          : { tone: "success", text: `已备份：${result.name}${result.copy ? `\n另存一份在：${result.copy}` : ""}` },
      );
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "备份失败" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="max-w-4xl overflow-hidden rounded-md border border-border bg-white">
      <div className="flex items-start gap-3 border-b border-border px-5 py-4">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-violet-50 text-violet-700">
          <CalendarClock className="h-4 w-4" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-slate-900">自动完整备份</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            到时间后，在没有浏览器打开的时候自动做一次完整备份，并另存一份到数据目录之外。即使数据目录被清理软件删掉，也能从那里恢复。只会清理自动备份，手动备份一份都不删。
          </p>
        </div>
      </div>

      <div className="grid max-w-3xl grid-cols-[120px_minmax(0,1fr)] items-start gap-x-5 gap-y-4 p-5">
        <label className="pt-0.5 text-right text-sm font-medium text-slate-600">自动备份</label>
        <label className="flex items-center gap-2 text-sm text-slate-800">
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
          />
          <span>开启</span>
        </label>

        <label className="pt-2 text-right text-sm font-medium text-slate-600">频率</label>
        <div className="flex flex-wrap items-center gap-3">
          <select
            className="input w-40"
            aria-label="备份频率"
            value={draft.interval_days}
            onChange={(e) => setDraft({ ...draft, interval_days: Number(e.target.value) })}
          >
            {INTERVAL_OPTIONS.map(([days, label]) => (
              <option key={days} value={days}>{label}</option>
            ))}
            {!INTERVAL_OPTIONS.some(([days]) => days === draft.interval_days) && (
              <option value={draft.interval_days}>每 {draft.interval_days} 天</option>
            )}
          </select>
          <span className="text-sm text-slate-600">保留最近</span>
          <input
            className="input w-20 no-spin"
            type="number"
            min={1}
            max={52}
            aria-label="保留份数"
            value={draft.keep}
            onChange={(e) => setDraft({ ...draft, keep: Math.min(52, Math.max(1, Number(e.target.value) || 1)) })}
          />
          <span className="text-sm text-slate-600">份</span>
        </div>

        <label className="pt-0.5 text-right text-sm font-medium text-slate-600">另存一份</label>
        <div>
          <label className="flex items-center gap-2 text-sm text-slate-800">
            <input type="checkbox" checked={copyEnabled} onChange={(e) => setCopyEnabled(e.target.checked)} />
            <span>复制到数据目录之外</span>
          </label>
          {copyEnabled && (
            <input
              className="input mt-2 w-full max-w-xl text-xs"
              aria-label="另存目录"
              value={draft.copy_dir ?? ""}
              placeholder={status.default_copy_dir}
              onChange={(e) => setDraft({ ...draft, copy_dir: e.target.value })}
            />
          )}
          <div className="mt-1 text-xs leading-5 text-slate-500">
            留空用默认位置。也可以填移动硬盘或网盘同步文件夹的完整路径。
          </div>
        </div>

        <label className="text-right text-sm font-medium text-slate-600">状态</label>
        <div className="space-y-1 text-xs text-slate-600">
          <div>上次自动备份：{formatTime(status.last_at)}</div>
          <div>
            下次：{status.enabled ? formatTime(status.next_due_at) : "已关闭"}
            {status.waiting_for_browsers && <span className="ml-2 text-amber-700">（已到时间，等浏览器全部关闭后开始）</span>}
          </div>
          {status.last_copy && <div className="break-all">最近一份另存在：{status.last_copy}</div>}
          {status.last_error && <div className="break-all text-red-600">{status.last_error}</div>}
        </div>

        <div />
        <div className="flex flex-wrap gap-2">
          <button
            className="btn-primary flex items-center gap-1.5 px-4 disabled:opacity-60"
            disabled={busy !== null || !changed}
            onClick={() => void handleSave()}
          >
            <Save className="h-4 w-4" />
            <span>{busy === "save" ? "保存中..." : "保存设置"}</span>
          </button>
          <button
            className="btn-secondary flex items-center gap-1.5 px-3 disabled:opacity-60"
            disabled={busy !== null || runningCount > 0}
            title={runningCount > 0 ? "请先关闭所有浏览器" : "现在就做一次自动备份"}
            onClick={() => void handleRun()}
          >
            <Play className="h-4 w-4" />
            <span>{busy === "run" ? "备份中..." : "立即备份一次"}</span>
          </button>
        </div>
      </div>

      {notice && (
        <div
          className={`whitespace-pre-line break-all border-t px-5 py-3 text-sm ${
            notice.tone === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-red-200 bg-red-50 text-red-800"
          }`}
        >
          {notice.text}
        </div>
      )}
    </div>
  );
}
