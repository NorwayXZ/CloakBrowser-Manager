/**
 * Display preferences (theme, sidebar). The backend settings table is the
 * source of truth; localStorage only caches the last values so the first
 * frame already has the right theme. Changes apply at once and are rolled
 * back with an error toast if the save fails.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { isApiError, request } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";
import { log } from "../../shared/log/logger";
import { useToast } from "../../ui";

export type UiPreferences = components["schemas"]["UiPreferencesModel"];
export type ThemePreference = UiPreferences["theme"];
export type InterfacePreference = UiPreferences["interface"];
export type ResolvedTheme = "light" | "dark";

const KEY = ["settings", "ui"] as const;
const THEME_CACHE = "cbm.theme";
const SIDEBAR_CACHE = "cbm.sidebar";

function readCache(): Required<UiPreferences> {
  const fallback = { theme: "system" as ThemePreference, sidebar_collapsed: false, interface: "new" as InterfacePreference };
  try {
    const theme = window.localStorage.getItem(THEME_CACHE);
    return {
      theme: theme === "light" || theme === "dark" || theme === "system" ? theme : fallback.theme,
      sidebar_collapsed: window.localStorage.getItem(SIDEBAR_CACHE) === "1",
      interface: fallback.interface,
    };
  } catch {
    return fallback;
  }
}

function writeCache(prefs: Pick<Required<UiPreferences>, "theme" | "sidebar_collapsed">) {
  try {
    window.localStorage.setItem(THEME_CACHE, prefs.theme);
    window.localStorage.setItem(SIDEBAR_CACHE, prefs.sidebar_collapsed ? "1" : "0");
  } catch {
    // Storage blocked: the backend still has the value.
  }
}

declare global {
  interface Window {
    /** Present in the macOS app's WKWebView, where the window follows the panel's theme. */
    webkit?: { messageHandlers?: Record<string, { postMessage(message: unknown): void } | undefined> };
  }
}

/** Tell the macOS app window which theme was chosen, so its own background and title bar match. */
function reportThemeToWindow(theme: ThemePreference, resolved: ResolvedTheme) {
  try {
    window.webkit?.messageHandlers?.cbmTheme?.postMessage({ theme, resolved });
  } catch {
    // Not in the app window, or the bridge is gone: the panel works without it.
  }
}

const DARK_QUERY = "(prefers-color-scheme: dark)";

function subscribeSystemTheme(listener: () => void) {
  const media = window.matchMedia(DARK_QUERY);
  media.addEventListener("change", listener);
  return () => media.removeEventListener("change", listener);
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

export function useSystemTheme(): ResolvedTheme {
  return useSyncExternalStore(subscribeSystemTheme, systemTheme, () => "light");
}

interface PreferencesValue {
  theme: ThemePreference;
  resolvedTheme: ResolvedTheme;
  sidebarCollapsed: boolean;
  setTheme: (theme: ThemePreference) => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  /** Which panel "/" opens next time. Resolves once the Manager has stored it. */
  setInterface: (next: InterfacePreference) => Promise<void>;
  saving: boolean;
  /** The running Manager predates this panel: it has no /api/settings/ui. */
  backendOutdated: boolean;
}

const PreferencesCtx = createContext<PreferencesValue | null>(null);

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [initial] = useState(readCache);
  const query = useQuery({
    queryKey: KEY,
    queryFn: () => request<UiPreferences>("/api/settings/ui"),
    staleTime: Infinity,
    placeholderData: initial,
  });
  const prefs: Required<UiPreferences> = {
    theme: query.data?.theme ?? initial.theme,
    sidebar_collapsed: query.data?.sidebar_collapsed ?? initial.sidebar_collapsed,
    // Carried through every save so a theme change cannot undo the choice of panel.
    interface: query.data?.interface ?? initial.interface,
  };

  const mutation = useMutation({
    mutationFn: (next: Required<UiPreferences>) => request<UiPreferences>("/api/settings/ui", { method: "PUT", body: next }),
    onMutate: async (next) => {
      await queryClient.cancelQueries({ queryKey: KEY });
      const previous = queryClient.getQueryData<UiPreferences>(KEY);
      queryClient.setQueryData(KEY, next);
      return { previous };
    },
    onError: (error, _next, context) => {
      queryClient.setQueryData(KEY, context?.previous);
      log.warn("保存界面偏好失败", { action: "settings.ui.save", detail: error });
      toast.show({ tone: "error", title: "界面偏好没有保存", description: error instanceof Error ? error.message : String(error) });
    },
  });

  const { mutate } = mutation;
  const { theme, sidebar_collapsed: sidebarCollapsed, interface: interfaceChoice } = prefs;
  const update = useCallback(
    (patch: Partial<UiPreferences>) => mutate({ theme, sidebar_collapsed: sidebarCollapsed, interface: interfaceChoice, ...patch } as Required<UiPreferences>),
    [mutate, theme, sidebarCollapsed, interfaceChoice],
  );
  const { mutateAsync } = mutation;
  const setInterface = useCallback(
    async (next: InterfacePreference) => {
      await mutateAsync({ theme, sidebar_collapsed: sidebarCollapsed, interface: next });
    },
    [mutateAsync, theme, sidebarCollapsed],
  );

  const system = useSystemTheme();
  const resolvedTheme: ResolvedTheme = theme === "system" ? system : theme;

  useEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme;
  }, [resolvedTheme]);

  useEffect(() => {
    writeCache({ theme, sidebar_collapsed: sidebarCollapsed });
  }, [theme, sidebarCollapsed]);

  useEffect(() => reportThemeToWindow(theme, resolvedTheme), [theme, resolvedTheme]);

  const saving = mutation.isPending;
  const backendOutdated = query.isError && isApiError(query.error) && query.error.status === 404;
  const value = useMemo<PreferencesValue>(
    () => ({
      theme,
      resolvedTheme,
      sidebarCollapsed,
      setTheme: (next) => update({ theme: next }),
      setSidebarCollapsed: (next) => update({ sidebar_collapsed: next }),
      setInterface,
      saving,
      backendOutdated,
    }),
    [theme, sidebarCollapsed, resolvedTheme, update, setInterface, saving, backendOutdated],
  );

  return <PreferencesCtx.Provider value={value}>{children}</PreferencesCtx.Provider>;
}

export function usePreferences(): PreferencesValue {
  const value = useContext(PreferencesCtx);
  if (!value) throw new Error("usePreferences needs <PreferencesProvider>");
  return value;
}

export const THEME_OPTIONS: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "跟随系统" },
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
];
