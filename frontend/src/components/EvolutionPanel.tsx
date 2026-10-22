import { Check, ChevronDown, ChevronRight, Dna, Loader2, Play, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  type EvolutionLogEntry,
  type EvolutionProposal,
  type EvolutionStatus,
  type Profile,
  type SiteCheckStatus,
} from "../lib/api";

interface EvolutionPanelProps {
  profiles: Profile[];
  onRefresh: () => Promise<void> | void;
}

const POLL_MS = 3000;

const STATUS_LABELS: Record<SiteCheckStatus, string> = {
  pass: "通过",
  warn: "警告",
  fail: "未通过",
  unknown: "未读到结论",
  error: "出错",
};

const OUTCOME_LABELS: Record<string, string> = {
  running: "进行中",
  clean: "全部通过",
  unfixable_only: "无可自动修复项",
  experiments: "实验完成",
  check_failed: "检测失败",
  deferred: "已推迟",
  error: "出错",
};

const OUTCOME_STYLES: Record<string, string> = {
  running: "bg-blue-50 text-blue-700",
  clean: "bg-emerald-50 text-emerald-700",
  unfixable_only: "bg-slate-100 text-slate-600",
  experiments: "bg-violet-50 text-violet-700",
  check_failed: "bg-red-50 text-red-700",
  deferred: "bg-amber-50 text-amber-700",
  error: "bg-red-50 text-red-700",
};

const VERDICT_LABELS: Record<string, string> = {
  improved: "有效",
  no_change: "无变化",
  regressed: "变差",
  error: "出错",
  deferred: "推迟",
};

const VERDICT_STYLES: Record<string, string> = {
  improved: "bg-emerald-50 text-emerald-700",
  no_change: "bg-slate-100 text-slate-600",
  regressed: "bg-red-50 text-red-700",
  error: "bg-red-50 text-red-700",
  deferred: "bg-amber-50 text-amber-700",
};

const INTERVAL_OPTIONS = [
  { hours: 12, label: "每 12 小时" },
  { hours: 24, label: "每天" },
  { hours: 72, label: "每 3 天" },
  { hours: 168, label: "每周" },
];

function formatTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "自动（内核决定）";
  if (typeof value === "boolean") return value ? "开启" : "关闭";
  return String(value);
}

function StatusFlow({ from, to }: { from: SiteCheckStatus | null; to: SiteCheckStatus | null }) {
  return (
    <span className="text-xs text-slate-600">
      {from ? STATUS_LABELS[from] : "—"} <span aria-hidden="true">→</span> {to ? STATUS_LABELS[to] : "—"}
    </span>
  );
}

