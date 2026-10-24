import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flush, log, redact, resetLogForTests } from "./logger";

beforeEach(() => {
  resetLogForTests();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("redact", () => {
  it("masks credentials in proxy URLs and secret values", () => {
    const out = redact("socks5://alice:pw@203.0.113.9:1080 password=hunter2 token: abc api_key='k1' cookie=sid=1");
    expect(out).toContain("socks5://***:***@203.0.113.9:1080");
    for (const secret of ["alice", "hunter2", "abc", "k1", "sid=1"]) expect(out).not.toContain(secret);
  });

  it("leaves ordinary text alone", () => {
    expect(redact("启动失败：授权并发已满 http://127.0.0.1:8080/api/status")).toBe("启动失败：授权并发已满 http://127.0.0.1:8080/api/status");
  });
});

describe("log", () => {
  it("uploads warnings and errors in one batch after a short delay, info stays local", async () => {
    const fetchMock = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    log.info("页面打开");
    log.warn("慢", { action: "load" });
    log.error("坏了", { action: "save", detail: new Error("password=x boom") });
    expect(fetchMock).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(3000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/client-logs");
    const { entries } = JSON.parse(String(init.body));
    expect(entries.map((e: { level: string }) => e.level)).toEqual(["warn", "error"]);
    expect(entries[1].detail).toContain("password=***");
    expect(entries[1].action).toBe("save");
    expect(log.recent()).toHaveLength(3);
  });

  it("clips long messages and keeps only the latest 200 entries", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}")));
    log.info("x".repeat(3000));
    expect(log.recent()[0]?.message.length).toBe(2001);
    for (let i = 0; i < 250; i += 1) log.info(`n${i}`);
    expect(log.recent()).toHaveLength(200);
    expect(log.recent().at(-1)?.message).toBe("n249");
  });

  it("swallows upload failures", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    log.error("坏了");
    await expect(flush()).resolves.toBeUndefined();
  });

  it("flushes immediately once a batch is full", () => {
    const fetchMock = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    for (let i = 0; i < 50; i += 1) log.error(`e${i}`);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
