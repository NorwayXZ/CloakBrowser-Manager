import { useQuery } from "@tanstack/react-query";
import { request } from "../../shared/api/client";
import type { Profile } from "../profiles/types";

export interface BackupItem {
  name: string;
  kind: "full" | "auto";
  /** Who made a full backup: by hand, on the schedule, or before an update. */
  origin?: "manual" | "auto" | "pre-update" | "snapshot";
  size: number;
  created_at: string;
}

export interface BackupList {
  backups: BackupItem[];
  location: string;
}

export interface RestoreResult {
  ok: boolean;
  profiles: number;
  previous_data: string;
}

export interface AutoBackupSettings {
  enabled: boolean;
  interval_days: number;
  keep: number;
  copy_dir: string | null;
}

export interface AutoBackupStatus extends AutoBackupSettings {
  default_copy_dir: string;
  last_at: string | null;
  next_due_at: string | null;
  last_error: string | null;
  last_copy: string | null;
  waiting_for_browsers: boolean;
}

export interface AutoBackupRun {
  ok: boolean;
  name: string;
  copy: string | null;
  copy_error: string | null;
  status: AutoBackupStatus;
}

export interface ConfigImportResult {
  ok: boolean;
  profiles: number;
  groups: number;
  proxy_presets: number;
}

const enc = encodeURIComponent;
// Zipping or unzipping every profile can take minutes; the request stays open meanwhile.
const LONG = 30 * 60_000;

export const dataKeys = {
  backups: ["backups", "list"] as const,
  auto: ["backups", "auto"] as const,
  trash: ["profiles", "trash"] as const,
};

export const dataApi = {
  backups: () => request<BackupList>("/api/backups"),
  createBackup: () => request<BackupItem>("/api/backups", { method: "POST", timeoutMs: LONG }),
  downloadUrl: (name: string) => `/api/backups/full/${enc(name)}/download`,
  deleteBackup: (item: Pick<BackupItem, "kind" | "name">) => request<{ ok: boolean }>(`/api/backups/${item.kind}/${enc(item.name)}`, { method: "DELETE" }),
  restore: (item: Pick<BackupItem, "kind" | "name">) => request<RestoreResult>(`/api/backups/${item.kind}/${enc(item.name)}/restore`, { method: "POST", timeoutMs: LONG }),
  restoreFile: (file: File) =>
    request<RestoreResult>("/api/backups/restore-upload", { method: "POST", body: file.type ? file : new Blob([file], { type: "application/zip" }), timeoutMs: LONG }),
  reveal: () => request<{ ok: boolean; location: string }>("/api/backups/reveal", { method: "POST" }),
  exportConfig: () => request<Record<string, unknown>>("/api/configuration/export"),
  importConfig: (backup: Record<string, unknown>) => request<ConfigImportResult>("/api/configuration/import", { method: "POST", body: backup }),
  auto: () => request<AutoBackupStatus>("/api/backups/auto"),
  saveAuto: (settings: AutoBackupSettings) => request<AutoBackupStatus>("/api/backups/auto", { method: "PUT", body: settings }),
  runAuto: () => request<AutoBackupRun>("/api/backups/auto/run", { method: "POST", timeoutMs: LONG }),
  trash: () => request<Profile[]>("/api/profiles/trash"),
  restoreProfile: (id: string) => request<Profile>(`/api/profiles/${enc(id)}/restore`, { method: "POST" }),
  purge: (id: string) => request<{ ok: boolean }>(`/api/profiles/${enc(id)}/purge`, { method: "DELETE" }),
};

export function useBackups() {
  return useQuery({ queryKey: dataKeys.backups, queryFn: dataApi.backups });
}

export function useAutoBackup() {
  return useQuery({ queryKey: dataKeys.auto, queryFn: dataApi.auto });
}

export function useTrash() {
  return useQuery({ queryKey: dataKeys.trash, queryFn: dataApi.trash });
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function backupLabel(item: BackupItem): string {
  if (item.kind !== "full") return "自动快照";
  if (item.origin === "auto") return "自动完整备份";
  if (item.origin === "pre-update") return "更新前备份";
  return "完整备份";
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "还没有";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** Days left before the trash empties itself (it keeps profiles for 7 days). */
export function daysLeft(deletedAt: string | null | undefined, now = Date.now()): number | null {
  if (!deletedAt) return null;
  const deleted = new Date(deletedAt).getTime();
  if (Number.isNaN(deleted)) return null;
  return Math.max(0, Math.ceil((deleted + 7 * 86_400_000 - now) / 86_400_000));
}

/** Hand a URL to the browser as a download (the macOS panel turns it into a save dialog). */
export function triggerDownload(href: string, filename: string) {
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}
