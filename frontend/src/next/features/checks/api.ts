import { useQuery } from "@tanstack/react-query";
import { request } from "../../shared/api/client";

// The site-check endpoints return plain dicts; shapes match backend/site_checks.py.

export type CheckStatus = "pass" | "warn" | "fail" | "unknown" | "error";
export type Overall = "pass" | "warn" | "fail";

export interface CheckSite {
  id: string;
  name: string;
  url: string;
  criteria: string;
}

export interface CheckResult {
  site: string;
  name: string;
  criteria: string;
  status: CheckStatus;
  summary: string;
  details: string[];
  screenshot: string | null;
  /** "site" for public detection sites, "local" for the Manager's own probe items. */
  source?: "site" | "local";
  /** Caveat for verdicts that depend on the exit IP's reputation. */
  ip_note?: string | null;
}

export interface CheckCounts {
  pass: number;
  warn: number;
  fail: number;
  unknown: number;
  error: number;
  total: number;
}

export interface ReportSummary {
  id: string;
  created_at: string | null;
  overall: Overall | null;
  profile_id?: string | null;
  profile_name: string | null;
  host_os: string | null;
  passed: number;
  total: number;
}

export interface ReportChange {
  site: string;
  name?: string | null;
  from: CheckStatus | null;
  to: CheckStatus | null;
  summary?: string | null;
}

export interface Report {
  id: string;
  created_at: string;
  overall: Overall;
  environment: Record<string, unknown>;
  results: CheckResult[];
  summary?: CheckCounts;
  egress_note?: string;
  diff?: { previous_created_at?: string | null; changes: ReportChange[] } | null;
}

export interface CheckState {
  phase: "idle" | "launching" | "checking" | "closing" | "done" | "failed";
  profile_id?: string;
  profile_name?: string;
  site?: string | null;
  index?: number;
  total?: number;
  results?: CheckResult[];
  report_id?: string;
  error?: string;
}

export interface EvolutionStatus {
  busy: boolean;
  profile_id?: string | null;
  profile_name?: string | null;
  pending_proposals: number;
}

type Flow = { from: CheckStatus | null; to: CheckStatus | null };

export interface Proposal {
  id: string;
  profile_id: string;
  profile_name?: string | null;
  knob: string;
  label?: string | null;
  from_value?: unknown;
  to_value?: unknown;
  evidence: { rationale?: string; targets?: Record<string, Flow> };
  status: "pending" | "applied" | "dismissed" | string;
  created_at: string;
  decided_at?: string | null;
}

export interface EvolutionLog {
  id: string;
  profile_id?: string | null;
  profile_name?: string | null;
  started_at: string;
  trigger?: string | null;
  outcome?: string | null;
  summary?: string | null;
  detail: {
    experiments?: {
      knob: string;
      label: string;
      from_value: unknown;
      to_value: unknown;
      verdict: string;
      targets_detail?: Record<string, Flow>;
      regressions?: { site: string; name?: string }[];
      note?: string | null;
    }[];
    unfixable?: { site: string; name: string; reason: string }[];
  };
}

export interface Linkability {
  profile_count: number;
  unclustered_count: number;
  clusters: {
    id: string;
    risk: string;
    profiles: { id: string; name: string }[];
    links: { a_id: string; b_id: string; a_name: string; b_name: string; score: number; level: string; reasons: string[]; suggestions: string[] }[];
  }[];
}

const enc = encodeURIComponent;
export const ACTIVE_PHASES = new Set(["launching", "checking", "closing"]);

export const checkKeys = {
  sites: ["site-checks", "sites"] as const,
  state: ["site-checks", "current"] as const,
  reports: ["site-checks", "list"] as const,
  report: (id: string) => ["site-checks", "report", id] as const,
  evolution: ["evolution", "status"] as const,
  proposals: ["evolution", "proposals"] as const,
  logs: ["evolution", "logs"] as const,
  linkability: ["linkability"] as const,
};

export const checksApi = {
  sites: () => request<CheckSite[]>("/api/site-checks/sites"),
  state: () => request<CheckState>("/api/site-checks/current"),
  reports: () => request<ReportSummary[]>("/api/site-checks"),
  report: (id: string) => request<Report>(`/api/site-checks/${enc(id)}`),
  start: (profileId: string) => request<CheckState>(`/api/profiles/${enc(profileId)}/site-check`, { method: "POST" }),
  remove: (id: string) => request<{ ok: boolean }>(`/api/site-checks/${enc(id)}`, { method: "DELETE" }),
  downloadUrl: (id: string) => `/api/site-checks/${enc(id)}/download`,
  fileUrl: (id: string, name: string) => `/api/site-checks/${enc(id)}/files/${enc(name)}`,
  evolution: () => request<EvolutionStatus>("/api/evolution/status"),
  proposals: () => request<Proposal[]>("/api/evolution/proposals"),
  logs: () => request<EvolutionLog[]>("/api/evolution/logs?limit=30"),
  decide: (id: string, approve: boolean) => request<Proposal>(`/api/evolution/proposals/${enc(id)}/${approve ? "approve" : "dismiss"}`, { method: "POST" }),
  evolve: (profileId: string) => request<{ ok: boolean; started: boolean }>(`/api/profiles/${enc(profileId)}/evolution/run`, { method: "POST" }),
  linkability: () => request<Linkability>("/api/linkability", { timeoutMs: 60_000 }),
};

export function useCheckState() {
  return useQuery({
    queryKey: checkKeys.state,
    queryFn: checksApi.state,
    // Follow a running check every 2 s; otherwise look again every 15 s
    // (a scheduled evolution cycle can start one too).
    refetchInterval: (query) => (query.state.data && ACTIVE_PHASES.has(query.state.data.phase) ? 2_000 : 15_000),
  });
}

export function useEvolutionStatus() {
  return useQuery({ queryKey: checkKeys.evolution, queryFn: checksApi.evolution, refetchInterval: (query) => (query.state.data?.busy ? 3_000 : 15_000) });
}

export const STATUS_LABEL: Record<CheckStatus, string> = { pass: "通过", warn: "警告", fail: "未通过", unknown: "未读到结论", error: "出错" };
export const STATUS_TONE: Record<CheckStatus, "success" | "warning" | "danger" | "neutral"> = { pass: "success", warn: "warning", fail: "danger", unknown: "neutral", error: "danger" };
export const OVERALL_LABEL: Record<Overall, string> = { pass: "全部通过", warn: "有警告", fail: "未通过" };

export function formatTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
