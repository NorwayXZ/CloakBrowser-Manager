import { AlertTriangle, CheckCircle2, Info, ShieldAlert, X, XCircle } from "lucide-react";
import type { PreflightResult } from "../lib/api";

export interface PreflightEntry {
  id: string;
  name: string;
  result: PreflightResult;
}

interface PreflightDialogProps {
  entries: PreflightEntry[];
  onCancel: () => void;
  onConfirm: () => void;
}

function statusLabel(status: PreflightResult["status"]) {
  if (status === "pass") return "通过";
  if (status === "warning") return "有提示";
  return "未通过";
}

function issueIcon(severity: "error" | "warning" | "info") {
  if (severity === "error") return <XCircle className="h-4 w-4 text-red-600" />;
  if (severity === "warning") return <AlertTriangle className="h-4 w-4 text-amber-600" />;
  return <Info className="h-4 w-4 text-blue-600" />;
}

export function PreflightDialog({ entries, onCancel, onConfirm }: PreflightDialogProps) {
  const blocked = entries.some((entry) => !entry.result.can_launch);
  const warnings = entries.reduce(
    (count, entry) => count + entry.result.issues.filter((issue) => issue.severity === "warning").length,
    0,
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 px-4 py-6">
      <section className="flex max-h-[min(820px,calc(100vh-48px))] w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-border bg-white shadow-2xl">
        <header className="flex items-start justify-between border-b border-border px-5 py-4">
          <div className="flex items-start gap-3">
            <div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${blocked ? "bg-red-50 text-red-700" : warnings ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"}`}>
              {blocked ? <ShieldAlert className="h-5 w-5" /> : warnings ? <AlertTriangle className="h-5 w-5" /> : <CheckCircle2 className="h-5 w-5" />}
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-900">启动前检查</h2>
              <p className="mt-1 text-xs leading-5 text-slate-500">
                检查的是浏览器兼容性和配置一致性，不是“反检测分数”。System 时区仍然是本机系统时区。
              </p>
            </div>
          </div>
          <button
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            onClick={onCancel}
            title="关闭检查"
            aria-label="关闭检查"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto bg-slate-50 p-5">
          {entries.map(({ id, name, result }) => (
            <article key={id} className="rounded-md border border-border bg-white">
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-900">{name}</div>
                  <div className="mt-1 text-xs text-slate-500">
                    {result.browser_engine === "cloakbrowser" ? "CloakBrowser 画像" : "系统 Chrome 原生"} · {result.launch_mode === "manual" ? "日常无外部 CDP" : "调试模式"}
                  </div>
                </div>
                <span className={`ml-3 inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${result.status === "pass" ? "bg-emerald-50 text-emerald-700" : result.status === "warning" ? "bg-amber-50 text-amber-700" : "bg-red-50 text-red-700"}`}>
                  {result.status === "pass" ? <CheckCircle2 className="h-3.5 w-3.5" /> : result.status === "warning" ? <AlertTriangle className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
                  {statusLabel(result.status)}
                </span>
              </div>

              <div className="grid gap-2 border-b border-border px-4 py-3 text-xs text-slate-600 sm:grid-cols-4">
                <div><span className="text-slate-400">外部 CDP</span><br />{Boolean(result.capabilities.external_cdp) ? "已开启" : "未开启"}</div>
                <div><span className="text-slate-400">画像参数</span><br />{Boolean(result.capabilities.fingerprint_args) ? "CloakBrowser 底层" : "本机真实硬件"}</div>
                <div><span className="text-slate-400">DNS 策略</span><br />{result.capabilities.proxy_dns_policy === "proxy_host_resolver" ? "通过代理解析" : "直连"}</div>
                <div><span className="text-slate-400">TLS</span><br />{Boolean(result.capabilities.tls_externally_verified) ? "已外部验证" : "浏览器原生，未外部验证"}</div>
              </div>

              {result.issues.length > 0 ? (
                <ul className="divide-y divide-slate-100 px-4">
                  {result.issues.map((issue) => (
                    <li key={`${issue.code}-${issue.message}`} className="flex gap-2 py-2.5 text-xs leading-5 text-slate-600">
                      {issueIcon(issue.severity)}
                      <span>{issue.message}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="px-4 py-3 text-xs text-emerald-700">没有发现配置冲突，可以启动。</div>
              )}
            </article>
          ))}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-border bg-white px-5 py-4">
          <div className="text-xs text-slate-500">
            {blocked ? "有画像无法启动，请返回编辑配置。" : warnings ? `${warnings} 项提示不会阻止启动，请确认后继续。` : "所有画像检查通过。"}
          </div>
          <div className="flex shrink-0 gap-2">
            <button className="btn-secondary px-4" onClick={onCancel}>取消</button>
            <button className="btn-primary px-4 disabled:cursor-not-allowed disabled:opacity-50" disabled={blocked} onClick={onConfirm}>继续启动</button>
          </div>
        </footer>
      </section>
    </div>
  );
}
