import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Profile } from "../profiles/types";
import { randomFingerprintSeed } from "./deviceProfiles";
import {
  applyProxyGeo,
  buildPayload,
  changeDevice,
  changeEngine,
  GPU_PRESETS,
  initialState,
  parseProxy,
  proxyFromParts,
  randomizeDevice,
  startupUrlsFromText,
  withExtensionPaths,
  type EditableEngine,
  type EditorState,
  type ProxyKind,
  type ProxyParts,
} from "./model";
import type { EditorForm, FingerprintOptions, HostOS, ProxyTestResult } from "./types";

const DRAFT_PREFIX = "cbm.editor-draft.";

interface StoredDraft {
  at: string;
  state: EditorState;
}

/**
 * Unsaved edits survive a reload (e.g. the macOS panel's web process being
 * restarted). sessionStorage, not localStorage: the draft can hold proxy
 * passwords and cookies, and must not outlive the window on disk.
 */
function draftKey(profileId: string | null) {
  return `${DRAFT_PREFIX}${profileId ?? "new"}`;
}

export function readDraft(profileId: string | null): StoredDraft | null {
  try {
    const raw = window.sessionStorage.getItem(draftKey(profileId));
    return raw ? (JSON.parse(raw) as StoredDraft) : null;
  } catch {
    return null;
  }
}

function writeDraft(profileId: string | null, state: EditorState | null) {
  try {
    if (state) window.sessionStorage.setItem(draftKey(profileId), JSON.stringify({ at: new Date().toISOString(), state }));
    else window.sessionStorage.removeItem(draftKey(profileId));
  } catch {
    // Storage blocked: the draft is simply not kept.
  }
}

/** Editor state and every field rule, mirroring the current panel's editor. */
export function useEditor(profile: Profile | null, hostOS: HostOS | null) {
  const profileId = profile?.id ?? null;
  // Computed once: the page remounts the editor (key) for another profile.
  const [initial] = useState(() => initialState(profile, hostOS));
  const [state, setState] = useState<EditorState>(initial);
  const [proxyTest, setProxyTest] = useState<ProxyTestResult | null>(null);
  const [proxyTestError, setProxyTestError] = useState<string | null>(null);
  const { form, proxyParts } = state;

  const baseline = useMemo(() => JSON.stringify(buildPayload(initial.form, hostOS)), [initial, hostOS]);
  const dirty = JSON.stringify(buildPayload(form, hostOS)) !== baseline;

  // Keep the draft while there is something unsaved.
  const draftTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (draftTimer.current) clearTimeout(draftTimer.current);
    draftTimer.current = setTimeout(() => writeDraft(profileId, dirty ? state : null), 400);
    return () => {
      if (draftTimer.current) clearTimeout(draftTimer.current);
    };
  }, [dirty, profileId, state]);

  const setForm = useCallback((update: (form: EditorForm) => EditorForm) => setState((s) => ({ ...s, form: update(s.form) })), []);

  const set = useCallback(<K extends keyof EditorForm>(key: K, value: EditorForm[K]) => setForm((f) => ({ ...f, [key]: value })), [setForm]);

  const setOption = useCallback(
    <K extends keyof FingerprintOptions>(key: K, value: FingerprintOptions[K]) =>
      setForm((f) => ({ ...f, fingerprint_options: { ...(f.fingerprint_options ?? {}), [key]: value } })),
    [setForm],
  );

  const clearProxyTest = () => {
    setProxyTest(null);
    setProxyTestError(null);
  };

  const setProxyParts = (next: ProxyParts) => {
    setState((s) => ({ ...s, proxyParts: next, form: { ...s.form, proxy: proxyFromParts(next), ...(next.kind !== "custom" || next.scheme !== "socks5" ? { proxy_connection_mode: "direct", relay_id: null } : {}) } }));
    clearProxyTest();
  };

  return {
    state,
    form,
    proxyParts,
    dirty,
    proxyTest,
    proxyTestError,
    set,
    setOption,
    setRouteMode: (mode: "direct" | "relay") => {
      setForm(f => ({ ...f, proxy_connection_mode: mode, relay_id: mode === "direct" ? null : f.relay_id }));
      clearProxyTest();
    },
    setRelay: (id: string | null) => { set("relay_id", id); clearProxyTest(); },
    setForm,
    restore: (draft: EditorState) => setState(draft),
    discardDraft: () => writeDraft(profileId, null),
    payload: () => buildPayload(form, hostOS),
    changeEngine: (engine: EditableEngine) => setForm((f) => changeEngine(f, engine, hostOS)),
    changeDevice: (id: string) => setForm((f) => changeDevice(f, id, hostOS)),
    randomizeDevice: () => setForm((f) => randomizeDevice(f, hostOS)),
    randomizeSeed: () => set("fingerprint_seed", randomFingerprintSeed()),
    applyGpuPreset: (name: string) => {
      const preset = GPU_PRESETS[name];
      if (preset) setForm((f) => ({ ...f, gpu_vendor: preset.vendor, gpu_renderer: preset.renderer }));
    },
    setProxyKind: (kind: ProxyKind) => setProxyParts({ ...proxyParts, kind, raw: kind === "xray" ? proxyParts.raw : "" }),
    setProxyPart: <K extends keyof ProxyParts>(key: K, value: ProxyParts[K]) => setProxyParts({ ...proxyParts, [key]: value }),
    usePreset: (proxy: string) => {
      setState((s) => ({ ...s, proxyParts: parseProxy(proxy), form: { ...s.form, proxy, ...(!proxy.startsWith("socks5://") ? { proxy_connection_mode: "direct", relay_id: null } : {}) } }));
      clearProxyTest();
    },
    setStartupUrlsText: (text: string) => setState((s) => ({ ...s, startupUrlsText: text, form: { ...s.form, startup_urls: startupUrlsFromText(text) } })),
    setExtensionPaths: (text: string) => setForm((f) => ({ ...f, launch_args: withExtensionPaths(f.launch_args, text) })),
    addLaunchArg: (arg: string): boolean => {
      const value = arg.trim();
      if (!value || (form.launch_args ?? []).includes(value)) return false;
      setState((s) => ({ ...s, launchArgsOpen: true, form: { ...s.form, launch_args: [...(s.form.launch_args ?? []), value] } }));
      return true;
    },
    removeLaunchArg: (index: number) => setForm((f) => ({ ...f, launch_args: (f.launch_args ?? []).filter((_, i) => i !== index) })),
    setLaunchArgsOpen: (open: boolean) => setState((s) => ({ ...s, launchArgsOpen: open })),
    proxyChecked: (result: ProxyTestResult) => {
      setProxyTest(result);
      setProxyTestError(null);
      // "跟随出口 IP" applies the result at once, as the current editor does.
      if (form.geoip) setForm((f) => applyProxyGeo(f, result));
    },
    proxyCheckFailed: (message: string) => {
      setProxyTest(null);
      setProxyTestError(message);
    },
    applyProxyGeo: () => setForm((f) => applyProxyGeo(f, proxyTest)),
  };
}

export type Editor = ReturnType<typeof useEditor>;
