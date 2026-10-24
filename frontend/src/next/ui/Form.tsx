import * as RadixCheckbox from "@radix-ui/react-checkbox";
import * as RadixSwitch from "@radix-ui/react-switch";
import { Check, ChevronDown, Minus } from "lucide-react";
import {
  createContext,
  forwardRef,
  useContext,
  useId,
  useState,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "../shared/lib/cn";

/**
 * FormField gives its control an id, a label, a description and an error, and
 * wires aria-describedby / aria-invalid through context, so every control in
 * the panel is labelled the same way.
 */
interface FieldContext {
  id: string;
  describedBy: string | undefined;
  invalid: boolean;
}

const FieldCtx = createContext<FieldContext | null>(null);

function useField(id?: string, invalid?: boolean, describedBy?: string) {
  const field = useContext(FieldCtx);
  return {
    id: id ?? field?.id,
    "aria-invalid": invalid ?? field?.invalid ? true : undefined,
    "aria-describedby": describedBy ?? field?.describedBy,
  };
}

export function FormField({
  label,
  description,
  error,
  required,
  children,
  className,
}: {
  label: ReactNode;
  description?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const id = useId();
  const descId = description ? `${id}-desc` : undefined;
  const errId = error ? `${id}-err` : undefined;
  const describedBy = [errId, descId].filter(Boolean).join(" ") || undefined;
  return (
    <FieldCtx.Provider value={{ id, describedBy, invalid: Boolean(error) }}>
      <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
        <label htmlFor={id} className="text-sm font-medium text-fg">
          {label}
          {required && <span className="ml-0.5 text-danger" aria-hidden>*</span>}
        </label>
        {children}
        {error && (
          <p id={errId} className="text-xs text-danger" role="alert">
            {error}
          </p>
        )}
        {description && (
          <p id={descId} className="text-xs text-fg-3">
            {description}
          </p>
        )}
      </div>
    </FieldCtx.Provider>
  );
}

const control =
  "w-full min-w-0 rounded border border-border-strong bg-surface text-sm text-fg placeholder:text-fg-3 " +
  "transition-colors duration-fast hover:border-fg-3 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25 " +
  "disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-fg-3 " +
  "aria-[invalid=true]:border-danger aria-[invalid=true]:focus:ring-danger/25";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { mono?: boolean }>(
  function Input({ className, id, mono, "aria-invalid": invalid, "aria-describedby": describedBy, ...rest }, ref) {
    const field = useField(id, invalid === true || invalid === "true" ? true : undefined, describedBy);
    return <input ref={ref} {...field} className={cn(control, "h-8 px-2.5", mono && "font-mono", className)} {...rest} />;
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { mono?: boolean }>(
  function Textarea({ className, id, mono, rows = 4, "aria-invalid": invalid, "aria-describedby": describedBy, ...rest }, ref) {
    const field = useField(id, invalid === true || invalid === "true" ? true : undefined, describedBy);
    return (
      <textarea
        ref={ref}
        rows={rows}
        {...field}
        className={cn(control, "px-2.5 py-1.5 leading-5", mono && "font-mono", className)}
        {...rest}
      />
    );
  },
);

/** Native select: keyboard, type-ahead and screen readers work everywhere, including WKWebView. */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, id, children, "aria-invalid": invalid, "aria-describedby": describedBy, ...rest },
  ref,
) {
  const field = useField(id, invalid === true || invalid === "true" ? true : undefined, describedBy);
  return (
    <div className={cn("relative min-w-0", className)}>
      <select ref={ref} {...field} className={cn(control, "h-8 cursor-pointer appearance-none pl-2.5 pr-8")} {...rest}>
        {children}
      </select>
      <ChevronDown aria-hidden className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-3" />
    </div>
  );
});

export function Checkbox({
  checked,
  onCheckedChange,
  label,
  description,
  disabled,
  id,
  "aria-label": ariaLabel,
}: {
  checked: boolean | "indeterminate";
  onCheckedChange: (checked: boolean) => void;
  label?: ReactNode;
  /** Shown under the label and read as the box's description. */
  description?: ReactNode;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
}) {
  const autoId = useId();
  const boxId = id ?? autoId;
  // Inside a <form>, Radix adds a hidden absolutely positioned native input next
  // to the box; the relative wrapper keeps it from stretching the document.
  const box = (
    <span className="relative inline-flex">
    <RadixCheckbox.Root
      id={boxId}
      checked={checked}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-describedby={description ? `${boxId}-desc` : undefined}
      onCheckedChange={(value) => onCheckedChange(value === true)}
      className={cn(
        "flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border border-border-strong bg-surface text-accent-on",
        "transition-colors duration-fast hover:border-fg-3 disabled:cursor-not-allowed disabled:opacity-50",
        "data-[state=checked]:border-accent data-[state=checked]:bg-accent",
        "data-[state=indeterminate]:border-accent data-[state=indeterminate]:bg-accent",
      )}
    >
      <RadixCheckbox.Indicator>
        {checked === "indeterminate" ? <Minus className="h-3 w-3" strokeWidth={3} /> : <Check className="h-3 w-3" strokeWidth={3} />}
      </RadixCheckbox.Indicator>
    </RadixCheckbox.Root>
    </span>
  );
  if (!label) return box;
  if (description) {
    return (
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5">{box}</span>
        <div className="min-w-0">
          <label htmlFor={boxId} className={cn("text-sm font-medium text-fg", disabled && "text-fg-3")}>
            {label}
          </label>
          <div id={`${boxId}-desc`} className="mt-0.5 text-xs text-fg-3">
            {description}
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2">
      {box}
      <label htmlFor={boxId} className={cn("text-sm text-fg", disabled && "text-fg-3")}>
        {label}
      </label>
    </div>
  );
}

/**
 * A few mutually exclusive choices shown side by side (a radio group).
 * Arrow keys move the choice, as with native radio buttons.
 */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  className,
}: {
  label: string;
  value: T;
  options: [T, ReactNode][];
  onChange: (value: T) => void;
  className?: string;
}) {
  const move = (delta: number, from: HTMLElement) => {
    const index = options.findIndex(([option]) => option === value);
    const next = options[(index + delta + options.length) % options.length];
    if (!next) return;
    onChange(next[0]);
    const buttons = from.parentElement?.querySelectorAll<HTMLButtonElement>("[role=radio]");
    buttons?.[(index + delta + options.length) % options.length]?.focus();
  };
  return (
    <div role="radiogroup" aria-label={label} className={cn("inline-flex max-w-full flex-wrap rounded border border-border-strong bg-surface-2 p-0.5", className)}>
      {options.map(([option, text]) => {
        const checked = value === option;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            onClick={() => onChange(option)}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight" || event.key === "ArrowDown") {
                event.preventDefault();
                move(1, event.currentTarget);
              } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
                event.preventDefault();
                move(-1, event.currentTarget);
              }
            }}
            className={cn(
              "h-7 rounded-sm px-3 text-sm transition-colors duration-fast",
              checked ? "bg-surface font-medium text-accent shadow-raised" : "text-fg-2 hover:text-fg",
            )}
          >
            {text}
          </button>
        );
      })}
    </div>
  );
}

