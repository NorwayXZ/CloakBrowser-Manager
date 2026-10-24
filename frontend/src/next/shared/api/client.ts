/**
 * The one way the redesigned panel talks to the Manager.
 *
 * Every failure becomes an ApiError with a `kind`, so callers and the query
 * layer can tell "the server said no" (http) from "the server is gone"
 * (network / timeout). Network failures are reported to the connection
 * monitor; 401 to the unauthorized handler.
 */

export type ApiErrorKind = "http" | "network" | "timeout";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  /** The backend's `detail` as sent (string, validation list, or object). */
  readonly detail: unknown;

  constructor(kind: ApiErrorKind, message: string, status: number | null = null, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }

  /** Worth retrying automatically: the request may succeed unchanged. */
  get retryable(): boolean {
    return this.kind !== "http" || (this.status !== null && this.status >= 500);
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

type Listener = () => void;
const unauthorizedListeners = new Set<Listener>();
const networkListeners = new Set<(ok: boolean) => void>();

export function onUnauthorized(listener: Listener): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

/** Called with false on a network failure and true on any answer from the server. */
export function onNetworkState(listener: (ok: boolean) => void): () => void {
  networkListeners.add(listener);
  return () => networkListeners.delete(listener);
}

function emitNetwork(ok: boolean) {
  networkListeners.forEach((listener) => listener(ok));
}

/** Turn FastAPI's `detail` into one readable sentence. */
export function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => (item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : null))
      .filter((part): part is string => Boolean(part));
    if (parts.length) return parts.join("；");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message: unknown }).message;
    if (typeof message === "string" && message) return message;
  }
  return fallback;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /** Default 15 s. Long jobs (backup, update) start a job and poll instead of waiting here. */
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 15_000;

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const abortFromCaller = () => controller.abort();
  signal?.addEventListener("abort", abortFromCaller);

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    if (signal?.aborted && !timedOut) throw error;
    emitNetwork(false);
    throw timedOut
      ? new ApiError("timeout", "Manager 没有及时响应，请稍后再试")
      : new ApiError("network", "连接不到 Manager 服务");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abortFromCaller);
  }

  emitNetwork(true);

  if (response.status === 401) {
    unauthorizedListeners.forEach((listener) => listener());
  }

  const text = await response.text();
  let data: unknown = null;
  let isJson = false;
  if (text) {
    try {
      data = JSON.parse(text);
      isJson = true;
    } catch {
      data = text;
    }
  }

  if (!response.ok) {
    const detail = isJson && data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : data;
    const fallback = response.statusText || `请求失败（${response.status}）`;
    // A non-JSON body (a proxy's HTML error page) is kept in detail but never shown as the message.
    throw new ApiError("http", isJson ? detailMessage(detail, fallback) : fallback, response.status, detail);
  }
  return data as T;
}
