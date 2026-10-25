import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { Badge, Button, Dialog } from "../../ui";
import { cn } from "../../shared/lib/cn";
import type { Preflight, PreflightIssue, Profile } from "./types";

export interface PreflightEntry {
  profile: Profile;
  result: Preflight;
}

const STATUS = {
  pass: { label: "通过", tone: "success" as const },
  warning: { label: "有提示", tone: "warning" as const },
  fail: { label: "未通过", tone: "danger" as const },
};

function IssueIcon({ severity }: { severity: PreflightIssue["severity"] }) {
  const className = "mt-0.5 h-4 w-4 shrink-0";
  if (severity === "error") return <XCircle className={cn(className, "text-danger")} aria-label="错误" />;
  if (severity === "warning") return <AlertTriangle className={cn(className, "text-warning")} aria-label="提示" />;
  return <Info className={cn(className, "text-info")} aria-label="说明" />;
}

export function PreflightDialog({
  entries,
  onCancel,
  onConfirm,
}: {
  entries: PreflightEntry[];
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const blocked = entries.some((entry) => !entry.result.can_launch);
  const warnings = entries.reduce((sum, entry) => sum + entry.result.issues.filter((issue) => issue.severity === "warning").length, 0);
  const summary = blocked
    ? "有环境无法启动，请先修改它的配置。"
    : warnings
      ? `${warnings} 项提示不会阻止启动，确认后继续。`
      : "全部检查通过。";

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onCancel()}
      size="lg"
      title={entries.length > 1 ? `启动前检查（${entries.length} 个环境）` : "启动前检查"}
      description="检查的是浏览器兼容性和配置一致性，不是“反检测分数”。系统时区仍然是本机的系统时区。"
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <span className={cn("text-sm", blocked ? "text-danger" : "text-fg-2")}>{summary}</span>
          <div className="flex gap-2">
            <Button onClick={onCancel}>取消</Button>
            <Button variant="primary" disabled={blocked} onClick={onConfirm} autoFocus={!blocked}>
              继续启动
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {entries.map(({ profile, result }) => {
          const caps = result.capabilities as Record<string, unknown>;
          const status = STATUS[result.status];
          return (
            <article key={profile.id} className="rounded-md border border-border" aria-label={profile.name}>
              <header className="flex items-center justify-between gap-3 border-b border-border px-3 py-2.5">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-fg">{profile.name}</div>
                  <div className="text-xs text-fg-3">
                    {result.browser_engine === "cloakbrowser" ? "CloakBrowser 画像" : "系统 Chrome 原生"} ·{" "}
                    {result.launch_mode === "manual" ? "日常模式，不开外部 CDP" : "调试模式"}
                  </div>
                </div>
                <Badge tone={status.tone}>{status.label}</Badge>
              </header>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-b border-border px-3 py-2.5 text-xs sm:grid-cols-4">
                {[
                  ["外部 CDP", caps.external_cdp ? "已开启" : "未开启"],
                  ["画像参数", caps.fingerprint_args ? "CloakBrowser 底层" : "本机真实硬件"],
                  ["DNS 策略", caps.proxy_dns_policy === "proxy_host_resolver" ? "通过代理解析" : "直连"],
                  ["TLS", caps.tls_externally_verified ? "已外部验证" : "浏览器原生，未外部验证"],
                ].map(([label, value]) => (
                  <div key={label} className="min-w-0">
                    <dt className="text-fg-3">{label}</dt>
                    <dd className="m-0 text-fg">{value}</dd>
                  </div>
                ))}
              </dl>
              {result.issues.length > 0 ? (
                <ul className="divide-y divide-border px-3">
                  {result.issues.map((issue) => (
                    <li key={`${issue.code}-${issue.message}`} className="flex gap-2 py-2 text-sm text-fg-2">
                      <IssueIcon severity={issue.severity} />
                      <span className="min-w-0 break-words">{issue.message}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="flex items-center gap-2 px-3 py-2.5 text-sm text-success">
                  <CheckCircle2 className="h-4 w-4" aria-hidden />
                  没有发现配置冲突，可以启动。
                </p>
              )}
            </article>
          );
        })}
      </div>
    </Dialog>
  );
}
