import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "../shared/lib/cn";
import { IconButton } from "./Button";

/** Read-only monospace value with a copy button (CDP address, exit IP, paths). */
export function CopyField({ value, label, className }: { value: string; label: string; className?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (state === "idle") return;
    const timer = window.setTimeout(() => setState("idle"), 1600);
    return () => window.clearTimeout(timer);
  }, [state]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("failed");
    }
  };

  return (
    <div className={cn("flex min-w-0 items-center gap-1 rounded border border-border bg-surface-2 pl-2.5", className)}>
      <code className="min-w-0 flex-1 truncate font-mono text-xs text-fg" title={value}>
        {value}
      </code>
      <IconButton
        size="sm"
        label={state === "copied" ? "已复制" : state === "failed" ? "复制失败，请手动选择" : `复制${label}`}
        icon={state === "copied" ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
        onClick={() => void copy()}
      />
      <span className="sr-only" aria-live="polite">
        {state === "copied" ? "已复制" : state === "failed" ? "复制失败" : ""}
      </span>
    </div>
  );
}
