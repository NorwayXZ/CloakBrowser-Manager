import { AlertTriangle, CheckCircle2, Download, Loader2, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AppUpdateState } from "../lib/api";

interface AppUpdateStatusProps {
  /** Version offered by the last "升级" check, when a newer release exists. */
  available: string | null;
  downloadUrl: string | null;
  runningCount: number;
  /** Reload the page once the new version answers (overridable in tests). */
  onUpdated?: () => void;
}

const POLL_MS = 1000;
const RESTART_TIMEOUT_MS = 3 * 60 * 1000;
const ACTIVE = new Set(["checking", "downloading", "backing_up", "preparing", "restarting"]);

function percent(state: AppUpdateState): string {
  if (!state.total) return "";
  return ` ${Math.min(100, Math.round(((state.done ?? 0) / state.total) * 100))}%`;
}

export function AppUpdateStatus({ available, downloadUrl, runningCount, onUpdated }: AppUpdateStatusProps) {
  const [state, setState] = useState<AppUpdateState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stalled, setStalled] = useState(false);
  const restartingSince = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.getAppUpdate();
      setState(next);
      return next;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const active = state ? ACTIVE.has(state.phase) : false;

  // Follow the job while it runs; once the app restarts, wait for the new version.
  useEffect(() => {
    if (!active || !state) return undefined;
    const target = state.target;
    const timer = window.setInterval(async () => {
      if (state.phase === "restarting") {
        restartingSince.current ??= Date.now();
        try {
          const status = await api.getStatus();
          if (target && status.app_version === target) {
            window.clearInterval(timer);
            (onUpdated ?? (() => window.location.reload()))();
            return;
          }
        } catch {
          // The server is down while the app swaps itself; keep waiting.
        }
        if (Date.now() - restartingSince.current > RESTART_TIMEOUT_MS) {
          window.clearInterval(timer);
          setStalled(true);
        }
        return;
      }
      await refresh();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, onUpdated, refresh, state]);

  const handleStart = async () => {
    if (runningCount > 0) return;
    if (!confirm(`更新到 ${available}？\n会先做一次完整备份，下载校验后应用自动退出并重启，期间面板会断开几十秒。`)) return;
    setError(null);
    setStalled(false);
    try {
      setState(await api.startAppUpdate());
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新没能开始");
    }
  };

  const handleDismiss = async () => {
    await api.dismissAppUpdateResult().catch(() => undefined);
    await refresh();
  };

  const result = state?.last_result;
  const failed = state?.phase === "failed";

  if (active && state) {
    return (
      <div className="flex items-center gap-3 border-b border-blue-200 bg-blue-50 px-5 py-3 text-sm text-blue-900" role="status">
        <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
        <div>
          <div className="font-semibold">
            {state.label}
            {state.phase === "downloading" ? percent(state) : ""}
            {state.target ? `（${state.target}）` : ""}
          </div>
          {state.phase === "restarting" && (
            <div className="mt-0.5 text-xs">
              {stalled
                ? "等了 3 分钟还没看到新版本。请从菜单栏/托盘确认应用是否在运行，必要时手动重新打开。"
                : "应用正在退出并替换为新版本，新版本启动后这个页面会自动刷新。"}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <>
      {result && (
        <div
          className={`flex items-start gap-3 border-b px-5 py-3 text-sm ${
            result.ok ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-red-200 bg-red-50 text-red-900"
          }`}
        >
          {result.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}
          <div className="min-w-0 flex-1">
            <div className="font-semibold">
              {result.ok ? `已更新到 ${result.to}` : `更新到 ${result.to} 没有成功，仍在使用 ${result.running}`}
            </div>
            {!result.ok && (
              <div className="mt-0.5 break-words text-xs">
                {result.reason ? `原因：${result.reason}。` : ""}可以稍后再试，或手动下载安装包覆盖。
              </div>
            )}
          </div>
          <button className="rounded p-1 opacity-60 hover:bg-white hover:opacity-100" title="关闭" onClick={() => void handleDismiss()}>
            <XCircle className="h-4 w-4" />
          </button>
        </div>
      )}

      {available && state?.supported && (
        <div className="flex flex-wrap items-center gap-3 border-b border-blue-200 bg-blue-50 px-5 py-3 text-sm text-blue-900">
          <Download className="h-4 w-4 shrink-0" />
          <span className="font-semibold">新版本 {available} 可以一键更新</span>
          <button
            className="btn-primary px-3 text-xs disabled:opacity-60"
            disabled={runningCount > 0}
            title={runningCount > 0 ? "请先关闭所有浏览器" : undefined}
            onClick={() => void handleStart()}
          >
            立即更新
          </button>
          {runningCount > 0 && <span className="text-xs">请先关闭所有浏览器</span>}
          {downloadUrl && (
            <a className="text-xs underline" href={downloadUrl} target="_blank" rel="noreferrer">
              手动下载
            </a>
          )}
        </div>
      )}

      {(error || failed) && (
        <div className="flex items-start gap-3 border-b border-red-200 bg-red-50 px-5 py-3 text-sm text-red-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1 break-words">
            <span className="font-semibold">更新没有完成：</span>
            {error || state?.error}
            {downloadUrl && (
              <a className="ml-2 underline" href={downloadUrl} target="_blank" rel="noreferrer">手动下载</a>
            )}
          </div>
        </div>
      )}
    </>
  );
}
