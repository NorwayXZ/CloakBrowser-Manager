import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, detailMessage, onNetworkState, onUnauthorized, request } from "./client";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function respond(status: number, body: unknown, statusText = "") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(typeof body === "string" ? body : JSON.stringify(body), { status, statusText })),
  );
}

describe("request", () => {
  it("returns parsed JSON and sends a JSON body", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    await expect(request("/api/x", { method: "PUT", body: { theme: "dark" } })).resolves.toEqual({ ok: true });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.method).toBe("PUT");
    expect(init.body).toBe('{"theme":"dark"}');
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
  });

  it("sends a file as it is, with its own type", async () => {
    const fetchMock = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    const file = new Blob(["PK"], { type: "application/zip" });
    await request("/api/backups/restore-upload", { method: "POST", body: file });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.body).toBe(file);
    expect(init.headers).toEqual({ "Content-Type": "application/zip" });
  });

  it("returns null for an empty body", async () => {
    respond(200, "");
    await expect(request("/api/x")).resolves.toBeNull();
  });

  it("turns an HTTP error into ApiError with the backend detail", async () => {
    respond(409, { detail: "请先关闭所有浏览器" });
    const error = await request("/api/backups").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ kind: "http", status: 409, message: "请先关闭所有浏览器", detail: "请先关闭所有浏览器" });
    expect(error.retryable).toBe(false);
  });

  it("joins FastAPI validation messages", async () => {
    respond(422, { detail: [{ msg: "端口无效" }, { msg: "名称不能为空" }] });
    await expect(request("/api/x")).rejects.toMatchObject({ message: "端口无效；名称不能为空", status: 422 });
  });

  it("falls back to the status text when the body is not JSON", async () => {
    respond(502, "<html>bad gateway</html>", "Bad Gateway");
    const error = await request("/api/x").catch((e) => e);
    expect(error.message).toBe("Bad Gateway");
    expect(error.retryable).toBe(true);
  });

  it("reports a network failure and marks it retryable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const states: boolean[] = [];
    const off = onNetworkState((ok) => states.push(ok));
    const error = await request("/api/x").catch((e) => e);
    off();
    expect(error).toMatchObject({ kind: "network", message: "连接不到 Manager 服务" });
    expect(error.retryable).toBe(true);
    expect(states).toEqual([false]);
  });

  it("times out", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      })),
    );
    const pending = request("/api/x", { timeoutMs: 1000 }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(1001);
    expect(await pending).toMatchObject({ kind: "timeout" });
  });

  it("lets a caller's abort through untouched", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      })),
    );
    const controller = new AbortController();
    const pending = request("/api/x", { signal: controller.signal }).catch((e) => e);
    controller.abort();
    const error = await pending;
    expect(error).not.toBeInstanceOf(ApiError);
    expect(error.name).toBe("AbortError");
  });

  it("notifies on 401", async () => {
    respond(401, { detail: "Unauthorized" });
    const listener = vi.fn();
    const off = onUnauthorized(listener);
    await request("/api/x").catch(() => undefined);
    off();
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("detailMessage", () => {
  it("reads strings, validation lists and message objects", () => {
    expect(detailMessage("x", "f")).toBe("x");
    expect(detailMessage([{ msg: "a" }], "f")).toBe("a");
    expect(detailMessage({ message: "m" }, "f")).toBe("m");
    expect(detailMessage(null, "f")).toBe("f");
    expect(detailMessage([], "f")).toBe("f");
  });
});
