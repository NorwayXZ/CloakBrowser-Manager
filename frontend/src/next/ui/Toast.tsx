import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "../shared/lib/cn";

export type ToastTone = "success" | "error" | "info";

export interface ToastInput {
  tone?: ToastTone;
  title: ReactNode;
  description?: ReactNode;
  action?: { label: string; onClick: () => void };
  /** ms; errors stay longer by default so there is time to read the reason. */
  duration?: number;
}

interface ToastItem extends ToastInput {
  id: number;
}

interface ToastApi {
  show: (toast: ToastInput) => number;
  dismiss: (id: number) => void;
}

const ToastCtx = createContext<ToastApi | null>(null);
const MAX_VISIBLE = 4;

const ICONS = { success: CheckCircle2, error: XCircle, info: Info };
const ICON_TONE = { success: "text-success", error: "text-danger", info: "text-info" };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setItems((list) => list.filter((item) => item.id !== id)), []);
  const show = useCallback((toast: ToastInput) => {
    const id = nextId.current++;
    setItems((list) => [...list, { ...toast, id }].slice(-MAX_VISIBLE));
    return id;
  }, []);
  const api = useMemo(() => ({ show, dismiss }), [show, dismiss]);

  return (
    <ToastCtx.Provider value={api}>
      {children}
      {/* Two live regions: errors interrupt the screen reader, the rest wait their turn. */}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 max-w-[calc(100vw-32px)] flex-col gap-2">
        <div aria-live="polite" role="status" className="flex flex-col gap-2">
          {items.filter((t) => t.tone !== "error").map((t) => <ToastCard key={t.id} toast={t} onDismiss={dismiss} />)}
        </div>
        <div aria-live="assertive" role="alert" className="flex flex-col gap-2">
          {items.filter((t) => t.tone === "error").map((t) => <ToastCard key={t.id} toast={t} onDismiss={dismiss} />)}
        </div>
      </div>
    </ToastCtx.Provider>
  );
}

function ToastCard({ toast, onDismiss }: { toast: ToastItem; onDismiss: (id: number) => void }) {
  const tone = toast.tone ?? "info";
  const duration = toast.duration ?? (tone === "error" ? 8000 : 4000);
  const [paused, setPaused] = useState(false);
  const Icon = ICONS[tone];

  useEffect(() => {
    if (paused || duration <= 0) return;
    const timer = window.setTimeout(() => onDismiss(toast.id), duration);
    return () => window.clearTimeout(timer);
  }, [duration, onDismiss, paused, toast.id]);

  return (
    <div
      className="pointer-events-auto flex items-start gap-2.5 glass-strong rounded-md p-3.5 animate-[cbm-pop-in_160ms_ease-out]"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", ICON_TONE[tone])} aria-hidden />
      <div className="min-w-0 flex-1 break-words">
        <div className="text-sm font-medium text-fg">{toast.title}</div>
        {toast.description && <div className="mt-0.5 text-sm text-fg-2">{toast.description}</div>}
        {toast.action && (
          <button
            type="button"
            className="mt-1.5 text-sm font-medium text-accent hover:underline"
            onClick={() => {
              toast.action?.onClick();
              onDismiss(toast.id);
            }}
          >
            {toast.action.label}
          </button>
        )}
      </div>
      <button
        type="button"
        aria-label="关闭提示"
        className="-m-1 rounded p-1 text-fg-3 hover:bg-surface-2 hover:text-fg"
        onClick={() => onDismiss(toast.id)}
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}

export function useToast(): ToastApi {
  const api = useContext(ToastCtx);
  if (!api) throw new Error("useToast needs <ToastProvider>");
  return api;
}
