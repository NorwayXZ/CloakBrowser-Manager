import { AlertTriangle, CheckCircle2, Info, XCircle, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../shared/lib/cn";
import { Button } from "./Button";

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

const BADGE_TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-fg-2",
  accent: "bg-accent-soft text-accent",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-full px-2 text-xs font-medium", BADGE_TONES[tone], className)}>
      {children}
    </span>
  );
}

export type Status = "running" | "stopped" | "busy" | "error";

const STATUS: Record<Status, { dot: string; text: string }> = {
  running: { dot: "bg-success", text: "text-success" },
  stopped: { dot: "bg-fg-3", text: "text-fg-2" },
  busy: { dot: "bg-accent-fill animate-[cbm-pulse_1.2s_ease-in-out_infinite]", text: "text-accent" },
  error: { dot: "bg-danger", text: "text-danger" },
};

/** A state is never told by color alone: the dot always comes with its label. */
export function StatusDot({ status, label, className }: { status: Status; label: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1.5 text-sm", STATUS[status].text, className)}>
      <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", STATUS[status].dot)} />
      <span className="truncate">{label}</span>
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("rounded bg-surface-2 animate-[cbm-pulse_1.4s_ease-in-out_infinite]", className)} />;
}

export function ProgressBar({ value, label }: { value: number | null; label: string }) {
  const pct = value === null ? null : Math.max(0, Math.min(100, value));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct ?? undefined}
      className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
    >
      <div
        className={cn("h-full rounded-full bg-accent-fill transition-[width] duration-base", pct === null && "w-1/3 animate-[cbm-pulse_1.2s_ease-in-out_infinite]")}
        style={pct === null ? undefined : { width: `${pct}%` }}
      />
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      {Icon && (
        <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-md bg-surface-2 text-fg-3">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
      )}
      <h3 className="text-base font-semibold text-fg">{title}</h3>
      {description && <p className="mt-1 max-w-md text-sm text-fg-2">{description}</p>}
      {action && <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "没能加载出来",
  message,
  onRetry,
  retrying,
  retryLabel = "重试",
  className,
}: {
  title?: ReactNode;
  message: ReactNode;
  onRetry?: () => void;
  retrying?: boolean;
  retryLabel?: string;
  className?: string;
}) {
  return (
    <div role="alert" className={cn("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-md bg-danger-soft text-danger">
        <XCircle className="h-5 w-5" aria-hidden />
      </div>
      <h3 className="text-base font-semibold text-fg">{title}</h3>
      <p className="mt-1 max-w-md break-words text-sm text-fg-2">{message}</p>
      {onRetry && (
        <Button className="mt-4" onClick={onRetry} loading={retrying}>
          {retryLabel}
        </Button>
      )}
    </div>
  );
}

const BANNER: Record<Exclude<Tone, "neutral" | "accent">, { box: string; icon: LucideIcon }> = {
  info: { box: "border-info/30 bg-info-soft", icon: Info },
  success: { box: "border-success/30 bg-success-soft", icon: CheckCircle2 },
  warning: { box: "border-warning/30 bg-warning-soft", icon: AlertTriangle },
  danger: { box: "border-danger/30 bg-danger-soft", icon: XCircle },
};

const BANNER_ICON: Record<keyof typeof BANNER, string> = {
  info: "text-info",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
};

export function Banner({
  tone = "info",
  title,
  children,
  action,
  className,
}: {
  tone?: keyof typeof BANNER;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const Icon = BANNER[tone].icon;
  return (
    <div
      role={tone === "danger" || tone === "warning" ? "alert" : "status"}
      className={cn("flex items-start gap-3 rounded-md border px-3 py-2.5 text-sm text-fg", BANNER[tone].box, className)}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", BANNER_ICON[tone])} aria-hidden />
      <div className="min-w-0 flex-1 break-words">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className={cn(title ? "mt-0.5" : undefined, "text-fg-2")}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
