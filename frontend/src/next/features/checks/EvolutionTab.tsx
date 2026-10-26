import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, ChevronRight, Dna, Play, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "../../shared/lib/cn";
import { Badge, Banner, Button, EmptyState, ErrorState, FormField, Section, Select, Skeleton, Switch, useConfirm, useToast, type Tone } from "../../ui";
import { AutomationHoursHint } from "../app/AutomationHoursHint";
import { profileKeys, profilesApi, useProfiles } from "../profiles/api";
import { isRunning } from "../profiles/format";
import { checkKeys, checksApi, formatTime, STATUS_LABEL, useEvolutionStatus, type CheckStatus, type EvolutionLog, type Proposal } from "./api";

const OUTCOME: Record<string, { label: string; tone: Tone }> = {
  running: { label: "进行中", tone: "accent" },
  clean: { label: "全部通过", tone: "success" },
  unfixable_only: { label: "无可自动修复项", tone: "neutral" },
  experiments: { label: "实验完成", tone: "info" },
  check_failed: { label: "检测失败", tone: "danger" },
  deferred: { label: "已推迟", tone: "warning" },
  error: { label: "出错", tone: "danger" },
};

const VERDICT: Record<string, { label: string; tone: Tone }> = {
  improved: { label: "有效", tone: "success" },
  no_change: { label: "无变化", tone: "neutral" },
  regressed: { label: "变差", tone: "danger" },
  error: { label: "出错", tone: "danger" },
  deferred: { label: "推迟", tone: "warning" },
};

const INTERVALS = [
  { hours: 12, label: "每 12 小时" },
  { hours: 24, label: "每天" },
  { hours: 72, label: "每 3 天" },
  { hours: 168, label: "每周" },
];

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "自动（内核决定）";
  if (typeof value === "boolean") return value ? "开启" : "关闭";
  return String(value);
}

function Flow({ from, to }: { from: CheckStatus | null; to: CheckStatus | null }) {
  return (
    <span className="text-fg-2">
      {from ? STATUS_LABEL[from] : "—"} <span aria-hidden>→</span> {to ? STATUS_LABEL[to] : "—"}
    </span>
  );
}

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Self-adversarial loop: a check's failures are traced to configuration
 * knobs, each fix is tried on a throwaway clone, and only fixes that work
 * become proposals; nothing touches the real profile until approved.
 */
