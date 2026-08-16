import { Bug, Loader2, Play, Square } from "lucide-react";
import { useState } from "react";

interface LaunchButtonProps {
  status: "running" | "stopped";
  onLaunch: () => Promise<void>;
  onDebugLaunch?: () => Promise<void>;
  onStop: () => Promise<void>;
  launchLabel?: string;
  showDebugLaunch?: boolean;
}

export function LaunchButton({
  status,
  onLaunch,
  onDebugLaunch,
  onStop,
  launchLabel = "启动",
  showDebugLaunch = true,
}: LaunchButtonProps) {
  const [loadingAction, setLoadingAction] = useState<"primary" | "debug" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleAction = async (action: () => Promise<void>, actionKey: "primary" | "debug") => {
    setLoadingAction(actionKey);
    setError(null);
    try {
      await action();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "操作失败";
      setError(msg);
      console.error("操作失败:", err);
    } finally {
      setLoadingAction(null);
    }
  };

  const handleClick = async () => {
    await handleAction(status === "running" ? onStop : onLaunch, "primary");
  };

  const handleDebugClick = async () => {
    if (!onDebugLaunch) return;
    await handleAction(onDebugLaunch, "debug");
  };

  if (loadingAction === "primary") {
    return (
      <button disabled className="btn-secondary opacity-60 cursor-not-allowed flex items-center gap-1.5">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span>{status === "running" ? "停止中..." : "启动中..."}</span>
      </button>
    );
  }

  if (status === "running") {
    return (
      <button onClick={handleClick} className="btn-danger flex items-center gap-1.5" disabled={loadingAction !== null}>
        <Square className="h-3.5 w-3.5" />
        <span>停止</span>
      </button>
    );
  }

  return (
    <div>
      <div className="flex items-center gap-2">
        <button
          onClick={handleClick}
          className="btn-primary flex items-center gap-1.5"
          disabled={loadingAction !== null}
        >
          <Play className="h-3.5 w-3.5" />
          <span>{launchLabel}</span>
        </button>
        {showDebugLaunch && onDebugLaunch && (
          <button
            onClick={handleDebugClick}
            className="btn-secondary flex items-center gap-1.5"
            title="带 CDP 打开，用于排查 console、cookie 和指纹自检"
            disabled={loadingAction !== null}
          >
            {loadingAction === "debug" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Bug className="h-3.5 w-3.5" />
            )}
            <span>{loadingAction === "debug" ? "调试中..." : "调试启动"}</span>
          </button>
        )}
      </div>
      {error && <p className="text-red-400 text-xs mt-1">{error}</p>}
    </div>
  );
}
