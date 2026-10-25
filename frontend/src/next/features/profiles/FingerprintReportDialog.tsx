import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { Badge, Banner, Button, Dialog, ErrorState, KeyValueList, Skeleton } from "../../ui";
import { profilesApi } from "./api";
import type { ExternalNetworkProbe, FingerprintIssue, FingerprintReport } from "./types";

function valueText(value: unknown) {
  if (value === null || value === undefined || value === "") return "空";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function scopeLabel(scope: string) {
  return scope === "main" ? "主页面" : scope === "worker" ? "Worker" : "iframe";
}

export function externalProbe(report: FingerprintReport): ExternalNetworkProbe | null {
  const main = report.raw.main as { network?: { externalProbe?: unknown } } | undefined;
  const probe = main?.network?.externalProbe;
  return probe && typeof probe === "object" ? (probe as ExternalNetworkProbe) : null;
}

const STATUS = {
  pass: { label: "通过", tone: "success" as const, Icon: CheckCircle2, iconClass: "text-success" },
  warning: { label: "有提示", tone: "warning" as const, Icon: AlertTriangle, iconClass: "text-warning" },
  fail: { label: "未通过", tone: "danger" as const, Icon: XCircle, iconClass: "text-danger" },
};

/** Runs the local fingerprint self-check of one running profile and shows the report. */
export function FingerprintReportDialog({ profileId, profileName, onClose }: { profileId: string; profileName: string; onClose: () => void }) {
  const query = useQuery({
    queryKey: ["profiles", profileId, "fingerprint-report"],
    queryFn: () => profilesApi.fingerprintReport(profileId),
    gcTime: 0,
    retry: false,
  });
  const report = query.data;

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      size="lg"
      title={`指纹自检 · ${profileName}`}
      description={
        report
          ? `${STATUS[report.analysis.status].label} · 错误 ${report.analysis.error_count} · 警告 ${report.analysis.warning_count}`
          : "检查主页面、iframe 和 Worker 的语言、时区和基础画像是否一致。"
      }
      footer={
        <>
          <Button onClick={() => void query.refetch()} loading={query.isFetching} disabled={query.isPending}>
            重新检测
          </Button>
          <Button variant="primary" onClick={onClose}>
            关闭
          </Button>
        </>
      }
    >
      {query.isPending ? (
        <div className="flex flex-col gap-3" aria-busy="true" aria-label="正在检测">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-2/3" />
        </div>
      ) : query.isError ? (
        <ErrorState title="指纹自检没有完成" message={query.error.message} onRetry={() => void query.refetch()} retrying={query.isFetching} />
      ) : report ? (
        <ReportBody report={report} />
      ) : null}
    </Dialog>
  );
}

function ReportBody({ report }: { report: FingerprintReport }) {
  const probe = externalProbe(report);
  const status = STATUS[report.analysis.status];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <status.Icon className={`h-5 w-5 ${status.iconClass}`} aria-hidden />
        <Badge tone={status.tone}>{status.label}</Badge>
        <span className="text-sm text-fg-2">
          {report.collection === "passive" ? "浏览器起始页自动采集" : "Manager 主动检查"} ·{" "}
          {report.expected.launch_mode === "manual" ? "日常模式，不开外部 CDP" : "调试模式"}
        </span>
      </div>

      <section aria-label="外部网络检查" className="rounded-md border border-border p-3">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-fg">外部网络检查</h3>
          <Badge tone={probe && !probe.error ? "success" : "warning"}>{probe && !probe.error ? "已收到探针结果" : "未完成外部检查"}</Badge>
        </div>
        {probe?.error ? (
          <p className="text-sm text-warning">{probe.error}。本次只显示本地代理策略。</p>
        ) : probe ? (
          <KeyValueList
            items={[
              { label: "出口 IP", value: <span className="font-mono">{probe.egress?.ip ?? "未知"}</span> },
              { label: "地区 / 时区", value: [probe.egress?.country, probe.egress?.city, probe.egress?.timezone].filter(Boolean).join(" · ") || "未知" },
              { label: "HTTP", value: probe.transport?.http_protocol ?? "未知" },
              { label: "TLS", value: <span className="break-all font-mono">{[probe.transport?.tls_version, probe.transport?.tls_cipher].filter(Boolean).join(" · ") || "未知"}</span> },
            ]}
          />
        ) : (
          <p className="text-sm text-warning">没有收到外部探针结果，TLS 和出口 IP 不能算作已验证。</p>
        )}
        <p className="mt-2 border-t border-border pt-2 text-xs text-fg-3">
          DNS：{report.network.dns_externally_verified ? "已由外部解析器验证" : "只启用了代理解析策略，没有经过外部 DNS 解析器验证"}。
        </p>
      </section>

      <KeyValueList
        items={[
          { label: "当前引擎", value: report.expected.browser_engine ?? "未知" },
          { label: "预期语言", value: report.expected.locale ?? "未设置" },
          { label: "预期时区", value: report.expected.timezone ?? "未设置" },
          { label: "外部 CDP", value: report.expected.external_cdp ? "已开启" : "未开启" },
          ...(report.proxy_geo
            ? [{ label: "代理地区", value: [report.proxy_geo.ip, [report.proxy_geo.country, report.proxy_geo.region, report.proxy_geo.city].filter(Boolean).join(" / ")].filter(Boolean).join(" · ") }]
            : []),
        ]}
      />
      <p className="text-xs text-fg-3">“预期语言 / 时区”是浏览器层的值；系统时区仍然是本机的系统时区，Manager 不会修改它。</p>

      {report.analysis.issues.length === 0 ? (
        <Banner tone="success">本地自检没有发现主页面、iframe、Worker 之间的语言、时区或基础画像不一致。</Banner>
      ) : (
        <ul className="flex flex-col gap-2" aria-label="发现的问题">
          {report.analysis.issues.map((issue, index) => (
            <IssueCard key={`${issue.scope}-${issue.signal}-${index}`} issue={issue} />
          ))}
        </ul>
      )}
    </div>
  );
}

function IssueCard({ issue }: { issue: FingerprintIssue }) {
  return (
    <li className={`rounded-md border p-3 text-sm ${issue.severity === "error" ? "border-danger/30 bg-danger-soft" : "border-warning/30 bg-warning-soft"}`}>
      <div className="font-medium text-fg">
        {scopeLabel(issue.scope)} · {issue.signal}
      </div>
      <p className="mt-0.5 text-fg-2">{issue.message}</p>
      <dl className="mt-2 grid grid-cols-2 gap-3 text-xs">
        <div className="min-w-0">
          <dt className="text-fg-3">期望</dt>
          <dd className="m-0 break-all text-fg">{valueText(issue.expected)}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-fg-3">实际</dt>
          <dd className="m-0 break-all text-fg">{valueText(issue.actual)}</dd>
        </div>
      </dl>
    </li>
  );
}