export function EvolutionPanel({ profiles, onRefresh }: EvolutionPanelProps) {
  const [status, setStatus] = useState<EvolutionStatus | null>(null);
  const [proposals, setProposals] = useState<EvolutionProposal[]>([]);
  const [logs, setLogs] = useState<EvolutionLogEntry[]>([]);
  const [profileId, setProfileId] = useState<string>("");
  const [intervalHours, setIntervalHours] = useState<number>(24);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<string | null>(null);

  const selected = profiles.find((profile) => profile.id === profileId);
  const busy = Boolean(status?.busy);
  const pending = proposals.filter((proposal) => proposal.status === "pending");
  const decided = proposals.filter((proposal) => proposal.status !== "pending");

  const load = useCallback(async () => {
    try {
      const [nextStatus, nextProposals, nextLogs] = await Promise.all([
        api.getEvolutionStatus(),
        api.listEvolutionProposals(),
        api.listEvolutionLogs(undefined, 30),
      ]);
      setStatus(nextStatus);
      setProposals(nextProposals);
      setLogs(nextLogs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取进化战报失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const first = profiles[0];
    if (!profileId && first) setProfileId(first.id);
  }, [profileId, profiles]);

  useEffect(() => {
    if (selected) setIntervalHours(Number(selected.evolution_interval_hours) || 24);
  }, [selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // While a cycle runs, poll; when it finishes, refresh everything once.
  useEffect(() => {
    if (!busy) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.getEvolutionStatus();
        setStatus(next);
        if (!next.busy) {
          window.clearInterval(timer);
          await load();
          await onRefresh();
        }
      } catch {
        // keep polling; the server may be busy
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [busy, load, onRefresh]);

  const saveSettings = async (enabled: boolean, hours: number) => {
    if (!selected) return;
    setError(null);
    try {
      await api.updateProfile(selected.id, {
        evolution_enabled: enabled,
        evolution_interval_hours: hours,
      });
      await onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存进化设置失败");
    }
  };

  const handleRunNow = async () => {
    if (!selected) return;
    if (!confirm(`对「${selected.name}」立即跑一轮进化？\n先做一键检测，再把候选修复逐个放到一次性克隆上验证；源画像不会被直接修改，有效的修复会生成待批准提案。整个过程可能要十几分钟。`)) return;
    setError(null);
    try {
      await api.runEvolutionNow(selected.id);
      setStatus(await api.getEvolutionStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : "进化没能开始");
    }
  };

  const handleDecide = async (proposal: EvolutionProposal, action: "approve" | "dismiss") => {
    if (action === "approve" && !confirm(`把「${proposal.label ?? proposal.knob}」应用到「${proposal.profile_name ?? ""}」？\n${formatValue(proposal.from_value)} → ${formatValue(proposal.to_value)}（已在克隆上验证有效）`)) return;
    setActing(proposal.id);
    setError(null);
    try {
      if (action === "approve") await api.approveEvolutionProposal(proposal.id);
      else await api.dismissEvolutionProposal(proposal.id);
      await load();
      await onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "处理提案失败");
    } finally {
      setActing(null);
    }
  };

  const running = selected?.status === "running";

  return (
    <div className="max-w-5xl overflow-hidden rounded-md border border-border bg-white">
      <div className="flex items-start gap-3 border-b border-border px-5 py-4">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-violet-50 text-violet-700">
          <Dna className="h-4 w-4" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-slate-900">进化战报（自对抗闭环）</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            检测发现的问题先归因到配置层成因，再逐个放到一次性克隆上实测验证 — 克隆用完即焚毁。
            只有实测有效的修复才会变成提案，<span className="font-medium text-slate-700">你批准后才改到源画像上</span>；
            出口 IP 信誉、内核层信号这类配置层改不了的问题会如实标注，不生成假修复。
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-3">
        <select
          className="input w-64"
          aria-label="进化的画像"
          value={profileId}
          onChange={(e) => setProfileId(e.target.value)}
        >
          {profiles.map((profile) => (
            <option key={profile.id} value={profile.id}>{profile.name}</option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-xs text-slate-700">
          <input
            type="checkbox"
            aria-label="自动进化"
            checked={Boolean(selected?.evolution_enabled)}
            disabled={!selected}
            onChange={(e) => void saveSettings(e.target.checked, intervalHours)}
          />
          自动进化
        </label>
        <select
          className="input w-32"
          aria-label="进化间隔"
          value={intervalHours}
          disabled={!selected}
          onChange={(e) => {
            const hours = Number(e.target.value);
            setIntervalHours(hours);
            void saveSettings(Boolean(selected?.evolution_enabled), hours);
          }}
        >
          {INTERVAL_OPTIONS.map((option) => (
            <option key={option.hours} value={option.hours}>{option.label}</option>
          ))}
        </select>
        <button
          className="btn-primary flex items-center gap-1.5 px-4 disabled:opacity-60"
          disabled={busy || !selected || running}
          title={running ? "请先关闭这个浏览器" : undefined}
          onClick={() => void handleRunNow()}
        >
          <Play className="h-4 w-4" />
          <span>立即进化一次</span>
        </button>
        <button className="btn-secondary flex items-center gap-1.5 px-3" onClick={() => void load()}>
          <RefreshCw className="h-4 w-4" />
          <span>刷新</span>
        </button>
        {running && <span className="text-xs text-amber-700">这个浏览器正在运行，进化会推迟。</span>}
      </div>

      {error && (
        <div className="border-b border-red-200 bg-red-50 px-5 py-3 text-sm text-red-800">{error}</div>
      )}

      {busy && (
        <div className="flex items-center gap-2 border-b border-blue-200 bg-blue-50 px-5 py-3 text-sm text-blue-900" role="status">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>正在进化「{status?.profile_name ?? ""}」：检测源画像并在克隆上逐项验证候选修复…</span>
        </div>
      )}

      <div className="border-b border-border px-5 py-3">
        <h3 className="text-xs font-semibold text-slate-900">
          待批准提案{pending.length > 0 ? `（${pending.length}）` : ""}
        </h3>
        {pending.length === 0 ? (
          <p className="mt-1.5 text-xs text-slate-500">暂无待批准提案 — 克隆实验验证有效的修复会出现在这里。</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {pending.map((proposal) => (
              <li key={proposal.id} className="rounded-md border border-violet-200 bg-violet-50/50 px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-slate-900">{proposal.label ?? proposal.knob}</span>
                  <span className="text-xs text-slate-500">
                    {proposal.profile_name ?? proposal.profile_id}：{formatValue(proposal.from_value)} → {formatValue(proposal.to_value)}
                  </span>
                  <span className="ml-auto flex gap-1.5">
                    <button
                      className="btn-primary flex items-center gap-1 px-3 text-xs disabled:opacity-60"
                      disabled={acting === proposal.id}
                      onClick={() => void handleDecide(proposal, "approve")}
                    >
                      <Check className="h-3.5 w-3.5" />
                      <span>批准应用</span>
                    </button>
                    <button
                      className="btn-secondary flex items-center gap-1 px-3 text-xs disabled:opacity-60"
                      disabled={acting === proposal.id}
                      onClick={() => void handleDecide(proposal, "dismiss")}
                    >
                      <X className="h-3.5 w-3.5" />
                      <span>忽略</span>
                    </button>
                  </span>
                </div>
                {proposal.evidence?.targets && (
                  <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
                    {Object.entries(proposal.evidence.targets).map(([site, change]) => (
                      <span key={site} className="text-xs text-slate-600">
                        {site}：<StatusFlow from={change.from} to={change.to} />
                      </span>
                    ))}
                  </div>
                )}
                {proposal.evidence?.rationale && (
                  <p className="mt-1 text-xs leading-5 text-slate-500">{proposal.evidence.rationale}</p>
                )}
              </li>
            ))}
          </ul>
        )}
        {decided.length > 0 && (
          <ul className="mt-2 space-y-1">
            {decided.slice(0, 5).map((proposal) => (
              <li key={proposal.id} className="text-xs text-slate-400">
                {proposal.profile_name ?? proposal.profile_id} · {proposal.label ?? proposal.knob}：
                {formatValue(proposal.from_value)} → {formatValue(proposal.to_value)} ·{" "}
                {proposal.status === "applied" ? "已应用" : "已忽略"}（{formatTime(proposal.decided_at)}）
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="px-5 py-3">
        <h3 className="text-xs font-semibold text-slate-900">战报时间线</h3>
        {logs.length === 0 ? (
          <p className="mt-1.5 text-xs text-slate-500">还没有进化记录。开启自动进化，或点「立即进化一次」。</p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {logs.map((entry) => {
              const experiments = entry.detail?.experiments ?? [];
              const unfixable = entry.detail?.unfixable ?? [];
              const isOpen = expanded === entry.id;
              const hasDetail = experiments.length > 0 || unfixable.length > 0;
              return (
                <li key={entry.id} className="rounded-md border border-border">
                  <button
                    className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left"
                    onClick={() => setExpanded(isOpen ? null : entry.id)}
                    aria-expanded={isOpen}
                  >
                    {isOpen ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${OUTCOME_STYLES[entry.outcome ?? ""] ?? "bg-slate-100 text-slate-600"}`}>
                      {OUTCOME_LABELS[entry.outcome ?? ""] ?? entry.outcome ?? "-"}
                    </span>
                    <span className="text-sm font-medium text-slate-800">{entry.profile_name ?? "-"}</span>
                    <span className="text-xs text-slate-400">
                      {entry.trigger === "scheduled" ? "定时" : "手动"} · {formatTime(entry.started_at)}
                    </span>
                    <span className="w-full text-xs leading-5 text-slate-600 sm:w-auto sm:flex-1">{entry.summary}</span>
                  </button>
                  {isOpen && hasDetail && (
                    <div className="border-t border-border px-3 py-2">
                      {experiments.map((experiment, index) => (
                        <div key={`${experiment.knob}-${index}`} className="flex flex-wrap items-center gap-2 py-1 text-xs">
                          <span className={`rounded px-2 py-0.5 font-medium ${VERDICT_STYLES[experiment.verdict] ?? ""}`}>
                            {VERDICT_LABELS[experiment.verdict] ?? experiment.verdict}
                          </span>
                          <span className="font-medium text-slate-800">{experiment.label}</span>
                          <span className="text-slate-500">{formatValue(experiment.from_value)} → {formatValue(experiment.to_value)}</span>
                          {Object.entries(experiment.targets_detail ?? {}).map(([site, change]) => (
                            <span key={site} className="text-slate-600">
                              {site}：<StatusFlow from={change.from} to={change.to} />
                            </span>
                          ))}
                          {(experiment.regressions ?? []).length > 0 && (
                            <span className="text-red-600">
                              连带变差：{experiment.regressions.map((r) => r.name ?? r.site).join("、")}
                            </span>
                          )}
                          {experiment.note && <span className="text-slate-400">{experiment.note}</span>}
                        </div>
                      ))}
                      {unfixable.map((item) => (
                        <div key={item.site} className="py-1 text-xs text-slate-500">
                          <span className="font-medium text-slate-700">{item.name}</span>
                          <span className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-[11px]">不可自动修复</span>
                          <span className="ml-1">{item.reason}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
