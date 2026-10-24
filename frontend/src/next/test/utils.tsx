import { QueryClient } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import axe from "axe-core";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { expect, vi } from "vitest";
import { AppProviders } from "../app/providers";
import { routes } from "../app/router";

export interface MockRoute {
  method?: string;
  path: string | RegExp;
  /** Response body, or a function of the parsed request body. */
  respond: unknown | ((body: unknown) => unknown);
  status?: number;
}

/**
 * Replace fetch with a small router. Unmatched requests answer 404 so a test
 * never hangs on a call it did not expect. Returns the spy for assertions.
 */
export function mockFetch(routesList: MockRoute[]) {
  const spy = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    const route = routesList.find(
      (r) => (r.method ?? "GET").toUpperCase() === method && (typeof r.path === "string" ? r.path === url : r.path.test(url)),
    );
    if (!route) return new Response(JSON.stringify({ detail: "Not found" }), { status: 404 });
    // Only JSON bodies are parsed; uploads (a File) reach the route as they are.
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : init?.body;
    const payload = typeof route.respond === "function" ? (route.respond as (b: unknown) => unknown)(body) : route.respond;
    return new Response(payload === undefined ? "" : JSON.stringify(payload), {
      status: route.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

export const STATUS = {
  running_count: 2,
  app_version: "0.7.2",
  binary_version: "145.0.7632.159.1",
  profiles_total: 6,
  host_os: "macos",
  runtime_mode: "native",
  viewer_mode: "native-window",
  host_screen: [2560, 1440],
};

/** Baseline answers every shell screen needs. */
export function shellRoutes(overrides: MockRoute[] = []): MockRoute[] {
  return [
    ...overrides,
    { path: "/api/auth/status", respond: { auth_required: false, authenticated: false, username: null } },
    { path: "/api/status", respond: STATUS },
    { path: "/api/automation/status", respond: { active: false } },
    { path: "/api/settings/ui", respond: { theme: "system", sidebar_collapsed: false } },
    { method: "PUT", path: "/api/settings/ui", respond: (body: unknown) => body },
    { path: "/api/profiles", respond: [] },
    { method: "POST", path: "/api/client-logs", respond: { accepted: 1, dropped: 0 } },
  ];
}

export function testQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } } });
}

export function renderWithProviders(ui: ReactElement, client = testQueryClient()) {
  return { client, ...render(<AppProviders client={client}>{ui}</AppProviders>) };
}

/** Render the whole shell at a path (without the /next basename). */
export function renderApp(path: string, client = testQueryClient()) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return { router, client, ...render(<AppProviders client={client}><RouterProvider router={router} /></AppProviders>) };
}

/** axe in jsdom: structure, names and ARIA. Color contrast is checked from the tokens instead. */
export async function expectNoAxeViolations(container: Element) {
  const result = await axe.run(container, {
    rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
  });
  const summary = result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`);
  expect(summary).toEqual([]);
}
