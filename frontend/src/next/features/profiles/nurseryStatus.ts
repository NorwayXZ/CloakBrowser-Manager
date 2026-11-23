import { useQueries } from "@tanstack/react-query";
import { request } from "../../shared/api/client";
import type { Tone } from "../../ui";
import type { Profile } from "./types";

export const DESKTOP_TARGET_ROUNDS = 3;
export const DESKTOP_TARGET_DAYS = 2;
export const MOBILE_TARGET_DAYS = 2;

const CYCLE_STORAGE_KEY = "cbm.nursery.cycle.v1";

interface CycleEntry {
  seed: number | null;
  startedAt: string;
  manualDays: string[];
}

export interface WarmupRunItem {
  id: string;
  started_at: string;
  finished_at?: string | null;
  pages_visited?: number | null;
  status: string;
  reason?: string | null;
}

export interface ProfileWarmupResponse {
  enabled: boolean;
  daily_max: number;
  targets: string[];
  warming: boolean;
  runs: WarmupRunItem[];
}

export interface NurseryBadgeInfo {
  tone: Tone;
  label: string;
  ready: boolean;
  warming: boolean;
  detail: string;
}

function localDay(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function readCycleMap(): Record<string, CycleEntry> {
  try {
    const raw = window.localStorage.getItem(CYCLE_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, CycleEntry>) : {};
  } catch {
    return {};
  }
}

function writeCycleMap(map: Record<string, CycleEntry>) {
  try {
    window.localStorage.setItem(CYCLE_STORAGE_KEY, JSON.stringify(map));
  } catch {
    // Ignore storage quota errors.
  }
}

/**
 * Syncs a profile's current fingerprint_seed into localStorage so that whenever
 * "一键重置 / 新一轮" rolls a new seed, the warmup counter resets cleanly to 0.
 */
export function syncNurseryCycle(profile: Profile): CycleEntry {
  const map = readCycleMap();
  const seed = profile.fingerprint_seed ?? null;
  const existing = map[profile.id];
  let entry: CycleEntry;

  if (!existing) {
    entry = {
      seed,
      startedAt: profile.created_at || new Date(0).toISOString(),
      manualDays: [],
    };
  } else if (existing.seed !== seed) {
    // Seed changed -> profile was reset for a brand-new registration cycle!
    entry = {
      seed,
      startedAt: new Date().toISOString(),
      manualDays: [],
    };
  } else {
    entry = { ...existing, manualDays: [...(existing.manualDays ?? [])] };
  }

  if (profile.last_opened_at && profile.last_opened_at >= entry.startedAt) {
    const openedDay = localDay(profile.last_opened_at);
    if (openedDay && !entry.manualDays.includes(openedDay)) {
      entry.manualDays.push(openedDay);
    }
  }

  if (
    !existing ||
    existing.seed !== entry.seed ||
    (existing.manualDays ?? []).length !== entry.manualDays.length
  ) {
    map[profile.id] = entry;
    writeCycleMap(map);
  }
  return entry;
}

export function computeNurseryBadge(
  profile: Profile,
  warmup: ProfileWarmupResponse | undefined,
): NurseryBadgeInfo {
  const cycle = syncNurseryCycle(profile);

  if (profile.platform === "ios") {
    const days = cycle.manualDays.length;
    if (days >= MOBILE_TARGET_DAYS) {
      return {
        tone: "success",
        label: "可注册 Gmail",
        ready: true,
        warming: false,
        detail: `已跨 ${days} 天手动逛过网页，可直接打开从联动入口创建账号`,
      };
    }
    return {
      tone: days > 0 ? "warning" : "neutral",
      label: days > 0 ? `暖床 ${days}/${MOBILE_TARGET_DAYS} 天` : `待暖床 0/${MOBILE_TARGET_DAYS} 天`,
      ready: false,
      warming: false,
      detail: `手机版请分 ${MOBILE_TARGET_DAYS} 天各点「打开」刷 2 分钟视频后再创建账号`,
    };
  }

  if (warmup?.warming) {
    return {
      tone: "accent",
      label: "正在暖床…",
      ready: false,
      warming: true,
      detail: "正在后台无窗口自动浏览网页（约 4～6 分钟自动停下）",
    };
  }

  const okRuns = (warmup?.runs ?? []).filter(
    (run) =>
      run.status === "ok" &&
      (run.pages_visited ?? 0) > 0 &&
      run.started_at >= cycle.startedAt,
  );
  const rounds = okRuns.length;
  const distinctDays = new Set(okRuns.map((r) => localDay(r.started_at)).filter(Boolean)).size;

  if (rounds >= DESKTOP_TARGET_ROUNDS && distinctDays >= DESKTOP_TARGET_DAYS) {
    return {
      tone: "success",
      label: "可注册 Gmail",
      ready: true,
      warming: false,
      detail: `已完成 ${rounds} 轮暖床（跨 ${distinctDays} 天），可以点「打开」从 YouTube / 地图等联动入口注册`,
    };
  }

  if (rounds >= DESKTOP_TARGET_ROUNDS && distinctDays < DESKTOP_TARGET_DAYS) {
    return {
      tone: "info",
      label: "已满 3 轮 · 明日可注册",
      ready: false,
      warming: false,
      detail: "今天已满 3 轮，建议隔夜沉淀到明天再点「打开」注册，更像老熟人",
    };
  }

  return {
    tone: rounds > 0 ? "warning" : "neutral",
    label: rounds > 0 ? `暖床中 ${rounds}/${DESKTOP_TARGET_ROUNDS} 轮` : `待暖床 0/${DESKTOP_TARGET_ROUNDS} 轮`,
    ready: false,
    warming: false,
    detail: `建议分 2～3 天跑满 ${DESKTOP_TARGET_ROUNDS} 轮（当前 ${rounds}/${DESKTOP_TARGET_ROUNDS} 轮，已跨 ${distinctDays}/${DESKTOP_TARGET_DAYS} 天）`,
  };
}

export function useNurseryWarmupMap(profiles: Profile[], enabled: boolean) {
  const desktopProfiles = enabled ? profiles.filter((p) => p.platform !== "ios") : [];
  const results = useQueries({
    queries: desktopProfiles.map((p) => ({
      queryKey: ["nursery", "warmup", p.id] as const,
      queryFn: () => request<ProfileWarmupResponse>(`/api/profiles/${encodeURIComponent(p.id)}/warmup`),
      refetchInterval: 6_000,
    })),
  });
  const map = new Map<string, ProfileWarmupResponse>();
  desktopProfiles.forEach((p, idx) => {
    const data = results[idx]?.data;
    if (data) map.set(p.id, data);
  });
  return map;
}
