import { useEffect, useState } from "react";
import { Clock } from "lucide-react";
import { api, type AutomationHours as AutomationHoursState } from "../lib/api";

function useAutomationHours() {
  const [state, setState] = useState<AutomationHoursState | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .getAutomationHours()
      .then((next) => {
        if (!cancelled) setState(next);
      })
      .catch(() => {
        // Advisory UI only: if the setting can't be read, show nothing.
        if (!cancelled) setState(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return [state, setState] as const;
}

/**
 * Global allowed-hours control for scheduled automation (warm-up ticks,
 * evolution cycles). Lives in the site-check area — the automation hub —
 * because a scheduled run outside the window defers instead of starting.
 * Manual triggers ignore the window; automation itself always runs
 * headless, so even an in-window run never opens a window.
 */
export function AutomationHoursSettings() {
  const [state, setState] = useAutomationHours();
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const value = draft ?? state?.hours ?? "";

  const save = async () => {
    setError(null);
    setSaved(false);
    try {
      const next = await api.updateAutomationHours(value.trim() === "" ? null : value.trim());
      setState(next);
      setDraft(next.hours ?? "");
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    }
  };

  return (
    <div className="max-w-5xl overflow-hidden rounded-md border border-border bg-white">
      <div className="flex flex-wrap items-center gap-3 px-5 py-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-amber-50 text-amber-700">
          <Clock className="h-4 w-4" />
        </div>
        <div className="min-w-52 flex-1">
          <h2 className="text-sm font-semibold text-slate-900">自动化时段</h2>
          <p className="mt-0.5 text-xs leading-5 text-slate-500">
            定时养号、自动进化只在这个时段内启动，时段外自动推迟（手动触发不受影响）。
            自动化全程无头运行，不会弹出浏览器窗口。格式 HH-HH，可跨夜如 23-07；留空表示不限制。
          </p>
        </div>
        <input
          className="input w-28"
          aria-label="自动化时段"
          placeholder="如 09-18"
          value={value}
          onChange={(e) => {
            setDraft(e.target.value);
            setSaved(false);
          }}
        />
        <button className="btn-secondary px-3" onClick={() => void save()}>
          保存
        </button>
        {state && !state.open_now && state.hours && (
          <span className="text-xs text-amber-700">当前不在时段内，定时任务会推迟。</span>
        )}
        {saved && <span className="text-xs text-emerald-700">已保存</span>}
      </div>
      {error && (
        <div className="border-t border-red-200 bg-red-50 px-5 py-2 text-xs text-red-800">{error}</div>
      )}
    </div>
  );
}

/**
 * Small warning shown next to manual-trigger buttons when an automation
 * window is set and the current time is outside it: scheduled jobs defer,
 * but the manual action about to be taken still runs immediately.
 */
export function AutomationHoursHint() {
  const [state] = useAutomationHours();
  if (!state?.hours || state.open_now) return null;
  return (
    <p className="text-xs text-amber-700" role="note">
      当前不在自动化时段（{state.hours}）内：定时任务会推迟到时段内，手动触发不受影响，点按钮会立即开始。
    </p>
  );
}
