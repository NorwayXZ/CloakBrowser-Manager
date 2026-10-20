import { CheckCircle2, Download, Loader2, Play, RefreshCw, ShieldCheck, Trash2, X, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  type Profile,
  type SiteCheckReport,
  type SiteCheckReportSummary,
  type SiteCheckSite,
  type SiteCheckState,
  type SiteCheckStatus,
} from "../lib/api";

interface SiteCheckPanelProps {
  profiles: Profile[];
  onRefresh: () => Promise<void> | void;
}

const ACTIVE = new Set(["launching", "checking", "closing"]);
const POLL_MS = 2000;

const STATUS_LABELS: Record<SiteCheckStatus, string> = {
  pass: "通过",
  warn: "警告",
  fail: "未通过",
  unknown: "未读到结论",
  error: "出错",
};

const STATUS_STYLES: Record<SiteCheckStatus, string> = {
  pass: "bg-emerald-50 text-emerald-700",
  warn: "bg-amber-50 text-amber-700",
  fail: "bg-red-50 text-red-700",
  unknown: "bg-slate-100 text-slate-600",
  error: "bg-red-50 text-red-700",
};

const OVERALL_LABELS: Record<"pass" | "warn" | "fail", string> = { pass: "全部通过", warn: "有警告", fail: "未通过" };

