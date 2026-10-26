import { useQuery } from "@tanstack/react-query";
import { request } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export { formatBytes } from "../data/api";

type Schemas = components["schemas"];
export type KernelOverview = Schemas["KernelOverviewResponse"];
export type KernelSettings = Schemas["KernelSettingsModel"];
export type KernelLicense = Schemas["KernelLicenseResponse"];
export type KernelCheck = Schemas["KernelCheckResponse"];
export type BrowserUpdate = Schemas["BrowserUpdateResponse"];
export type ManagerUpdate = Schemas["ManagerUpdateResponse"];
export type AutomationHours = Schemas["AutomationHoursResponse"];
// `clear_api_key` defaults to false on the backend; the panel only sends it to wipe the stored key.
export type LlmSettingsUpdate = Omit<Schemas["LlmSettingsModel"], "clear_api_key"> & { clear_api_key?: boolean };

/** /api/settings/llm answers a plain dict: the key itself is never sent back. */
export interface LlmSettings {
  configured: boolean;
  base_url: string | null;
  model: string | null;
  has_api_key: boolean;
  executor_model: string | null;
  executor_effort: string | null;
}

export type McpMode = Schemas["McpSettingsModel"]["mode"];
export type McpAuditEntry = Schemas["McpAuditResponse"];
export type AgentTokenScope = "read" | "control" | "cdp";

// /api/agent/tokens answers plain dicts (no response model), matching backend/main.py.
export interface AgentToken {
  id: string;
  name: string;
  scope: AgentTokenScope;
  /** Unix seconds. */
  created_at: number;
}

export interface AgentTokenList {
  /** False when the Manager has no authentication: tokens are then not checked. */
  enforced: boolean;
  scopes: AgentTokenScope[];
  tokens: AgentToken[];
}

export interface AgentTokenCreated {
  /** Plaintext token, shown exactly once. */
  token: string;
  record: AgentToken;
  enforced: boolean;
  note: string;
}

export type AppUpdatePhase = "idle" | "checking" | "downloading" | "backing_up" | "preparing" | "restarting" | "failed";

export interface AppUpdateResult {
  ok: boolean;
  from: string | null;
  to: string;
  running: string;
  reason: string | null;
  finished_at: string;
}

/** /api/app/update: the one-click updater of the packaged app. */
export interface AppUpdateState {
  phase: AppUpdatePhase;
  label?: string;
  target?: string;
  done?: number;
  total?: number;
  error?: string;
  supported?: boolean;
  current_version?: string | null;
  last_result?: AppUpdateResult | null;
}

export const APP_UPDATE_ACTIVE = new Set<AppUpdatePhase>(["checking", "downloading", "backing_up", "preparing", "restarting"]);

/** What "检查更新" found: the Manager check and the kernel update that runs with it. */
export interface UpdateCheck {
  manager: ManagerUpdate;
  browser: BrowserUpdate | null;
  browserError: string | null;
}

export const settingsKeys = {
  kernel: ["settings", "kernel"] as const,
  llm: ["settings", "llm"] as const,
  mcp: ["settings", "mcp"] as const,
  agentTokens: ["agent", "tokens"] as const,
  mcpAudit: ["mcp", "audit"] as const,
  hours: ["automation", "hours"] as const,
  appUpdate: ["app", "update"] as const,
  /** Last "检查更新" result, kept so the toolbar can mention a new version. */
  updateCheck: ["app", "update-check"] as const,
};

const enc = encodeURIComponent;
// Pulling code, downloading a kernel or asking GitHub can each take a while.
const SLOW = 10 * 60_000;

