/**
 * Opening and closing browsers, shared by the list, the detail panel and the
 * remote viewer. Every launch goes through the preflight dialog first, as in
 * the current panel; launches then run one after another so license seats and
 * CPU are not hit all at once.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { log } from "../../shared/log/logger";
import { useToast } from "../../ui";
import { profilesApi, useInvalidateProfiles } from "./api";
import { isRunning } from "./format";
import { PreflightDialog, type PreflightEntry } from "./PreflightDialog";
import type { LaunchMode, Profile } from "./types";

interface LaunchApi {
  /** Check, confirm, then open the stopped ones among `profiles`. */
  launch: (profiles: Profile[], mode: LaunchMode) => Promise<void>;
  stop: (profiles: Profile[]) => Promise<void>;
  /** Profiles with a launch or stop in flight. */
  busy: ReadonlySet<string>;
}

const LaunchCtx = createContext<LaunchApi | null>(null);

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export function LaunchProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const navigate = useNavigate();
  const invalidate = useInvalidateProfiles();
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [pending, setPending] = useState<{ entries: PreflightEntry[]; mode: LaunchMode } | null>(null);

  const mark = useCallback((ids: string[], on: boolean) => {
    setBusy((current) => {
      const next = new Set(current);
      ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
      return next;
    });
  }, []);

  const launch = useCallback(
    async (profiles: Profile[], mode: LaunchMode) => {
      const targets = profiles.filter((profile) => !isRunning(profile));
      if (targets.length === 0) return;
      mark(targets.map((p) => p.id), true);
      const results = await Promise.allSettled(targets.map((profile) => profilesApi.preflight(profile.id, mode)));
      const entries: PreflightEntry[] = [];
      results.forEach((result, index) => {
        const profile = targets[index]!;
        if (result.status === "fulfilled") entries.push({ profile, result: result.value });
        else {
          mark([profile.id], false);
          toast.show({ tone: "error", title: `没能检查「${profile.name}」`, description: message(result.reason) });
        }
      });
      // Waiting for the user's answer is not "starting" yet.
      mark(entries.map((entry) => entry.profile.id), false);
      if (entries.length) setPending({ entries, mode });
    },
    [mark, toast],
  );

  const cancel = () => setPending(null);

  const confirm = async () => {
    if (!pending || pending.entries.some((entry) => !entry.result.can_launch)) return;
    const { entries, mode } = pending;
    setPending(null);
    mark(entries.map((entry) => entry.profile.id), true);
    let opened = 0;
    for (const { profile } of entries) {
      try {
        const result = await profilesApi.launch(profile.id, mode);
        opened += 1;
        // Refresh first: the viewer leaves at once if the cached status still says stopped.
        await invalidate();
        if (entries.length === 1) {
          if (result.viewer_mode === "vnc") navigate(`/profiles/${profile.id}/viewer`);
          else toast.show({ tone: "success", title: `已打开「${profile.name}」`, description: mode === "debug" ? "调试模式，已开启 Manager CDP。" : "请在弹出的浏览器窗口里使用。" });
        }
      } catch (error) {
        log.warn(`启动失败：${profile.name}`, { action: "profile.launch", detail: error });
        toast.show({ tone: "error", title: `「${profile.name}」没能打开`, description: message(error) });
      } finally {
        mark([profile.id], false);
        void invalidate();
      }
    }
    if (entries.length > 1 && opened > 0) toast.show({ tone: "success", title: `已打开 ${opened} 个浏览器` });
  };

  const stop = useCallback(
    async (profiles: Profile[]) => {
      const targets = profiles.filter(isRunning);
      if (targets.length === 0) return;
      mark(targets.map((p) => p.id), true);
      let closed = 0;
      for (const profile of targets) {
        try {
          await profilesApi.stop(profile.id);
          closed += 1;
        } catch (error) {
          toast.show({ tone: "error", title: `「${profile.name}」没能关闭`, description: message(error) });
        } finally {
          mark([profile.id], false);
        }
      }
      await invalidate();
      if (closed > 0) toast.show({ tone: "success", title: targets.length === 1 ? `已关闭「${targets[0]!.name}」` : `已关闭 ${closed} 个浏览器` });
    },
    [invalidate, mark, toast],
  );

  const value = useMemo(() => ({ launch, stop, busy }), [launch, stop, busy]);

  return (
    <LaunchCtx.Provider value={value}>
      {children}
      {pending && <PreflightDialog entries={pending.entries} onCancel={cancel} onConfirm={() => void confirm()} />}
    </LaunchCtx.Provider>
  );
}

export function useLaunch(): LaunchApi {
  const value = useContext(LaunchCtx);
  if (!value) throw new Error("useLaunch needs <LaunchProvider>");
  return value;
}
