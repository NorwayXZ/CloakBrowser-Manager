import { useEffect, useState } from "react";
import { api, type AutomationStatus } from "../lib/api";

const POLL_MS = 5000;

/**
 * Persistent header pill shown while any automation (site check, warm-up,
 * evolution) is running. Automation sessions are headless, so without
 * this the user has no way to tell the Manager is busy in the background.
 */
export function AutomationIndicator() {
  const [status, setStatus] = useState<AutomationStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await api.getAutomationStatus();
        if (!cancelled) setStatus(next);
      } catch {
        if (!cancelled) setStatus(null);
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (!status?.active) return null;

  return (
    <span
      className="flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-800"
      title="自动化正在后台无头运行，不会弹出浏览器窗口"
      role="status"
    >
      <span className="relative inline-flex">
        <span className="absolute inline-flex h-2 w-2 animate-ping rounded-full bg-amber-400 opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
      </span>
      <span>
        自动化运行中：{status.label ?? "自动化"}
        {status.profile_name ? ` · ${status.profile_name}` : ""}
      </span>
    </span>
  );
}
