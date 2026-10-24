import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// Lazy-loaded pages can take over a second to arrive when the whole suite runs
// in parallel; the default 1 s wait then fails at random.
configure({ asyncUtilTimeout: 3000 });

// jsdom lacks a few browser APIs that Radix primitives and the shell use.
// Only fill what is missing, so the current panel's tests see no change.

if (typeof window !== "undefined") {
  if (!window.matchMedia) {
    window.matchMedia = (query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        addListener: () => undefined,
        removeListener: () => undefined,
        dispatchEvent: () => false,
      }) as MediaQueryList;
  }
  if (!("ResizeObserver" in window)) {
    class ResizeObserverStub {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    (window as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;
  }
  // Node 22+ ships its own localStorage global, which is undefined unless Node
  // is started with --localstorage-file and then shadows jsdom's.
  if (!window.localStorage) {
    const data = new Map<string, string>();
    const storage: Storage = {
      get length() {
        return data.size;
      },
      clear: () => data.clear(),
      getItem: (key) => data.get(key) ?? null,
      key: (index) => [...data.keys()][index] ?? null,
      removeItem: (key) => void data.delete(key),
      setItem: (key, value) => void data.set(key, String(value)),
    };
    Object.defineProperty(window, "localStorage", { value: storage, configurable: true });
  }
  const proto = window.HTMLElement.prototype as unknown as Record<string, unknown>;
  proto.hasPointerCapture ??= () => false;
  proto.releasePointerCapture ??= () => undefined;
  proto.setPointerCapture ??= () => undefined;
  proto.scrollIntoView ??= () => undefined;
}