export function EvolutionTab() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const profiles = useProfiles();
  const status = useEvolutionStatus();
  const proposals = useQuery({ queryKey: checkKeys.proposals, queryFn: checksApi.proposals });
  const logs = useQuery({ queryKey: checkKeys.logs, queryFn: checksApi.logs });
  const [profileId, setProfileId] = useState("");
  const [saving, setSaving] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const list = profiles.data ?? [];
  const selected = list.find((p) => p.id === profileId) ?? list[0];
  const busy = Boolean(status.data?.busy);
  const running = selected ? isRunning(selected) : false;
  const pending = (proposals.data ?? []).filter((p) => p.status === "pending");
  const decided = (proposals.data ?? []).filter((p) => p.status !== "pending");

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: checkKeys.proposals }),
      queryClient.invalidateQueries({ queryKey: checkKeys.logs }),
      queryClient.invalidateQueries({ queryKey: checkKeys.evolution }),
      queryClient.invalidateQueries({ queryKey: profileKeys.list }),
    ]);

  // A cycle just finished: refresh proposals and the timeline once.
  const wasBusy = useRef(false);
  useEffect(() => {
    if (busy) wasBusy.current = true;
    else if (wasBusy.current) {
      wasBusy.current = false;
      void refresh();
    }
  });

  const save = async (enabled: boolean, hours: number) => {
    if (!selected) return;
    setSaving(true);
    try {
      const saved = await profilesApi.update(selected.id, { evolution_enabled: enabled, evolution_interval_hours: hours });
      queryClient.setQueryData(profileKeys.list, (current: typeof list | undefined) => current?.map((p) => (p.id === saved.id ? saved : p)));
    } catch (error) {
      toast.show({ tone: "error", title: "进化设置没有保存", description: message(error) });
    } finally {
      setSaving(false);
    }
  };

  const runNow = async () => {
    if (!selected) return;
    const ok = await confirm({
      title: `对「${selected.name}」立即跑一轮进化？`,
      description: "先做一键检测，再把候选修复逐个放到一次性克隆上验证；源环境不会被直接修改，有效的修复会生成待批准提案。整个过程可能要十几分钟。",
      confirmLabel: "开始",
    });
    if (!ok) return;
    setStarting(true);
    try {
      await checksApi.evolve(selected.id);
      await queryClient.invalidateQueries({ queryKey: checkKeys.evolution });
    } catch (error) {
      toast.show({ tone: "error", title: "进化没能开始", description: message(error) });
    } finally {
      setStarting(false);
    }
  };

  const decide = async (proposal: Proposal, approve: boolean) => {
    if (approve) {
      const ok = await confirm({
        title: `把「${proposal.label ?? proposal.knob}」应用到「${proposal.profile_name ?? ""}」？`,
        description: `${formatValue(proposal.from_value)} → ${formatValue(proposal.to_value)}（已在克隆上验证有效）`,
        confirmLabel: "批准应用",
      });
      if (!ok) return;
    }
    setActing(proposal.id);
    try {
      await checksApi.decide(proposal.id, approve);
      toast.show({ tone: "success", title: approve ? "已应用到环境" : "已忽略这条提案" });
    } catch (error) {
      toast.show({ tone: "error", title: "提案没有处理", description: message(error) });
    } finally {
      setActing(null);
      await refresh();
    }
  };

  const interval = Number(selected?.evolution_interval_hours) || 24;

  return (
    <div className="flex flex-col gap-5">
      <Section
        id="evolution"
        title="进化（自对抗闭环）"
        description="检测发现的问题先归因到配置层成因，再逐个放到一次性克隆上实测验证，克隆用完即焚毁。只有实测有效的修复才会变成提案，你批准后才改到源环境上；出口 IP 信誉、内核层信号这类配置改不了的问题会如实标注，不生成假修复。"
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <FormField label="进化的环境" className="w-64 max-w-full">
              <Select value={selected?.id ?? ""} disabled={list.length === 0} onChange={(event) => setProfileId(event.target.value)}>
                {list.length === 0 && <option value="">还没有环境</option>}
                {list.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.name}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label="进化间隔" className="w-36">
              <Select value={interval} disabled={!selected || saving} onChange={(event) => void save(Boolean(selected?.evolution_enabled), Number(event.target.value))}>
                {INTERVALS.map((option) => (
                  <option key={option.hours} value={option.hours}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </FormField>
            <Button variant="primary" icon={<Play className="h-4 w-4" />} loading={starting} disabled={busy || !selected || running} title={running ? "请先关闭这个环境的浏览器" : undefined} onClick={() => void runNow()}>
              立即进化一次
            </Button>
          </div>
          <div className="max-w-md">
            <Switch
              checked={Boolean(selected?.evolution_enabled)}
              disabled={!selected || saving}
              onCheckedChange={(enabled) => void save(enabled, interval)}
              label="自动进化"
              description="按上面的间隔定时运行；浏览器正在使用时自动推迟。"
            />
          </div>
          {running && <p className="text-xs text-warning">这个环境的浏览器正在运行，进化会推迟。</p>}
          <AutomationHoursHint />
          {busy && (
            <Banner tone="info" title={`正在进化「${status.data?.profile_name ?? ""}」`}>
              检测源环境并在克隆上逐项验证候选修复…
            </Banner>
          )}
        </div>
      </Section>

      <Section id="proposals" title={`待批准提案${pending.length ? `（${pending.length}）` : ""}`}>
        {proposals.isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : proposals.isError ? (
          <ErrorState message={proposals.error.message} onRetry={() => void proposals.refetch()} />
        ) : pending.length === 0 ? (
          <p className="text-sm text-fg-2">暂无待批准提案：克隆实验验证有效的修复会出现在这里。</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {pending.map((proposal) => (
              <li key={proposal.id} className="rounded-md border border-accent/30 bg-accent-soft p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-fg">{proposal.label ?? proposal.knob}</span>
                  <span className="text-xs text-fg-2">
                    {proposal.profile_name ?? proposal.profile_id}：{formatValue(proposal.from_value)} → {formatValue(proposal.to_value)}
                  </span>
                  <span className="ml-auto flex gap-1.5">
                    <Button size="sm" variant="primary" icon={<Check className="h-3.5 w-3.5" />} disabled={acting === proposal.id} onClick={() => void decide(proposal, true)}>
                      批准应用
                    </Button>
                    <Button size="sm" icon={<X className="h-3.5 w-3.5" />} disabled={acting === proposal.id} onClick={() => void decide(proposal, false)}>
                      忽略
                    </Button>
                  </span>
                </div>
                {proposal.evidence?.targets && (
                  <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                    {Object.entries(proposal.evidence.targets).map(([site, change]) => (
                      <span key={site}>
                        {site}：<Flow from={change.from} to={change.to} />
                      </span>
                    ))}
                  </div>
                )}
                {proposal.evidence?.rationale && <p className="mt-1 text-xs text-fg-2">{proposal.evidence.rationale}</p>}
              </li>
            ))}
          </ul>
        )}
        {decided.length > 0 && (
          <ul className="mt-3 flex flex-col gap-1 border-t border-border pt-2 text-xs text-fg-3">
            {decided.slice(0, 5).map((proposal) => (
              <li key={proposal.id}>
                {proposal.profile_name ?? proposal.profile_id} · {proposal.label ?? proposal.knob}：{formatValue(proposal.from_value)} → {formatValue(proposal.to_value)} ·{" "}
                {proposal.status === "applied" ? "已应用" : "已忽略"}（{formatTime(proposal.decided_at)}）
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="timeline" title="进化时间线">
        {logs.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : logs.isError ? (
          <ErrorState message={logs.error.message} onRetry={() => void logs.refetch()} />
        ) : logs.data.length === 0 ? (
          <EmptyState icon={Dna} title="还没有进化记录" description="开启自动进化，或点“立即进化一次”。" />
        ) : (
          <ul className="flex flex-col gap-1.5">
            {logs.data.map((entry) => (
              <LogEntry key={entry.id} entry={entry} open={expanded === entry.id} onToggle={() => setExpanded(expanded === entry.id ? null : entry.id)} />
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function LogEntry({ entry, open, onToggle }: { entry: EvolutionLog; open: boolean; onToggle: () => void }) {
  const experiments = entry.detail?.experiments ?? [];
  const unfixable = entry.detail?.unfixable ?? [];
  const hasDetail = experiments.length > 0 || unfixable.length > 0;
  const outcome = OUTCOME[entry.outcome ?? ""] ?? { label: entry.outcome ?? "-", tone: "neutral" as const };
  return (
    <li className="rounded-md border border-border">
      <button type="button" className={cn("flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left", !hasDetail && "cursor-default")} aria-expanded={hasDetail ? open : undefined} onClick={hasDetail ? onToggle : undefined}>
        {hasDetail ? open ? <ChevronDown className="h-4 w-4 text-fg-3" aria-hidden /> : <ChevronRight className="h-4 w-4 text-fg-3" aria-hidden /> : <span className="w-4" aria-hidden />}
        <Badge tone={outcome.tone}>{outcome.label}</Badge>
        <span className="text-sm font-medium text-fg">{entry.profile_name ?? "-"}</span>
        <span className="text-xs text-fg-3">
          {entry.trigger === "scheduled" ? "定时" : "手动"} · {formatTime(entry.started_at)}
        </span>
        <span className="w-full text-xs text-fg-2 sm:w-auto sm:flex-1">{entry.summary}</span>
      </button>
      {open && hasDetail && (
        <div className="flex flex-col gap-1 border-t border-border px-3 py-2 text-xs">
          {experiments.map((experiment, index) => {
            const verdict = VERDICT[experiment.verdict] ?? { label: experiment.verdict, tone: "neutral" as const };
            return (
              <div key={`${experiment.knob}-${index}`} className="flex flex-wrap items-center gap-2">
                <Badge tone={verdict.tone}>{verdict.label}</Badge>
                <span className="font-medium text-fg">{experiment.label}</span>
                <span className="text-fg-2">
                  {formatValue(experiment.from_value)} → {formatValue(experiment.to_value)}
                </span>
                {Object.entries(experiment.targets_detail ?? {}).map(([site, change]) => (
                  <span key={site}>
                    {site}：<Flow from={change.from} to={change.to} />
                  </span>
                ))}
                {(experiment.regressions ?? []).length > 0 && <span className="text-danger">连带变差：{(experiment.regressions ?? []).map((r) => r.name ?? r.site).join("、")}</span>}
                {experiment.note && <span className="text-fg-3">{experiment.note}</span>}
              </div>
            );
          })}
          {unfixable.map((item) => (
            <div key={item.site} className="flex flex-wrap items-center gap-1.5 text-fg-2">
              <span className="font-medium text-fg">{item.name}</span>
              <Badge>不可自动修复</Badge>
              <span>{item.reason}</span>
            </div>
          ))}
        </div>
      )}
    </li>
  );
}
