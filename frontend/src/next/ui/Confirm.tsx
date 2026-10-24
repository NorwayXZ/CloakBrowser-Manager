import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { Button } from "./Button";
import { Dialog } from "./Overlay";

/**
 * Replaces window.confirm(): same look in WKWebView and Chrome, keyboard
 * friendly, and it can say what will happen. `await confirm({...})` resolves
 * true only when the user presses the confirm button.
 */
export interface ConfirmOptions {
  title: ReactNode;
  description?: ReactNode;
  /** What exactly will be affected, shown in the body. */
  details?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmCtx = createContext<ConfirmFn | null>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback<ConfirmFn>((next) => {
    resolver.current?.(false);
    setOptions(next);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const settle = (value: boolean) => {
    resolver.current?.(value);
    resolver.current = null;
    setOptions(null);
  };

  return (
    <ConfirmCtx.Provider value={confirm}>
      {children}
      <Dialog
        open={options !== null}
        onOpenChange={(open) => !open && settle(false)}
        title={options?.title ?? ""}
        description={options?.description}
        size="sm"
        footer={
          <>
            <Button onClick={() => settle(false)}>{options?.cancelLabel ?? "取消"}</Button>
            <Button variant={options?.danger ? "danger" : "primary"} onClick={() => settle(true)} autoFocus>
              {options?.confirmLabel ?? "确定"}
            </Button>
          </>
        }
      >
        {options?.details}
      </Dialog>
    </ConfirmCtx.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const confirm = useContext(ConfirmCtx);
  if (!confirm) throw new Error("useConfirm needs <ConfirmProvider>");
  return confirm;
}
