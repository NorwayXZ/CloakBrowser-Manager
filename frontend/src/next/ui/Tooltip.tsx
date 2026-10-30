import * as RadixTooltip from "@radix-ui/react-tooltip";
import type { ReactElement, ReactNode } from "react";
import { Kbd } from "./Kbd";

export const TooltipProvider = RadixTooltip.Provider;

export function Tooltip({
  content,
  shortcut,
  side = "bottom",
  children,
}: {
  content: ReactNode;
  shortcut?: string;
  side?: "top" | "bottom" | "left" | "right";
  children: ReactElement;
}) {
  return (
    <RadixTooltip.Root delayDuration={400}>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={6}
          className="z-50 flex max-w-xs items-center gap-2 rounded-md bg-fg/90 px-2.5 py-1 text-xs text-canvas shadow-popover backdrop-blur-md animate-[cbm-fade-in_150ms_ease-out]"
        >
          {content}
          {shortcut && <Kbd tone="inverse">{shortcut}</Kbd>}
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}
