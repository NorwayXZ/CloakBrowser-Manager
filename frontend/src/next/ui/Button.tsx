import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "../shared/lib/cn";
import { Spinner } from "./Spinner";
import { Tooltip } from "./Tooltip";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "danger-ghost";
export type ButtonSize = "sm" | "md";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-gradient-to-br from-accent-fill to-accent-fill-2 text-accent-on shadow-[0_6px_16px_rgb(91_80_232/0.28)] " +
    "hover:from-accent-fill-hover hover:to-accent-fill-2 hover:brightness-105 active:brightness-95",
  secondary: "border border-border-strong/60 bg-surface/70 text-fg hover:bg-surface active:bg-surface-2",
  ghost: "text-fg-2 hover:bg-surface-2 hover:text-fg active:bg-surface-3",
  danger: "bg-danger text-danger-on hover:bg-danger-hover active:bg-danger-hover",
  /** Destructive but secondary: red text, no fill (e.g. "移到回收站" beside other actions). */
  "danger-ghost": "text-danger hover:bg-danger-soft active:bg-danger-soft",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 px-3.5 text-xs",
  md: "h-10 gap-2 px-5 text-sm",
};

export const buttonBase =
  "inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded-full font-semibold " +
  "transition-[background-color,border-color,color,box-shadow,transform] duration-fast active:scale-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 " +
  "focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-50";

/** Button look for elements that must stay links (e.g. "open the old panel"). */
export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md"): string {
  return cn(buttonBase, VARIANTS[variant], SIZES[size]);
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner in place of the icon and blocks clicks; the width stays the same. */
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading = false, icon, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(buttonBase, VARIANTS[variant], SIZES[size], className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Spinner className={size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5"} /> : icon}
      {children}
    </button>
  );
});

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  /** Accessible name, also shown as the tooltip. Required: an icon alone says nothing to a screen reader. */
  label: string;
  icon: ReactNode;
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  shortcut?: string;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, icon, variant = "ghost", size = "md", loading = false, shortcut, className, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <Tooltip content={label} shortcut={shortcut}>
      <button
        ref={ref}
        type={type}
        aria-label={label}
        className={cn(buttonBase, VARIANTS[variant], size === "sm" ? "h-8 w-8" : "h-10 w-10", className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...rest}
      >
        {loading ? <Spinner className="h-3.5 w-3.5" /> : icon}
      </button>
    </Tooltip>
  );
});
