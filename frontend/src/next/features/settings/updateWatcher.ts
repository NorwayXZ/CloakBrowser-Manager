import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { appApi } from "../app/api";
import { settingsKeys, useAppUpdate, type AppUpdateState } from "./api";

const POLL_MS = 1_000;
const RESTART_TIMEOUT_MS = 3 * 60_000;
const STALLED_KEY = ["app", "update-stalled"] as const;

/** Replaced in tests: jsdom cannot reload. */
export const pageReloader = { reload: () => window.location.reload() };

/**
 * While the packaged app swaps itself for a new version the server goes away
 * for a while. Wait for the new version to answer, then reload so the panel
 * runs the new bundle; after 3 minutes say it looks stuck. Mounted once, in
 * the toolbar, so it works whichever page is open.
 *
 * The wait starts when the job says "restarting" and does not end just
 * because the job stops saying so: the new server may answer the job poll
 * (now idle) before the version check runs.
 */
export function useAppUpdateWatcher() {
  const queryClient = useQueryClient();
  const update = useAppUpdate();
  const [awaiting, setAwaiting] = useState<string | null>(null);
  const restarting = update.data?.phase === "restarting";
  const target = update.data?.target;
  const latest = useRef(update.data);
  latest.current = update.data;

  useEffect(() => {
    if (restarting && target) setAwaiting(target);
  }, [restarting, target]);

  useEffect(() => {
    if (!awaiting) return undefined;
    const since = Date.now();
    queryClient.setQueryData(STALLED_KEY, false);
    const timer = window.setInterval(async () => {
      try {
        const status = await appApi.status();
        if (status.app_version === awaiting) {
          window.clearInterval(timer);
          pageReloader.reload();
          return;
        }
        // An answer from a server whose job is no longer restarting, still on the
        // old version: the update gave up and its result says why.
        const job: AppUpdateState | undefined = queryClient.getQueryData(settingsKeys.appUpdate) ?? latest.current;
        if (job && job.phase !== "restarting") {
          window.clearInterval(timer);
          setAwaiting(null);
          return;
        }
      } catch {
        // The server is down while the app replaces itself; keep waiting.
      }
      if (Date.now() - since > RESTART_TIMEOUT_MS) {
        window.clearInterval(timer);
        queryClient.setQueryData(STALLED_KEY, true);
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [awaiting, queryClient]);

  return update;
}

export function useRestartStalled(): boolean {
  return useQuery({ queryKey: STALLED_KEY, queryFn: () => false, staleTime: Infinity, gcTime: Infinity }).data ?? false;
}
