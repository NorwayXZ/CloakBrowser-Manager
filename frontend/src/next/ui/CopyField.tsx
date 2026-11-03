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


/** A multi-line command or config snippet with a copy button (the connection commands). */
export function CodeBlock({ value, label, className }: { value: string; label: string; className?: string }) {
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
    <div className={cn("relative min-w-0 rounded border border-border bg-surface-2", className)}>
      <pre className="m-0 overflow-x-auto px-3 py-2.5 pr-24 font-mono text-xs leading-5 text-fg" tabIndex={0} aria-label={label}>
        <code>{value}</code>
      </pre>
      <button
        type="button"
        onClick={() => void copy()}
        className="absolute right-2 top-2 inline-flex h-7 items-center gap-1 rounded border border-border bg-surface px-2 text-xs text-fg-2 hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        aria-label={state === "copied" ? "已复制" : state === "failed" ? "复制失败，请手动选择" : `复制${label}`}
      >
        {state === "copied" ? <Check className="h-3.5 w-3.5 text-success" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
        {state === "copied" ? "已复制" : "复制代码"}
      </button>
      <span className="sr-only" aria-live="polite">
        {state === "copied" ? "已复制" : state === "failed" ? "复制失败" : ""}
      </span>
    </div>
  );
}
