import { Bot, Hand } from "lucide-react";
import { useState } from "react";
import { cn } from "../../shared/lib/cn";
import { Button, useToast } from "../../ui";
import { profilesApi, useInvalidateProfiles } from "./api";
import type { AgentLease, Profile } from "./types";

function minutesLeft(lease: AgentLease): number {
  return Math.max(1, Math.ceil(lease.seconds_left / 60));
}

/**
 * Shown under a running profile while an AI agent drives it, and after the
 * person took over. 接管 parks the profile on the person and cuts the agent's
 * live CDP connections; 归还给 AI lets agents back in. The button never wraps:
 * the text may truncate, the action may not.
 */
export function AgentLeaseBadge({ profile, lease }: { profile: Pick<Profile, "id" | "name">; lease: AgentLease }) {
  const invalidate = useInvalidateProfiles();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const byPerson = lease.kind === "human";

  const act = async () => {
    setBusy(true);
    try {
      if (byPerson) await profilesApi.releaseLease(profile.id);
      else await profilesApi.takeover(profile.id);
      await invalidate();
    } catch (error) {
      toast.show({
        tone: "error",
        title: byPerson ? `没能把「${profile.name}」归还给 AI` : `没能接管「${profile.name}」`,
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setBusy(false);
    }
  };

  // The name column is narrow: the line stays short, the timing goes in the tooltip.
  const text = byPerson ? "你已接管，AI 暂不能操作" : `AI 控制中：${lease.holder}`;
  const detail = byPerson ? `${text}（约 ${minutesLeft(lease)} 分钟后自动归还）` : `${text}（${minutesLeft(lease)} 分钟内有效）`;
  return (
    <div className={cn("mt-1 flex min-w-0 items-center gap-1.5 text-xs", byPerson ? "text-fg-2" : "text-warning")} data-testid="agent-lease">
      {byPerson ? <Hand className="h-3.5 w-3.5 shrink-0" aria-hidden /> : <Bot className="h-3.5 w-3.5 shrink-0" aria-hidden />}
      <span className="min-w-0 truncate" title={detail}>
        {text}
      </span>
      <Button size="sm" className="h-5 px-1.5" loading={busy} onClick={() => void act()} aria-label={byPerson ? `把「${profile.name}」归还给 AI` : `接管「${profile.name}」`}>
        {byPerson ? "归还给 AI" : "接管"}
      </Button>
    </div>
  );
}
