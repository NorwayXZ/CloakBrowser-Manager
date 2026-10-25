import type { ReactNode } from "react";
import { cn } from "../shared/lib/cn";

export function Kbd({ children, tone = "default" }: { children: ReactNode; tone?: "default" | "inverse" }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-sm px-1 font-sans text-xs",
        tone === "default" ? "border border-border bg-surface-2 text-fg-2" : "bg-canvas/15 text-canvas",
      )}
    >
      {children}
    </kbd>
  );
}
