import { Activity, AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useState } from "react";
import { api, type FingerprintIssue, type FingerprintReport } from "../lib/api";

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
                      分数 {report.analysis.score} · 错误 {report.analysis.error_count} · 警告 {report.analysis.warning_count}
                    </div>
                  )}
                </div>
              </div>
              <button
                onClick={() => {
                  setReport(null);
                  setError(null);
                }}
                className="text-gray-500 hover:text-gray-300"
              >
                关闭
              </button>
            </div>

            <div className="max-h-[70vh] overflow-y-auto p-4">
              {error && <div className="text-sm text-red-400">{error}</div>}

              {report && (
                <div className="space-y-4">
                  <div className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-3">
                    <div className="rounded-md bg-surface-2 p-3">
                      <div className="text-gray-500 mb-1">当前引擎</div>
                      <div className="text-gray-200">{report.expected.browser_engine ?? "未知"}</div>
                    </div>
                    <div className="rounded-md bg-surface-2 p-3">
                      <div className="text-gray-500 mb-1">预期语言</div>
                      <div className="text-gray-200">{report.expected.locale ?? "未设置"}</div>
                    </div>
                    <div className="rounded-md bg-surface-2 p-3">
                      <div className="text-gray-500 mb-1">预期时区</div>
                      <div className="text-gray-200">{report.expected.timezone ?? "未设置"}</div>
                    </div>
                  </div>

                  {report.proxy_geo && (
                    <div className="rounded-md bg-surface-2 p-3 text-xs">
                      <div className="text-gray-500 mb-1">代理地区</div>
                      <div className="text-gray-200">
                        {report.proxy_geo.ip} · {report.proxy_geo.country} / {report.proxy_geo.region} / {report.proxy_geo.city}
                      </div>
                      <div className="text-gray-500 mt-1">{report.proxy_geo.source}</div>
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
                          <div className="font-medium text-gray-200">{issueLabel(issue)}</div>
                          <div className="mt-1 text-gray-400">{issue.message}</div>
                          <div className="mt-2 grid grid-cols-2 gap-2">
                            <div>
                              <div className="text-gray-500">期望</div>
                              <div className="break-all text-gray-300">{valueText(issue.expected)}</div>
                            </div>
                            <div>
                              <div className="text-gray-500">实际</div>
                              <div className="break-all text-gray-300">{valueText(issue.actual)}</div>
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
