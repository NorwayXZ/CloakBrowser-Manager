import { useState } from "react";
import { Bot, Hand } from "lucide-react";
import { api, type AgentLease } from "../lib/api";

interface AgentLeaseBadgeProps {
  profileId: string;
  lease: AgentLease;
  onChanged: () => Promise<void> | void;
}

function minutesLeft(lease: AgentLease): number {
  return Math.max(1, Math.ceil(lease.seconds_left / 60));
}

/**
 * Shown on a running profile while an AI agent drives it (or after the user
 * took over). "接管" parks the profile on the user and cuts the agent's live
 * CDP connections; "归还" lets agents back in.
 */
export function AgentLeaseBadge({ profileId, lease, onChanged }: AgentLeaseBadgeProps) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const byUser = lease.kind === "human";

  const act = async () => {
    setBusy(true);
    setFailed(false);
    try {
      if (byUser) await api.releaseProfileLease(profileId);
      else await api.takeoverProfile(profileId);
      await onChanged();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={`mt-1.5 flex items-center gap-2 text-xs ${byUser ? "text-slate-500" : "text-amber-600"}`}
      data-testid="agent-lease"
    >
      {byUser ? <Hand className="h-3.5 w-3.5 shrink-0" /> : <Bot className="h-3.5 w-3.5 shrink-0" />}
      <span className="min-w-0">
        {byUser
          ? `你已接管，AI 暂不能操作（约 ${minutesLeft(lease)} 分钟后自动归还）`
          : `AI 控制中：${lease.holder}（${minutesLeft(lease)} 分钟内有效）`}
      </span>
      <button
        className="shrink-0 whitespace-nowrap rounded border border-current px-1.5 py-0.5 hover:bg-black/5 disabled:opacity-50"
        disabled={busy}
        onClick={() => void act()}
      >
        {byUser ? "归还给 AI" : "接管"}
      </button>
      {failed && <span className="text-red-500">操作失败</span>}
    </div>
  );
}