export const settingsApi = {
  kernel: () => request<KernelOverview>("/api/kernel", { timeoutMs: 60_000 }),
  checkKernel: () => request<KernelCheck>("/api/kernel/check", { method: "POST", timeoutMs: 60_000 }),
  updateKernel: () => request<BrowserUpdate>("/api/kernel/update", { method: "POST", timeoutMs: SLOW }),
  saveKernelSettings: (settings: KernelSettings) => request<KernelOverview>("/api/kernel/settings", { method: "PUT", body: settings }),
  saveLicense: (key: string) => request<KernelOverview>("/api/kernel/license", { method: "POST", body: { license_key: key }, timeoutMs: 60_000 }),
  removeLicense: () => request<KernelOverview>("/api/kernel/license", { method: "DELETE" }),
  deleteKernel: (name: string) => request<{ ok: boolean; freed_bytes: number }>(`/api/kernel/versions/${enc(name)}`, { method: "DELETE", timeoutMs: 60_000 }),

  llm: () => request<LlmSettings>("/api/settings/llm"),
  saveLlm: (body: LlmSettingsUpdate) => request<LlmSettings>("/api/settings/llm", { method: "PUT", body }),

  mcpMode: () => request<{ mode: McpMode }>("/api/settings/mcp"),
  saveMcpMode: (mode: McpMode) => request<{ mode: McpMode }>("/api/settings/mcp", { method: "PUT", body: { mode } }),
  agentTokens: () => request<AgentTokenList>("/api/agent/tokens"),
  createAgentToken: (name: string, scope: AgentTokenScope) =>
    request<AgentTokenCreated>("/api/agent/tokens", { method: "POST", body: { name, scope } }),
  revokeAgentToken: (id: string) => request<{ ok: boolean }>(`/api/agent/tokens/${enc(id)}`, { method: "DELETE" }),
  mcpAudit: (limit: number) => request<McpAuditEntry[]>(`/api/mcp/audit?limit=${limit}`),

  hours: () => request<AutomationHours>("/api/automation/hours"),
  saveHours: (hours: string | null) => request<AutomationHours>("/api/automation/hours", { method: "PUT", body: { hours } }),

  login: (username: string, password: string) =>
    request<{ ok: boolean; username?: string | null }>("/api/auth/login", { method: "POST", body: { username, password } }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  saveAccount: (body: { current_password: string; username: string; new_password: string | null }) =>
    request<{ ok: boolean; username: string | null }>("/api/auth/account", { method: "PUT", body }),

  appUpdate: () => request<AppUpdateState>("/api/app/update"),
  startAppUpdate: () => request<AppUpdateState>("/api/app/update", { method: "POST", timeoutMs: 60_000 }),
  dismissAppUpdate: () => request<{ ok: boolean }>("/api/app/update/result", { method: "DELETE" }),
  /** Git installs pull new code here; packaged builds only ask GitHub for a newer release. */
  checkManager: () => request<ManagerUpdate>("/api/update", { method: "POST", timeoutMs: SLOW }),
  updateBrowser: () => request<BrowserUpdate>("/api/browser/update", { method: "POST", timeoutMs: SLOW }),
};

export function useKernel() {
  return useQuery({ queryKey: settingsKeys.kernel, queryFn: settingsApi.kernel });
}

export function useLlmSettings() {
  return useQuery({ queryKey: settingsKeys.llm, queryFn: settingsApi.llm });
}

export function useMcpMode() {
  return useQuery({ queryKey: settingsKeys.mcp, queryFn: settingsApi.mcpMode });
}

export function useAgentTokens() {
  return useQuery({ queryKey: settingsKeys.agentTokens, queryFn: settingsApi.agentTokens });
}

export const AUDIT_LIMIT = 30;

export function useMcpAudit() {
  return useQuery({ queryKey: settingsKeys.mcpAudit, queryFn: () => settingsApi.mcpAudit(AUDIT_LIMIT) });
}

export function useHours() {
  return useQuery({ queryKey: settingsKeys.hours, queryFn: settingsApi.hours, staleTime: 60_000 });
}

/** Polled every second while an update runs, every minute otherwise. */
export function useAppUpdate() {
  return useQuery({
    queryKey: settingsKeys.appUpdate,
    queryFn: settingsApi.appUpdate,
    refetchInterval: (query) => (query.state.data && APP_UPDATE_ACTIVE.has(query.state.data.phase) ? 1_000 : 60_000),
  });
}

export function useUpdateCheck() {
  return useQuery<UpdateCheck | null>({ queryKey: settingsKeys.updateCheck, queryFn: () => null, staleTime: Infinity, gcTime: Infinity });
}

export function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
