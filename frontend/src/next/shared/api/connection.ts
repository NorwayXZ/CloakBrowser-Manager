/**
 * Is the Manager reachable? Any request that fails at the network level flips
 * this to "reconnecting"; we then probe /api/status with backoff (1 s → 15 s)
 * until it answers, and tell subscribers so they can refetch.
 */
import { useSyncExternalStore } from "react";
import { onNetworkState } from "./client";

export type ConnectionState = "online" | "reconnecting";

const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000];
const PROBE_PATH = "/api/status";

let state: ConnectionState = "online";
let attempt = 0;
let probeTimer: ReturnType<typeof setTimeout> | null = null;
const listeners = new Set<() => void>();
const reconnectListeners = new Set<() => void>();

function set(next: ConnectionState) {
  if (next === state) return;
  const recovered = state === "reconnecting" && next === "online";
  state = next;
  listeners.forEach((listener) => listener());
  if (recovered) reconnectListeners.forEach((listener) => listener());
}

function scheduleProbe() {
  if (probeTimer !== null) return;
  const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] ?? 15000;
  probeTimer = setTimeout(async () => {
    probeTimer = null;
    attempt += 1;
    try {
      // Any HTTP answer means the server is back, even an error status.
      await fetch(PROBE_PATH, { credentials: "same-origin" });
      markOnline();
      return;
    } catch {
      // still down
    }
    scheduleProbe();
  }, delay);
}

function markOnline() {
  attempt = 0;
  if (probeTimer !== null) {
    clearTimeout(probeTimer);
    probeTimer = null;
  }
  set("online");
}

function markOffline() {
  set("reconnecting");
  scheduleProbe();
}

onNetworkState((ok) => (ok ? markOnline() : markOffline()));

export function getConnectionState(): ConnectionState {
  return state;
}

export function subscribeConnection(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Runs after the Manager answers again following an outage. */
export function onReconnect(listener: () => void): () => void {
  reconnectListeners.add(listener);
  return () => reconnectListeners.delete(listener);
}

export function useConnectionState(): ConnectionState {
  return useSyncExternalStore(subscribeConnection, getConnectionState, getConnectionState);
}

/** Test hook. */
export function resetConnectionForTests(): void {
  attempt = 0;
  if (probeTimer !== null) clearTimeout(probeTimer);
  probeTimer = null;
  state = "online";
}
