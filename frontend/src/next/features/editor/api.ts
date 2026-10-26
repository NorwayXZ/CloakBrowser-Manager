import { useQuery } from "@tanstack/react-query";
import { ApiError, detailMessage, request } from "../../shared/api/client";
import type {
  AutomationHours,
  CookieExportFormat,
  CookieMergeResult,
  CookiePullResult,
  ProxyPreset,
  ProxyTestResult,
  WarmupInfo,
  WarmupScriptsInfo,
  WarmupTarget,
} from "./types";

const enc = encodeURIComponent;

export const editorKeys = {
  proxyPresets: ["proxy-presets", "list"] as const,
  warmupTargets: ["warmup", "targets"] as const,
  warmup: (id: string) => ["profiles", id, "warmup"] as const,
  scripts: (id: string) => ["profiles", id, "warmup-scripts"] as const,
  automationHours: ["automation", "hours"] as const,
};

export const editorApi = {
  proxyPresets: () => request<ProxyPreset[]>("/api/proxy-presets"),
  // The backend dials out through the proxy and asks several IP services.
  testProxy: (proxy: string | null) => request<ProxyTestResult>("/api/proxy/test", { method: "POST", body: { proxy }, timeoutMs: 60_000 }),
  mergeCookies: (text: string, existing: string | null, domain: string | null) =>
    request<CookieMergeResult>("/api/cookies/merge", { method: "POST", body: { text, existing, domain } }),
  pullCookies: (id: string) => request<CookiePullResult>(`/api/profiles/${enc(id)}/cookies/pull`, { method: "POST", timeoutMs: 30_000 }),
  warmupTargets: () => request<WarmupTarget[]>("/api/warmup/targets"),
  warmup: (id: string) => request<WarmupInfo>(`/api/profiles/${enc(id)}/warmup`),
  runWarmup: (id: string) => request<{ ok: boolean; started: boolean }>(`/api/profiles/${enc(id)}/warmup/run`, { method: "POST" }),
  scripts: (id: string) => request<WarmupScriptsInfo>(`/api/profiles/${enc(id)}/warmup/scripts`),
  generateScripts: (id: string) => request<{ ok: boolean }>(`/api/profiles/${enc(id)}/warmup/scripts/generate`, { method: "POST" }),
  decideScripts: (id: string, batchId: string, approve: boolean) =>
    request<{ ok: boolean }>(`/api/profiles/${enc(id)}/warmup/scripts/batches/${enc(batchId)}/${approve ? "approve" : "reject"}`, { method: "POST" }),
  automationHours: () => request<AutomationHours>("/api/automation/hours"),
};

/**
 * Fetch the cookie export and hand it to the browser as a file. Fetching
 * first (instead of a plain link) shows the server's reason when the browser
 * cannot be read, rather than saving an error page. The macOS panel window
 * turns the blob link into a save dialog.
 */
export async function downloadCookieExport(id: string, format: CookieExportFormat, filename: string): Promise<void> {
  const response = await fetch(`/api/profiles/${enc(id)}/cookies/export?format=${format}`, { credentials: "same-origin" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError("http", detailMessage(body.detail, response.statusText), response.status, body.detail);
  }
  const url = URL.createObjectURL(await response.blob());
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

export function useProxyPresets() {
  return useQuery({ queryKey: editorKeys.proxyPresets, queryFn: editorApi.proxyPresets });
}

export function useWarmupTargets() {
  return useQuery({ queryKey: editorKeys.warmupTargets, queryFn: editorApi.warmupTargets, staleTime: Infinity });
}

export function useWarmupInfo(id: string | null) {
  return useQuery({ queryKey: editorKeys.warmup(id ?? ""), queryFn: () => editorApi.warmup(id!), enabled: id !== null });
}

export function useWarmupScripts(id: string) {
  return useQuery({
    queryKey: editorKeys.scripts(id),
    queryFn: () => editorApi.scripts(id),
    // Generation is a background job: poll while it runs.
    refetchInterval: (query) => (query.state.data?.generating ? 2_500 : false),
  });
}

export function useAutomationHours() {
  return useQuery({ queryKey: editorKeys.automationHours, queryFn: editorApi.automationHours, staleTime: 60_000 });
}
