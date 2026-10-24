import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cn } from "../shared/lib/cn";

/**
 * Table parts. The wrapper is the only place allowed to scroll sideways; the
 * header stays put while the body scrolls.
 */
export function Table({ children, label, className }: { children: ReactNode; label: string; className?: string }) {
  return (
    <div className={cn("min-w-0 overflow-auto rounded-md border border-border bg-surface", className)}>
      <table aria-label={label} className="w-full border-separate border-spacing-0 text-sm">
        {children}
      </table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return <thead className="sticky top-0 z-10 bg-surface-2">{children}</thead>;
}

export function TH({ className, children, ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn("h-9 whitespace-nowrap border-b border-border px-3 text-left text-xs font-medium text-fg-2", className)}
      {...rest}
    >
      {children}
    </th>
  );
}

export function TR({ className, selected, children, ...rest }: HTMLAttributes<HTMLTableRowElement> & { selected?: boolean }) {
  return (
    <tr
      aria-selected={selected}
      className={cn("transition-colors duration-fast hover:bg-surface-2", selected && "bg-accent-soft hover:bg-accent-soft", className)}
      {...rest}
    >
      {children}
    </tr>
  );
}

export function TD({ className, children, ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={cn("h-11 border-b border-border px-3 align-middle text-fg", className)} {...rest}>
      {children}
    </td>
  );
}
