import * as RadixDialog from "@radix-ui/react-dialog";
import * as RadixMenu from "@radix-ui/react-dropdown-menu";
import * as RadixPopover from "@radix-ui/react-popover";
import * as RadixTabs from "@radix-ui/react-tabs";
import { Check, X } from "lucide-react";
import type { ReactElement, ReactNode } from "react";
import { cn } from "../shared/lib/cn";
import { IconButton } from "./Button";

// ── Dialog ──────────────────────────────────────────────────────────────────

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = "md",
  dismissible = true,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  /** false while an action runs: Esc and clicks outside then do nothing. */
  dismissible?: boolean;
}) {
  const width = size === "sm" ? "max-w-sm" : size === "lg" ? "max-w-3xl" : "max-w-lg";
  return (
    <RadixDialog.Root open={open} onOpenChange={(next) => (dismissible || next ? onOpenChange(next) : undefined)}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-backdrop/40 animate-[cbm-fade-in_120ms_ease-out]" />
        <RadixDialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 flex max-h-[calc(100vh-48px)] w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 flex-col",
            "rounded-lg border border-border bg-surface shadow-modal focus:outline-none animate-[cbm-pop-in_160ms_ease-out]",
            width,
          )}
        >
          <div className="flex items-start gap-3 px-5 pb-3 pt-4">
            <div className="min-w-0 flex-1">
              <RadixDialog.Title className="text-md font-semibold text-fg">{title}</RadixDialog.Title>
              {description ? (
                <RadixDialog.Description className="mt-1 text-sm text-fg-2">{description}</RadixDialog.Description>
              ) : (
                <RadixDialog.Description className="sr-only">{title}</RadixDialog.Description>
              )}
            </div>
            {dismissible && (
              <RadixDialog.Close asChild>
                <IconButton label="关闭" icon={<X className="h-4 w-4" />} size="sm" className="-mr-1.5 -mt-0.5" />
              </RadixDialog.Close>
            )}
          </div>
          {children && <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-4 text-sm text-fg">{children}</div>}
          {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

// ── Dropdown menu ───────────────────────────────────────────────────────────

const menuContent =
  "z-50 min-w-44 rounded-md border border-border bg-surface p-1 shadow-popover animate-[cbm-pop-in_120ms_ease-out]";
const menuItem =
  "flex h-8 cursor-default select-none items-center gap-2 rounded px-2 text-sm text-fg outline-none " +
  "data-[highlighted]:bg-surface-2 data-[disabled]:pointer-events-none data-[disabled]:opacity-50";

export function Menu({ trigger, children, align = "end" }: { trigger: ReactElement; children: ReactNode; align?: "start" | "end" }) {
  return (
    <RadixMenu.Root>
      <RadixMenu.Trigger asChild>{trigger}</RadixMenu.Trigger>
      <RadixMenu.Portal>
        <RadixMenu.Content align={align} sideOffset={4} className={menuContent}>
          {children}
        </RadixMenu.Content>
      </RadixMenu.Portal>
    </RadixMenu.Root>
  );
}

export function MenuItem({
  children,
  icon,
  onSelect,
  danger,
  disabled,
  shortcut,
}: {
  children: ReactNode;
  icon?: ReactNode;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
  shortcut?: string;
}) {
  return (
    <RadixMenu.Item className={cn(menuItem, danger && "text-danger")} onSelect={onSelect} disabled={disabled}>
      <span className="flex h-4 w-4 items-center justify-center" aria-hidden>
        {icon}
      </span>
      <span className="flex-1">{children}</span>
      {shortcut && <span className="text-xs text-fg-3">{shortcut}</span>}
    </RadixMenu.Item>
  );
}

export function MenuRadioGroup({
  value,
  onValueChange,
  options,
  label,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: { value: string; label: ReactNode; icon?: ReactNode }[];
  label?: ReactNode;
}) {
  return (
    <>
      {label && <RadixMenu.Label className="px-2 py-1 text-xs text-fg-3">{label}</RadixMenu.Label>}
      <RadixMenu.RadioGroup value={value} onValueChange={onValueChange}>
        {options.map((option) => (
          <RadixMenu.RadioItem key={option.value} value={option.value} className={menuItem}>
            <span className="flex h-4 w-4 items-center justify-center" aria-hidden>
              {option.icon}
            </span>
            <span className="flex-1">{option.label}</span>
            <RadixMenu.ItemIndicator>
              <Check className="h-4 w-4 text-accent" aria-hidden />
            </RadixMenu.ItemIndicator>
          </RadixMenu.RadioItem>
        ))}
      </RadixMenu.RadioGroup>
    </>
  );
}

export function MenuSeparator() {
  return <RadixMenu.Separator className="my-1 h-px bg-border" />;
}

// ── Popover ─────────────────────────────────────────────────────────────────

export function Popover({
  trigger,
  children,
  align = "end",
  label,
  onOpenChange,
}: {
  trigger: ReactElement;
  children: ReactNode;
  align?: "start" | "center" | "end";
  label: string;
  onOpenChange?: (open: boolean) => void;
}) {
  return (
    <RadixPopover.Root onOpenChange={onOpenChange}>
      <RadixPopover.Trigger asChild>{trigger}</RadixPopover.Trigger>
      <RadixPopover.Portal>
        <RadixPopover.Content
          aria-label={label}
          align={align}
          sideOffset={6}
          className="z-50 w-72 max-w-[calc(100vw-32px)] rounded-md border border-border bg-surface p-3 text-sm shadow-popover animate-[cbm-pop-in_120ms_ease-out] focus:outline-none"
        >
          {children}
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}

// ── Tabs ────────────────────────────────────────────────────────────────────

export function Tabs({
  value,
  onValueChange,
  tabs,
  label,
}: {
  value: string;
  onValueChange: (value: string) => void;
  tabs: { value: string; label: ReactNode; content: ReactNode }[];
  label: string;
}) {
  return (
    <RadixTabs.Root value={value} onValueChange={onValueChange} className="min-w-0">
      <RadixTabs.List aria-label={label} className="flex gap-1 overflow-x-auto border-b border-border">
        {tabs.map((tab) => (
          <RadixTabs.Trigger
            key={tab.value}
            value={tab.value}
            className={cn(
              "-mb-px h-9 shrink-0 whitespace-nowrap border-b-2 border-transparent px-3 text-sm font-medium text-fg-2",
              "transition-colors duration-fast hover:text-fg data-[state=active]:border-accent data-[state=active]:text-fg",
            )}
          >
            {tab.label}
          </RadixTabs.Trigger>
        ))}
      </RadixTabs.List>
      {tabs.map((tab) => (
        <RadixTabs.Content key={tab.value} value={tab.value} className="pt-4 focus:outline-none">
          {tab.content}
        </RadixTabs.Content>
      ))}
    </RadixTabs.Root>
  );
}
