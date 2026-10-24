import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileSearch, Play, ShieldCheck, Trash2, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { cn } from "../../shared/lib/cn";
import { Badge, Banner, Button, buttonClass, Dialog, EmptyState, ErrorState, FormField, IconButton, ProgressBar, Section, Select, Skeleton, useConfirm, useToast } from "../../ui";
import { AutomationHoursHint } from "../app/AutomationHoursHint";
import { profileKeys, useProfiles } from "../profiles/api";
import { isRunning } from "../profiles/format";
import { ACTIVE_PHASES, checkKeys, checksApi, formatTime, OVERALL_LABEL, STATUS_LABEL, STATUS_TONE, useCheckState, type CheckStatus, type Report } from "./api";

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export function StatusBadge({ status }: { status: CheckStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Badge>;
}

/**
 * One-click check: open a profile headless in debug mode, run the local probe,
 * visit each detection site, save a report. Reports list on the left, the
 * selected one on the right (?report=id).
 */
export function ReportsTab() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("report");
  const profiles = useProfiles();
  const sites = useQuery({ queryKey: checkKeys.sites, queryFn: checksApi.sites, staleTime: Infinity });
  const state = useCheckState();
  const reports = useQuery({ queryKey: checkKeys.reports, queryFn: checksApi.reports });
  const [profileId, setProfileId] = useState("");
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const list = profiles.data ?? [];
  const candidate = list.find((p) => p.id === profileId) ?? list[0];
  const phase = state.data?.phase ?? "idle";
  const active = ACTIVE_PHASES.has(phase);
  const candidateRunning = candidate ? isRunning(candidate) : false;

  const select = (id: string | null) =>
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (id) next.set("report", id);
      else next.delete("report");
      return next;
    }, { replace: true });

  // When a check finishes, refresh the list and open its report.
  const wasActive = useRef(false);
  useEffect(() => {
    if (active) wasActive.current = true;
    else if (wasActive.current) {
      wasActive.current = false;
      void queryClient.invalidateQueries({ queryKey: checkKeys.reports });
      void queryClient.invalidateQueries({ queryKey: profileKeys.list });
      if (state.data?.report_id) select(state.data.report_id);
    }
  }, [active, queryClient, select, state.data?.report_id]);

  const start = async () => {
    if (!candidate) return;
    const ok = await confirm({
      title: `对「${candidate.name}」生成一键检测报告？`,
      description: `会在后台用调试模式打开这个环境（不弹窗），先做本地一致性自检，再依次访问 ${sites.data?.length || 7} 个检测网站，大约需要 5 分钟，测完自动关闭。期间不要操作这个环境。`,
      confirmLabel: "开始检测",
    });
    if (!ok) return;
    setStarting(true);
    setStartError(null);
    try {
      queryClient.setQueryData(checkKeys.state, await checksApi.start(candidate.id));
      select(null);
    } catch (error) {
      setStartError(message(error));
    } finally {
      setStarting(false);
    }
  };

  const remove = async (id: string) => {
    const ok = await confirm({ title: "删除这份检测报告和截图？", confirmLabel: "删除", danger: true });
    if (!ok) return;
    try {
      await checksApi.remove(id);
      if (selectedId === id) select(null);
      toast.show({ tone: "success", title: "已删除报告" });
    } catch (error) {
      toast.show({ tone: "error", title: "没有删除", description: message(error) });
    } finally {
      void queryClient.invalidateQueries({ queryKey: checkKeys.reports });
    }
  };

  const current = state.data;
  const currentSite = sites.data?.find((site) => site.id === current?.site);
  const siteLabel = currentSite?.name ?? (current?.site?.startsWith("local_") ? "本地自检" : current?.site ?? "");
  const total = current?.total ?? 7;
  const step = Math.min((current?.index ?? 0) + 1, total);

  return (
    <div className="flex flex-col gap-5">
      <Section
        id="site-check"
        title="一键检测报告"
        description="在后台无头打开环境（报告会注明无头运行），先用 Manager 自带探针逐项核对 UA、平台、GPU、时区、语言、CPU、内存、WebGL、Canvas、Audio、字体、WebRTC 和出口 IP，再依次访问下面的网站，读出每个网站的结论并截图。"
      >
        <div className="flex flex-col gap-4">
          <details className="rounded-md border border-border">
            <summary className="cursor-pointer px-3 py-2 text-sm text-fg-2">检测哪些网站（{sites.data?.length ?? "…"} 个）</summary>
            <ul className="grid grid-cols-1 gap-x-6 gap-y-1 border-t border-border px-3 py-2 text-xs text-fg-2 md:grid-cols-2">
              {(sites.data ?? []).map((site) => (
                <li key={site.id}>
                  <span className="font-medium text-fg">{site.name}</span>：{site.criteria}
                </li>
              ))}
            </ul>
          </details>
          <div className="flex flex-wrap items-end gap-2">
            <FormField label="检测的环境" className="w-72 max-w-full">
              <Select value={candidate?.id ?? ""} disabled={active || list.length === 0} onChange={(event) => setProfileId(event.target.value)}>
                {list.length === 0 && <option value="">还没有环境</option>}
                {list.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.name}
                  </option>
                ))}
              </Select>
            </FormField>
            <Button variant="primary" icon={<Play className="h-4 w-4" />} loading={starting} disabled={active || !candidate || candidateRunning} title={candidateRunning ? "请先关闭这个环境的浏览器" : undefined} onClick={() => void start()}>
              开始一键检测
            </Button>
          </div>
          {candidateRunning && <p className="text-xs text-warning">这个环境的浏览器正在运行，请先关闭它。</p>}
          <AutomationHoursHint />
          {startError && <Banner tone="danger" title="检测没能开始">{startError}</Banner>}
        </div>
      </Section>

      {(active || phase === "failed") && current && (
        <div role="status" className={cn("flex flex-col gap-2 rounded-md border p-4", phase === "failed" ? "border-danger/30 bg-danger-soft" : "border-accent/30 bg-accent-soft")}>
          {phase === "failed" ? (
            <p className="text-sm text-fg">
              <span className="font-semibold">检测没有完成：</span>
              {current.error}
            </p>
          ) : (
            <>
              <p className="text-sm font-semibold text-fg">
                {phase === "launching" && `正在用调试模式打开「${current.profile_name}」`}
                {phase === "checking" && `正在检测「${current.profile_name}」：${siteLabel}（${step}/${total}）`}
                {phase === "closing" && "检测完成，正在关闭浏览器"}
              </p>
              <ProgressBar value={phase === "checking" ? (step / total) * 100 : phase === "closing" ? 100 : null} label="检测进度" />
            </>
          )}
          {(current.results ?? []).length > 0 && (
            <ul className="flex flex-col gap-1 text-xs">
              {(current.results ?? []).map((result) => (
                <li key={result.site} className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={result.status} />
                  <span className="font-medium text-fg">{result.name}</span>
                  <span className="text-fg-2">{result.summary}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
        <Section id="report-list" title="检测报告">
          {reports.isPending ? (
            <Skeleton className="h-32 w-full" />
          ) : reports.isError ? (
            <ErrorState message={reports.error.message} onRetry={() => void reports.refetch()} />
          ) : reports.data.length === 0 ? (
            <EmptyState icon={ShieldCheck} title="还没有检测报告" description="选一个环境，点“开始一键检测”。" />
          ) : (
            <ul className="-mx-2 flex flex-col gap-0.5" aria-label="报告">
              {reports.data.map((report) => (
                <li key={report.id} className="group/report flex items-center gap-1">
                  <button
                    type="button"
                    aria-current={selectedId === report.id ? "true" : undefined}
                    onClick={() => select(report.id)}
                    className={cn(
                      "flex min-w-0 flex-1 flex-col rounded px-2 py-1.5 text-left transition-colors duration-fast",
                      selectedId === report.id ? "bg-accent-soft" : "hover:bg-surface-2",
                    )}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-sm font-medium text-fg">{report.profile_name ?? report.id}</span>
                      {report.overall && <StatusBadge status={report.overall} />}
                    </span>
                    <span className="text-xs text-fg-3">
                      {formatTime(report.created_at)} · {report.passed}/{report.total} 通过
                    </span>
                  </button>
                  <IconButton size="sm" variant="danger-ghost" label={`删除报告 ${report.profile_name ?? report.id}`} icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => void remove(report.id)} />
                </li>
              ))}
            </ul>
          )}
        </Section>
        {selectedId ? (
          <ReportDetail id={selectedId} onClose={() => select(null)} />
        ) : (
          (reports.data?.length ?? 0) > 0 && (
            <div className="rounded-md border border-dashed border-border-strong bg-surface">
              <EmptyState icon={FileSearch} title="选一份报告查看" description="能看到每个网站的结论、截图，以及和这个环境上一份报告的对比。" />
            </div>
          )
        )}
      </div>
    </div>
  );
}

function ReportDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const report = useQuery({ queryKey: checkKeys.report(id), queryFn: () => checksApi.report(id) });
  const [preview, setPreview] = useState<{ url: string; title: string } | null>(null);

  if (report.isPending) return <Skeleton className="h-80 w-full" />;
  if (report.isError) return <ErrorState title="报告没有打开" message={report.error.message} onRetry={() => void report.refetch()} />;
  const data: Report = report.data;
  const env = data.environment;
  const counts = data.summary ?? {
    pass: data.results.filter((r) => r.status === "pass").length,
    warn: data.results.filter((r) => r.status === "warn").length,
    fail: data.results.filter((r) => r.status === "fail").length,
    unknown: data.results.filter((r) => r.status === "unknown").length,
    error: data.results.filter((r) => r.status === "error").length,
    total: data.results.length,
  };
  const changed = new Set((data.diff?.changes ?? []).map((change) => change.site));
  const profileId = typeof env.profile_id === "string" ? env.profile_id : null;

  return (
    <section aria-label="报告详情" className="min-w-0 rounded-md border border-border bg-surface">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-start gap-2">
          {data.overall === "pass" ? <CheckCircle2 className="mt-0.5 h-5 w-5 text-success" aria-hidden /> : <XCircle className={cn("mt-0.5 h-5 w-5", data.overall === "warn" ? "text-warning" : "text-danger")} aria-hidden />}
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-fg">
              {String(env.profile_name ?? "")}：{OVERALL_LABEL[data.overall]}
            </h2>
            <p className="text-xs text-fg-3">
              {formatTime(data.created_at)} · {String(env.host_os ?? "")} · 内核 {String(env.kernel_version ?? "-")} · 出口 {String(env.exit_ip ?? "直连")} {String(env.exit_country ?? "")}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {profileId && (
            <Link className={buttonClass("ghost", "sm")} to={`/profiles?p=${encodeURIComponent(profileId)}`}>
              查看环境
            </Link>
          )}
          <a className={buttonClass("secondary", "sm")} href={checksApi.downloadUrl(data.id)} download>
            <Download className="h-3.5 w-3.5" aria-hidden />
            导出报告（zip）
          </a>
          <Button size="sm" variant="ghost" onClick={onClose}>
            关闭
          </Button>
        </div>
      </header>
      <div className="flex flex-col gap-2 border-b border-border px-4 py-3 text-sm text-fg-2">
        <p>
          共 {counts.total} 项：通过 {counts.pass} · 警告 {counts.warn} · 未通过 {counts.fail}
          {counts.unknown > 0 && <> · 未读到结论 {counts.unknown}</>}
          {counts.error > 0 && <> · 出错 {counts.error}</>}
        </p>
        {data.egress_note && <p className="text-warning">{data.egress_note}</p>}
        {data.diff &&
          (data.diff.changes.length === 0 ? (
            <p className="text-fg-3">与上次报告（{formatTime(data.diff.previous_created_at)}）相比，各条目结论没有变化。</p>
          ) : (
            <div>
              <p className="font-medium text-fg">与上次报告（{formatTime(data.diff.previous_created_at)}）相比的变化：</p>
              <ul className="mt-1 flex flex-col gap-1">
                {data.diff.changes.map((change) => (
                  <li key={change.site} className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-fg">{change.name ?? change.site}</span>
                    {change.from ? <StatusBadge status={change.from} /> : <span className="text-fg-3">新增</span>}
                    <span aria-hidden>→</span>
                    {change.to ? <StatusBadge status={change.to} /> : <span className="text-fg-3">本次未检</span>}
                    {change.summary && <span className="text-fg-3">{change.summary}</span>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
      </div>
      <ul className="divide-y divide-border">
        {data.results.map((result) => (
          <li key={result.site} data-changed={changed.has(result.site) || undefined} className={cn("grid grid-cols-1 gap-3 px-4 py-3 sm:grid-cols-[140px_minmax(0,1fr)_auto]", changed.has(result.site) && "bg-warning-soft")}>
            <div className="flex flex-col items-start gap-1">
              <span className="font-medium text-fg">{result.name}</span>
              {result.source === "local" && <Badge tone="info">本地自检</Badge>}
              <StatusBadge status={result.status} />
              {changed.has(result.site) && <Badge tone="warning">和上次不同</Badge>}
            </div>
            <div className="min-w-0 text-sm">
              <p className="text-fg">{result.summary}</p>
              {result.details.length > 0 && (
                <ul className="mt-1 flex flex-col gap-0.5 text-xs text-fg-2">
                  {result.details.map((detail) => (
                    <li key={detail} className="break-words">
                      {detail}
                    </li>
                  ))}
                </ul>
              )}
              {result.ip_note && <p className="mt-1 text-xs text-warning">IP 信誉：{result.ip_note}</p>}
              <p className="mt-1 text-xs text-fg-3">标准：{result.criteria}</p>
            </div>
            {result.screenshot && (
              <button
                type="button"
                className="h-20 w-32 overflow-hidden rounded border border-border"
                title="查看大图"
                onClick={() => setPreview({ url: checksApi.fileUrl(data.id, result.screenshot!), title: result.name })}
              >
                <img src={checksApi.fileUrl(data.id, result.screenshot)} alt={`${result.name} 截图`} className="h-full w-full object-cover object-top" loading="lazy" />
              </button>
            )}
          </li>
        ))}
      </ul>
      {preview && (
        <Dialog open onOpenChange={(open) => !open && setPreview(null)} title={`${preview.title} 截图`} size="lg">
          <img src={preview.url} alt={`${preview.title} 截图`} className="max-w-full rounded border border-border" />
        </Dialog>
      )}
    </section>
  );
}
