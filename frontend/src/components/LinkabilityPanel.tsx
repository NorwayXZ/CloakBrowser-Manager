import { AlertTriangle, CheckCircle2, Loader2, Network, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type LinkabilityResult } from "../lib/api";

const RISK_STYLES: Record<string, string> = {
  high: "bg-red-50 text-red-700",
  medium: "bg-amber-50 text-amber-700",
};

const RISK_LABELS: Record<string, string> = {
  high: "高风险",
  medium: "中风险",
};

const LEVEL_LABELS: Record<string, string> = {
  strong: "强关联",
  medium: "中等关联",
};

export function LinkabilityPanel() {
  const [data, setData] = useState<LinkabilityResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.getLinkability());
    } catch (err) {
      setError(err instanceof Error ? err.message : "关联分析加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
      <div className="max-w-5xl overflow-hidden rounded-md border border-border bg-white">
        <div className="flex items-start gap-3 border-b border-border px-5 py-4">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-700">
            <Network className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-semibold text-slate-900">关联分析</div>
            <div className="mt-0.5 text-xs leading-5 text-slate-500">
              只用已保存的画像数据分析：共用代理出口、相同指纹种子、相同设备模板、相同硬件组合等信号叠加得越多，
              这些画像越容易被检测方关联成同一个人。本分析不会启动浏览器，也不会改动任何画像。
            </div>
          </div>
          <button
            className="btn-secondary flex shrink-0 items-center gap-1.5 px-3 disabled:opacity-60"
            disabled={loading}
            onClick={() => void load()}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span>重新分析</span>
          </button>
        </div>

        <div className="px-5 py-4">
          {error && (
            <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {!error && loading && !data && (
            <div className="flex items-center gap-2 py-6 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>正在分析...</span>
            </div>
          )}

          {!error && data && data.clusters.length === 0 && (
            <div className="flex items-start gap-3 py-2">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-emerald-50 text-emerald-600">
                <CheckCircle2 className="h-4 w-4" />
              </div>
              <div>
                <div className="font-medium text-slate-900">没有发现可关联的画像组合</div>
                <div className="mt-0.5 text-xs leading-5 text-slate-500">
                  当前 {data.profile_count} 个画像之间没有共用出口、相同设备模板或相同硬件组合等强关联信号。
                  时区与语言相同很常见，单独出现不会计入关联。
                </div>
              </div>
            </div>
          )}

          {!error && data && data.clusters.length > 0 && (
            <div className="mb-3 text-xs text-slate-500">
              共 {data.profile_count} 个画像，其中 {data.profile_count - data.unclustered_count} 个落在{" "}
              {data.clusters.length} 组关联里，其余 {data.unclustered_count} 个未发现关联。
            </div>
          )}
        </div>

        {!error && data && data.clusters.map((cluster) => (
          <div key={cluster.id} className="border-t border-border px-5 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded px-2 py-0.5 text-xs font-medium ${RISK_STYLES[cluster.risk] ?? RISK_STYLES.medium}`}>
                {RISK_LABELS[cluster.risk] ?? cluster.risk}
              </span>
              <span className="text-sm font-medium text-slate-900">
                {cluster.profiles.length} 个画像可能被关联成同一个人
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {cluster.profiles.map((profile) => (
                <span key={profile.id} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
                  {profile.name}
                </span>
              ))}
            </div>
            <div className="mt-3 space-y-3">
              {cluster.links.map((link) => (
                <div key={`${link.a_id}-${link.b_id}`} className="rounded-md border border-border bg-slate-50 px-3 py-2.5">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium text-slate-900">{link.a_name}</span>
                    <span className="text-slate-400">↔</span>
                    <span className="font-medium text-slate-900">{link.b_name}</span>
                    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
                      link.level === "strong" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"
                    }`}>
                      {LEVEL_LABELS[link.level] ?? link.level} · {link.score} 分
                    </span>
                  </div>
                  <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-xs leading-5 text-slate-600">
                    {link.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                  {link.suggestions.length > 0 && (
                    <div className="mt-1.5 text-xs leading-5 text-slate-500">
                      {link.suggestions.map((suggestion) => (
                        <div key={suggestion}>建议：{suggestion}</div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
