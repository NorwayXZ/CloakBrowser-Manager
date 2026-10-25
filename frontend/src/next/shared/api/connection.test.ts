import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { request } from "./client";
import { getConnectionState, onReconnect, resetConnectionForTests } from "./connection";

beforeEach(() => {
  resetConnectionForTests();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("goes to reconnecting on a network failure and back once the server answers", async () => {
  let up = false;
  const fetchMock = vi.fn(async () => {
    if (!up) throw new TypeError("Failed to fetch");
    return new Response("{}");
  });
  vi.stubGlobal("fetch", fetchMock);
  const reconnected = vi.fn();
  const off = onReconnect(reconnected);

  await request("/api/profiles").catch(() => undefined);
  expect(getConnectionState()).toBe("reconnecting");

  await vi.advanceTimersByTimeAsync(1000); // first probe, still down
  expect(getConnectionState()).toBe("reconnecting");
  const probesSoFar = fetchMock.mock.calls.length;

  await vi.advanceTimersByTimeAsync(1500); // backoff is now 2 s: no probe yet
  expect(fetchMock.mock.calls.length).toBe(probesSoFar);

  up = true;
  await vi.advanceTimersByTimeAsync(600);
  expect(getConnectionState()).toBe("online");
  expect(reconnected).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls.at(-1)?.[0]).toBe("/api/status");
  off();
});

it("any successful request ends an outage at once", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
  await request("/api/x").catch(() => undefined);
  expect(getConnectionState()).toBe("reconnecting");
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}")));
  await request("/api/x");
  expect(getConnectionState()).toBe("online");
});
