import { Activity, AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useState } from "react";
import { api, type ExternalNetworkProbe, type FingerprintIssue, type FingerprintReport } from "../lib/api";

interface FingerprintReportButtonProps {
  profileId: string;
  disabled?: boolean;
  disabledReason?: string;
}

function valueText(value: unknown) {
  if (value === null || value === undefined || value === "") return "空";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function issueLabel(issue: FingerprintIssue) {
  const scope = issue.scope === "main" ? "主页面" : issue.scope === "worker" ? "Worker" : "iframe";
  return `${scope} · ${issue.signal}`;
}

function externalProbeFrom(report: FingerprintReport): ExternalNetworkProbe | null {
  const main = report.raw.main;
  if (!main || typeof main !== "object") return null;
  const network = (main as { network?: unknown }).network;
  if (!network || typeof network !== "object") return null;
  const probe = (network as { externalProbe?: unknown }).externalProbe;
  return probe && typeof probe === "object" ? probe as ExternalNetworkProbe : null;
}

export function FingerprintReportButton({
  profileId,
  disabled,
  disabledReason = "先启动浏览器",
}: FingerprintReportButtonProps) {
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<FingerprintReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runReport = async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await api.getFingerprintReport(profileId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "指纹自检失败");
      setReport(null);
    } finally {
      setLoading(false);
    }
  };

  const statusIcon = report?.analysis.status === "pass"
    ? <CheckCircle2 className="h-4 w-4 text-emerald-400" />
    : report?.analysis.status === "warning"
      ? <AlertTriangle className="h-4 w-4 text-yellow-400" />
      : <XCircle className="h-4 w-4 text-red-400" />;

  return (
    <>
      <button
        onClick={runReport}
        disabled={disabled || loading}
        className="btn-secondary flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
        title={disabled ? disabledReason : "运行指纹自检"}
      >
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Activity className="h-3.5 w-3.5" />}
        <span>{loading ? "检测中..." : "指纹自检"}</span>
      </button>

      {(report || error) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
          <div className="w-full max-w-2xl rounded-md border border-border bg-surface-1 shadow-xl">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <div className="flex items-center gap-2">
                {report ? statusIcon : <XCircle className="h-4 w-4 text-red-400" />}
                <div>
                  <div className="text-sm font-semibold">指纹自检报告</div>
                  {report && (
                    <div className="text-xs text-gray-500">
                      状态 {report.analysis.status === "pass" ? "通过" : report.analysis.status === "warning" ? "有提示" : "未通过"} · 错误 {report.analysis.error_count} · 警告 {report.analysis.warning_count}
                    </div>
                  )}
                </div>
              </div>
              <button
                onClick={() => {
                  setReport(null);
                  setError(null);
                }}
                className="text-slate-500 hover:text-slate-900"
              >
                关闭
              </button>
            </div>

            <div className="max-h-[70vh] overflow-y-auto p-4">
              {error && <div className="text-sm text-red-400">{error}</div>}

              {report && (
                <div className="space-y-4">
                  {(() => {
                    const probe = externalProbeFrom(report);
                    const transport = probe?.transport;
                    const egress = probe?.egress;
                    return (
                      <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs">
                        <div className="mb-2 flex items-center justify-between gap-3">
                          <div className="font-semibold text-slate-800">外部网络检查</div>
                          <div className={probe && !probe.error ? "text-emerald-700" : "text-amber-700"}>
                            {probe && !probe.error ? "已收到探针结果" : "未完成外部检查"}
                          </div>
                        </div>
                        {probe?.error ? (
                          <div className="leading-5 text-amber-700">{probe.error}。本次只显示本地代理策略。</div>
                        ) : probe ? (
                          <div className="grid gap-2 sm:grid-cols-2">
                            <div><span className="text-slate-500">出口 IP</span><br /><span className="font-mono text-slate-800">{egress?.ip ?? "未知"}</span></div>
                            <div><span className="text-slate-500">地区 / 时区</span><br /><span className="text-slate-800">{[egress?.country, egress?.city, egress?.timezone].filter(Boolean).join(" · ") || "未知"}</span></div>
                            <div><span className="text-slate-500">HTTP</span><br /><span className="text-slate-800">{transport?.http_protocol ?? "未知"}</span></div>
                            <div><span className="text-slate-500">TLS</span><br /><span className="break-all font-mono text-slate-800">{[transport?.tls_version, transport?.tls_cipher].filter(Boolean).join(" · ") || "未知"}</span></div>
                          </div>
                        ) : (
                          <div className="leading-5 text-amber-700">没有收到外部探针结果，TLS 和出口 IP 不能算作已验证。</div>
                        )}
                        <div className="mt-2 border-t border-slate-200 pt-2 leading-5 text-slate-500">
                          DNS：{report.network.dns_externally_verified ? "已由外部解析器验证" : "仅启用代理解析策略，未经外部 DNS 解析器验证"}。System 时区始终是本机系统值。
                        </div>
                      </div>
                    );
                  })()}

                  <div className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-3">
                    <div className="rounded-md bg-surface-2 p-3">
                      <div className="text-slate-500 mb-1">当前引擎</div>
                      <div className="text-slate-800">{report.expected.browser_engine ?? "未知"}</div>
                    </div>
                    <div className="rounded-md bg-surface-2 p-3">
                      <div className="text-slate-500 mb-1">预期语言</div>
                      <div className="text-slate-800">{report.expected.locale ?? "未设置"}</div>
                    </div>
                    <div className="rounded-md bg-surface-2 p-3">
                      <div className="text-slate-500 mb-1">预期时区</div>
                      <div className="text-slate-800">{report.expected.timezone ?? "未设置"}</div>
                    </div>
                  </div>

                  <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
                    启动方式：{report.expected.launch_mode === "manual" ? "日常无外部 CDP" : "调试模式"}
                    {" · "}采集方式：{report.collection === "passive" ? "浏览器起始页自动采集" : "Manager 主动检查"}
                    {" · "}外部 CDP：{report.expected.external_cdp ? "已开启" : "未开启"}
                  </div>

                  <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
                    这里的“预期语言 / 时区”是浏览器层值，System 时区仍然是本机系统时区，不会被 Manager 修改。
                  </div>

                  {report.proxy_geo && (
                    <div className="rounded-md bg-surface-2 p-3 text-xs">
                      <div className="text-slate-500 mb-1">代理地区</div>
                      <div className="text-slate-800">
                        {report.proxy_geo.ip} · {report.proxy_geo.country} / {report.proxy_geo.region} / {report.proxy_geo.city}
                      </div>
                      <div className="text-slate-500 mt-1">{report.proxy_geo.source}</div>
                    </div>
                  )}

                  {report.analysis.issues.length === 0 ? (
                    <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-300">
                      本地自检未发现 main、iframe、Worker 的语言/时区/基础画像不一致。
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {report.analysis.issues.map((issue, index) => (
                        <div
                          key={`${issue.scope}-${issue.signal}-${index}`}
                          className={`rounded-md border p-3 text-xs ${
                            issue.severity === "error"
                              ? "border-red-500/30 bg-red-500/10"
                              : "border-yellow-500/30 bg-yellow-500/10"
                          }`}
                        >
                          <div className="font-medium text-slate-800">{issueLabel(issue)}</div>
                          <div className="mt-1 text-slate-600">{issue.message}</div>
                          <div className="mt-2 grid grid-cols-2 gap-2">
                            <div>
                              <div className="text-slate-500">期望</div>
                              <div className="break-all text-slate-700">{valueText(issue.expected)}</div>
                            </div>
                            <div>
                              <div className="text-slate-500">实际</div>
                              <div className="break-all text-slate-700">{valueText(issue.actual)}</div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
