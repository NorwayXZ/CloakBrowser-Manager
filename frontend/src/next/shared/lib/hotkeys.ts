import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";

export const IS_MAC = typeof navigator !== "undefined" && /mac/i.test(`${navigator.platform} ${navigator.userAgent}`);

/** "mod+1" → "⌘1" on macOS, "Ctrl+1" elsewhere. */
export function formatShortcut(combo: string): string {
  return combo
    .split("+")
    .map((part) => {
      if (part === "mod") return IS_MAC ? "⌘" : "Ctrl+";
      if (part === "shift") return IS_MAC ? "⇧" : "Shift+";
      if (part === "enter") return IS_MAC ? "↩" : "Enter";
      if (part === "esc") return "Esc";
      return part.length === 1 ? part.toUpperCase() : part;
    })
    .join("");
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

export function matchesCombo(event: KeyboardEvent, combo: string): boolean {
  const parts = combo.split("+");
  const key = parts[parts.length - 1] ?? "";
  const wantMod = parts.includes("mod");
  const wantShift = parts.includes("shift");
  const mod = IS_MAC ? event.metaKey : event.ctrlKey;
  if (wantMod !== mod) return false;
  // "?" is shift+/ on most layouts: compare the produced character, ignore shift.
  if (key.length === 1 && !/[a-z0-9]/i.test(key)) return event.key === key;
  if (wantShift !== event.shiftKey) return false;
  return event.key.toLowerCase() === key.toLowerCase();
}

export interface Hotkey {
  combo: string;
  handler: (event: KeyboardEvent) => void;
  /** Also fire while focus is in a text field. Default: only for mod combos. */
  whileTyping?: boolean;
}

export function useHotkeys(hotkeys: Hotkey[]): void {
  const ref = useRef(hotkeys);
  ref.current = hotkeys;
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing) return;
      for (const hotkey of ref.current) {
        if (!matchesCombo(event, hotkey.combo)) continue;
        const typingAllowed = hotkey.whileTyping ?? hotkey.combo.includes("mod");
        if (!typingAllowed && isTyping(event.target)) continue;
        event.preventDefault();
        hotkey.handler(event);
        return;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}

export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (listener: () => void) => {
      const media = window.matchMedia(query);
      media.addEventListener("change", listener);
      return () => media.removeEventListener("change", listener);
    },
    [query],
  );
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => false);
}
