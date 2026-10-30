import type { ReactNode } from "react";
import { cn } from "../shared/lib/cn";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="text-xl font-bold tracking-tight text-fg">{title}</h1>
        {description && <p className="mt-1 text-sm text-fg-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ children, className, padded = true }: { children: ReactNode; className?: string; padded?: boolean }) {
  return <div className={cn("min-w-0 rounded-md border border-border bg-surface shadow-raised", padded && "p-4", className)}>{children}</div>;
}

/** A titled block inside a page: settings groups, form sections. */
export function Section({
  title,
  description,
  actions,
  children,
  id,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  id?: string;
  className?: string;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section id={id} aria-labelledby={headingId} className={cn("min-w-0 rounded-md border border-border bg-surface shadow-raised", className)}>
      <header className="flex flex-wrap items-start justify-between gap-3 px-5 pb-1 pt-4">
        <div className="min-w-0">
          <h2 id={headingId} className="text-md font-semibold tracking-tight text-fg">
            {title}
          </h2>
          {description && <p className="mt-0.5 text-sm text-fg-2">{description}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </header>
      <div className="px-5 pb-5 pt-3">{children}</div>
    </section>
  );
}

/** Label / value rows, e.g. the profile summary. Values wrap instead of overflowing. */
export function KeyValueList({ items }: { items: { label: ReactNode; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-[minmax(88px,max-content)_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
      {items.map((item, index) => (
        <div key={index} className="contents">
          <dt className="text-fg-3">{item.label}</dt>
          <dd className="m-0 min-w-0 break-words text-fg">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
