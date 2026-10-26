/**
 * Frontend log: a ring buffer in memory plus batched upload of warnings and
 * errors to the Manager, which writes them into manager.log (tagged frontend).
 *
 * Nothing secret leaves the page: proxy credentials in URLs, and values after
 * password / token / key / cookie markers, are masked before an entry is kept.
 * Upload failures are swallowed, never logged again, so the logger cannot loop.
 */

export type LogLevel = "info" | "warn" | "error";

export interface LogEntry {
  level: LogLevel;
  message: string;
  route?: string;
  action?: string;
  detail?: string;
  at: string;
}

const BUFFER_SIZE = 200;
const FLUSH_DELAY_MS = 3000;
const MAX_BATCH = 50;
const ENDPOINT = "/api/client-logs";

const buffer: LogEntry[] = [];
let pending: LogEntry[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;

export function redact(text: string): string {
  return text
    .replace(/([a-z][a-z0-9+.-]*:\/\/)[^\s/@:]+:[^\s/@]+@/gi, "$1***:***@")
    .replace(/((?:password|passwd|pwd|token|secret|api[_-]?key|authorization|cookie)["']?\s*[:=]\s*["']?)[^\s"',;&]+/gi, "$1***");
}

function currentRoute(): string | undefined {
  return typeof window === "undefined" ? undefined : window.location.pathname;
}

function stringify(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (value instanceof Error) return value.stack || `${value.name}: ${value.message}`;
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function clip(text: string | undefined, max: number): string | undefined {
  if (text === undefined) return undefined;
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function record(level: LogLevel, message: string, context: { action?: string; detail?: unknown } = {}) {
  const entry: LogEntry = {
    level,
    message: clip(redact(message), 2000) ?? "",
    route: currentRoute(),
    action: clip(context.action, 200),
    detail: clip(redact(stringify(context.detail) ?? ""), 4000) || undefined,
    at: new Date().toISOString(),
  };
  buffer.push(entry);
  if (buffer.length > BUFFER_SIZE) buffer.shift();
  if (level !== "info") {
    pending.push(entry);
    scheduleFlush();
  }
  return entry;
}

function scheduleFlush() {
  if (pending.length >= MAX_BATCH) {
    void flush();
    return;
  }
  if (flushTimer === null) flushTimer = setTimeout(() => void flush(), FLUSH_DELAY_MS);
}

export async function flush(): Promise<void> {
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (pending.length === 0) return;
  const entries = pending.slice(0, MAX_BATCH);
  pending = pending.slice(MAX_BATCH);
  try {
    // Plain fetch, not the API client: a failing upload must not trigger
    // connection or auth handling, nor produce another log entry.
    await fetch(ENDPOINT, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entries }),
      keepalive: true,
    });
  } catch {
    // Dropped on purpose; the entries stay in the in-memory buffer.
  }
  if (pending.length) scheduleFlush();
}

export const log = {
  info: (message: string, context?: { action?: string; detail?: unknown }) => record("info", message, context),
  warn: (message: string, context?: { action?: string; detail?: unknown }) => record("warn", message, context),
  error: (message: string, context?: { action?: string; detail?: unknown }) => record("error", message, context),
  /** Most recent entries, newest last. */
  recent: (): readonly LogEntry[] => buffer.slice(),
};

let installed = false;

/** Capture uncaught errors and rejected promises once per page. */
export function installGlobalErrorLogging(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("error", (event) => {
    log.error(event.message || "未捕获的错误", { action: "window.error", detail: event.error ?? `${event.filename}:${event.lineno}` });
  });
  window.addEventListener("unhandledrejection", (event) => {
    log.error("未处理的 Promise 拒绝", { action: "unhandledrejection", detail: event.reason });
  });
  window.addEventListener("pagehide", () => void flush());
}

/** Test hook: forget everything. */
export function resetLogForTests(): void {
  buffer.length = 0;
  pending = [];
  if (flushTimer !== null) clearTimeout(flushTimer);
  flushTimer = null;
}