function StatusBadge({ status }: { status: SiteCheckStatus }) {
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}>{STATUS_LABELS[status]}</span>;
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function SiteCheckPanel({ profiles, onRefresh }: SiteCheckPanelProps) {
  const [sites, setSites] = useState<SiteCheckSite[]>([]);
  const [state, setState] = useState<SiteCheckState>({ phase: "idle" });
  const [reports, setReports] = useState<SiteCheckReportSummary[]>([]);
  const [selected, setSelected] = useState<SiteCheckReport | null>(null);
  const [profileId, setProfileId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ url: string; title: string } | null>(null);
  const active = ACTIVE.has(state.phase);
  const candidate = profiles.find((profile) => profile.id === profileId);

  const loadReports = useCallback(async () => {
    try {
      setReports(await api.listSiteCheckReports());
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取报告失败");
    }
  }, []);

  useEffect(() => {
    void api.listSiteCheckSites().then(setSites).catch(() => undefined);
    void api.getSiteCheckState().then(setState).catch(() => undefined);
    void loadReports();
  }, [loadReports]);

  useEffect(() => {
    const first = profiles[0];
    if (!profileId && first) setProfileId(first.id);
  }, [profileId, profiles]);

  // Follow a running check; when it ends, refresh the list and open the report.
  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.getSiteCheckState();
        setState(next);
        if (!ACTIVE.has(next.phase)) {
          window.clearInterval(timer);
          await loadReports();
          await onRefresh();
          if (next.report_id) setSelected(await api.getSiteCheckReport(next.report_id));
        }
      } catch {
        // keep polling; the server may be busy
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, loadReports, onRefresh]);

  const handleStart = async () => {
    if (!candidate) return;
    if (!confirm(`对「${candidate.name}」做指纹检测？\n会用调试模式打开这个浏览器，依次访问 ${sites.length || 7} 个检测网站，大约需要 5 分钟，测完自动关闭。期间不要操作这个浏览器。`)) return;
    setError(null);
    setSelected(null);
    try {
      setState(await api.startSiteCheck(candidate.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "检测没能开始");
    }
  };

  const handleOpen = async (id: string) => {
    setError(null);
    try {
      setSelected(await api.getSiteCheckReport(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "打开报告失败");
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("删除这份检测报告和截图？")) return;
    await api.deleteSiteCheckReport(id).catch(() => undefined);
    if (selected?.id === id) setSelected(null);
    await loadReports();
  };

  const running = profiles.some((profile) => profile.id === profileId && profile.status === "running");
  const doneResults = state.results ?? [];
  const currentSite = sites.find((site) => site.id === state.site);

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
      <div className="max-w-5xl overflow-hidden rounded-md border border-border bg-white">
        <div className="flex items-start gap-3 border-b border-border px-5 py-4">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-700">
            <ShieldCheck className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-slate-900">用公开检测网站验收指纹</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              自动打开画像，依次访问下面的网站，读出每个网站的结论并截图。7 项都通过才算这个画像合格。报告可以导出 zip 发给开发者排查。
            </p>
          </div>
        </div>
        <ul className="grid gap-x-6 gap-y-1 px-5 py-3 text-xs text-slate-600 sm:grid-cols-2">
          {sites.map((site) => (
            <li key={site.id}>
              <span className="font-medium text-slate-800">{site.name}</span>：{site.criteria}
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap items-center gap-2 border-t border-border px-5 py-3">
          <select
            className="input w-72"
            aria-label="检测的画像"
            value={profileId}
            disabled={active}
            onChange={(e) => setProfileId(e.target.value)}
          >
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>{profile.name}</option>
            ))}
          </select>
          <button
            className="btn-primary flex items-center gap-1.5 px-4 disabled:opacity-60"
            disabled={active || !candidate || running}
            title={running ? "请先关闭这个浏览器" : undefined}
            onClick={() => void handleStart()}
          >
            <Play className="h-4 w-4" />
            <span>开始检测</span>
          </button>
          {running && <span className="text-xs text-amber-700">这个浏览器正在运行，请先关闭它。</span>}
        </div>
      </div>

      {error && (
        <div className="max-w-5xl rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>
      )}

      {(active || state.phase === "failed") && (
        <div className="max-w-5xl rounded-md border border-blue-200 bg-blue-50 px-5 py-3 text-sm text-blue-900" role="status">
          {state.phase === "failed" ? (
            <div className="text-red-800">检测没有完成：{state.error}</div>
          ) : (
            <div className="flex items-center gap-2 font-semibold">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>
                {state.phase === "launching" && `正在用调试模式打开「${state.profile_name}」`}
                {state.phase === "checking" && `正在检测「${state.profile_name}」：${currentSite?.name ?? state.site ?? ""}（${Math.min((state.index ?? 0) + 1, state.total ?? 7)}/${state.total ?? 7}）`}
                {state.phase === "closing" && "检测完成，正在关闭浏览器"}
              </span>
            </div>
          )}
          {doneResults.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs">
              {doneResults.map((result) => (
                <li key={result.site} className="flex items-center gap-2">
                  <StatusBadge status={result.status} />
                  <span className="font-medium">{result.name}</span>
                  <span className="text-blue-800">{result.summary}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {selected && (
        <div className="max-w-5xl overflow-hidden rounded-md border border-border bg-white">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-3">
            <div className="flex items-center gap-2">
              {selected.overall === "pass" ? (
                <CheckCircle2 className="h-5 w-5 text-emerald-600" />
              ) : (
                <XCircle className={`h-5 w-5 ${selected.overall === "warn" ? "text-amber-600" : "text-red-600"}`} />
              )}
              <div>
                <div className="text-sm font-semibold text-slate-900">
                  {String(selected.environment.profile_name ?? "")}：{OVERALL_LABELS[selected.overall]}
                </div>
                <div className="text-xs text-slate-500">
                  {formatTime(selected.created_at)} · {String(selected.environment.host_os ?? "")} · 内核 {String(selected.environment.kernel_version ?? "-")} · 出口 {String(selected.environment.exit_ip ?? "直连")} {String(selected.environment.exit_country ?? "")}
                </div>
              </div>
            </div>
            <div className="flex gap-2">
              <a className="btn-secondary flex items-center gap-1 px-3 text-xs" href={api.siteCheckDownloadUrl(selected.id)} download>
                <Download className="h-3.5 w-3.5" />
                <span>导出报告（zip）</span>
              </a>
              <button className="btn-secondary px-2" title="关闭报告" onClick={() => setSelected(null)}>
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
          <table className="w-full text-sm">
            <tbody>
              {selected.results.map((result) => (
                <tr key={result.site} className="border-b border-border align-top last:border-b-0">
                  <td className="w-36 px-5 py-3">
                    <div className="font-medium text-slate-800">{result.name}</div>
                    <div className="mt-1"><StatusBadge status={result.status} /></div>
                  </td>
                  <td className="px-3 py-3">
                    <div className="text-slate-800">{result.summary}</div>
                    {result.details.length > 0 && (
                      <ul className="mt-1 space-y-0.5 text-xs text-slate-500">
                        {result.details.map((detail) => <li key={detail}>{detail}</li>)}
                      </ul>
                    )}
                    <div className="mt-1 text-xs text-slate-400">标准：{result.criteria}</div>
                  </td>
                  <td className="w-40 px-5 py-3">
                    {result.screenshot && (
                      <button
                        className="block overflow-hidden rounded border border-border"
                        title="查看截图"
                        onClick={() => setPreview({ url: api.siteCheckFileUrl(selected.id, result.screenshot!), title: result.name })}
                      >
                        <img src={api.siteCheckFileUrl(selected.id, result.screenshot)} alt={`${result.name} 截图`} className="h-20 w-32 object-cover object-top" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="max-w-5xl overflow-hidden rounded-md border border-border bg-white">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-900">检测报告</h2>
          <button className="btn-secondary flex items-center gap-1.5 px-3" onClick={() => void loadReports()}>
            <RefreshCw className="h-4 w-4" />
            <span>刷新</span>
          </button>
        </div>
        {reports.length === 0 ? (
          <div className="px-5 py-6 text-sm text-slate-500">还没有检测报告。</div>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {reports.map((report) => (
                <tr key={report.id} className="border-b border-border last:border-b-0">
                  <td className="px-5 py-2.5">
                    <div className="font-medium text-slate-800">{report.profile_name ?? report.id}</div>
                    <div className="text-xs text-slate-400">{formatTime(report.created_at)} · {report.host_os ?? ""}</div>
                  </td>
                  <td className="px-3 py-2.5 text-xs">
                    {report.overall && <StatusBadge status={report.overall} />}
                    <span className="ml-2 text-slate-500">{report.passed}/{report.total} 通过</span>
                  </td>
                  <td className="px-5 py-2.5">
                    <div className="flex justify-end gap-1.5">
                      <button className="btn-secondary px-2.5 text-xs" onClick={() => void handleOpen(report.id)}>查看</button>
                      <a className="btn-secondary flex items-center px-2.5 text-xs" href={api.siteCheckDownloadUrl(report.id)} download title="导出报告">
                        <Download className="h-3.5 w-3.5" />
                      </a>
                      <button
                        className="btn-secondary px-2.5 text-red-600"
                        aria-label={`删除报告 ${report.id}`}
                        onClick={() => void handleDelete(report.id)}
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

      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" onClick={() => setPreview(null)}>
          <div className="max-h-full max-w-5xl overflow-auto rounded-md bg-white p-2" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-2 pb-2 text-sm font-medium">
              <span>{preview.title} 截图</span>
              <button className="btn-secondary px-2" title="关闭截图" onClick={() => setPreview(null)}><X className="h-4 w-4" /></button>
            </div>
            <img src={preview.url} alt={`${preview.title} 截图`} className="max-w-full" />
          </div>
        </div>
      )}
    </section>
  );
}