/** Long help text folded to one line, with 展开 / 收起. */
export function Hint({ children, lines = 1 }: { children: string; lines?: 1 | 2 }) {
  const [open, setOpen] = useState(false);
  const long = children.length > (lines === 1 ? 56 : 112);
  return (
    <span className="block">
      <span className={cn(!open && long && (lines === 1 ? "line-clamp-1" : "line-clamp-2"))}>{children}</span>
      {long && (
        <button type="button" className="text-accent hover:underline" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? "收起" : "展开"}
        </button>
      )}
    </span>
  );
}

export function Switch({
  checked,
  onCheckedChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <label htmlFor={id} className={cn("text-sm font-medium text-fg", disabled && "text-fg-3")}>
          {label}
        </label>
        {description && (
          <p id={`${id}-desc`} className="mt-0.5 text-xs text-fg-3">
            {description}
          </p>
        )}
      </div>
      <span className="relative inline-flex shrink-0">
      <RadixSwitch.Root
        id={id}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onCheckedChange}
        aria-describedby={description ? `${id}-desc` : undefined}
        className={cn(
          "relative mt-0.5 h-5 w-9 shrink-0 rounded-full bg-border-strong transition-colors duration-fast",
          "data-[state=checked]:bg-accent disabled:cursor-not-allowed disabled:opacity-50",
        )}
      >
        <RadixSwitch.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-surface shadow-raised transition-transform duration-fast data-[state=checked]:translate-x-[18px]" />
      </RadixSwitch.Root>
      </span>
    </div>
  );
}
