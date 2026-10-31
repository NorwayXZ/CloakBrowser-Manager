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
  flat,
}: {
  children: ReactNode;
  label: string;
  className?: string;
  /** Below this width the table scrolls sideways inside its frame instead of squeezing columns. */
  minWidth?: number;
  /** One framed table with ruled rows, for long dense lists, instead of a card per row. */
  flat?: boolean;
}) {
  return (
    <div data-flat={flat || undefined} className={cn("group/t min-w-0 overflow-auto px-1 pb-1", flat && "glass rounded-lg px-0 pb-0", className)}>
      <table aria-label={label} className="-mt-2 w-full table-fixed border-separate border-spacing-x-0 border-spacing-y-2.5 text-sm group-data-[flat]/t:mt-0 group-data-[flat]/t:border-spacing-y-0" style={minWidth ? { minWidth } : undefined}>
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
      className={cn("h-8 whitespace-nowrap px-4 text-left text-xs font-medium text-fg-3 group-data-[flat]/t:h-9 group-data-[flat]/t:border-b group-data-[flat]/t:border-border group-data-[flat]/t:bg-surface-2/70 group-data-[flat]/t:px-3", className)}
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
    <td className={cn("h-14 border-y border-border bg-surface/80 px-4 align-middle text-fg transition-colors duration-fast first:rounded-l-lg first:border-l last:rounded-r-lg last:border-r group-hover:bg-surface group-data-[selected]:bg-accent-soft group-data-[flat]/t:h-11 group-data-[flat]/t:rounded-none group-data-[flat]/t:border-x-0 group-data-[flat]/t:border-t-0 group-data-[flat]/t:bg-transparent group-data-[flat]/t:px-3 group-data-[flat]/t:group-hover:bg-surface-2", className)} {...rest}>
      {children}
    </td>
  );
}
