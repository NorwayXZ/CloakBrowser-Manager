import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cn } from "../shared/lib/cn";

/**
 * Table parts. The wrapper is the only place allowed to scroll sideways; the
 * header stays put while the body scrolls.
 */
export function Table({
  children,
  label,
  className,
  minWidth,
}: {
  children: ReactNode;
  label: string;
  className?: string;
  /** Below this width the table scrolls sideways inside its frame instead of squeezing columns. */
  minWidth?: number;
}) {
  return (
    <div className={cn("min-w-0 overflow-auto px-1 pb-1", className)}>
      <table aria-label={label} className="-mt-2 w-full table-fixed border-separate border-spacing-x-0 border-spacing-y-2.5 text-sm" style={minWidth ? { minWidth } : undefined}>
        {children}
      </table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return <thead>{children}</thead>;
}

export function TH({ className, children, ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn("h-8 whitespace-nowrap px-4 text-left text-xs font-medium text-fg-3", className)}
      {...rest}
    >
      {children}
    </th>
  );
}

/** `selected` is visual only (plain table rows take no aria-selected); the row's checkbox carries the state. */
export function TR({ className, selected, children, ...rest }: HTMLAttributes<HTMLTableRowElement> & { selected?: boolean }) {
  return (
    <tr
      data-selected={selected || undefined}
      className={cn("group", className)}
      {...rest}
    >
      {children}
    </tr>
  );
}

export function TD({ className, children, ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={cn("h-14 border-y border-border bg-surface/80 px-4 align-middle text-fg transition-colors duration-fast first:rounded-l-lg first:border-l last:rounded-r-lg last:border-r group-hover:bg-surface group-data-[selected]:bg-accent-soft", className)} {...rest}>
      {children}
    </td>
  );
}
