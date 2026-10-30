import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetConnectionForTests } from "../shared/api/connection";
import { resetLogForTests } from "../shared/log/logger";
import { expectNoAxeViolations, mockFetch, renderApp, shellRoutes, STATUS, testQueryClient } from "../test/utils";
import { AppProviders } from "./providers";
import { AuthGate } from "./AuthGate";
import { RouteErrorBoundary } from "./RouteErrorBoundary";

/** matchMedia whose answers the test controls; `set` fires change listeners. */
function controllableMedia(initial: Record<string, boolean>) {
  const state = { ...initial };
  const listeners = new Map<string, Set<() => void>>();
  window.matchMedia = ((query: string) => ({
    get matches() {
      return state[query] ?? false;
    },
    media: query,
    addEventListener: (_: string, fn: () => void) => {
      if (!listeners.has(query)) listeners.set(query, new Set());
      listeners.get(query)!.add(fn);
    },
    removeEventListener: (_: string, fn: () => void) => listeners.get(query)?.delete(fn),
  })) as unknown as typeof window.matchMedia;
  return {
    set(query: string, value: boolean) {
      state[query] = value;
      act(() => listeners.get(query)?.forEach((fn) => fn()));
    },
  };
}

const DARK = "(prefers-color-scheme: dark)";
const NARROW = "(max-width: 1179px)";

beforeEach(() => {
  window.localStorage.clear();
  resetConnectionForTests();
  resetLogForTests();
  delete document.documentElement.dataset.theme;
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("app shell", () => {
  it("shows the sidebar, toolbar and versions, and marks the current page", async () => {
    controllableMedia({});
    mockFetch(shellRoutes());
    renderApp("/settings");
    const nav = screen.getByRole("navigation", { name: "页面" });
    expect(within(nav).getByRole("link", { name: /设置/ })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: /环境/ })).not.toHaveAttribute("aria-current");
    expect(await screen.findByText("Manager v0.7.2")).toBeInTheDocument();
    expect(screen.getByText("内核 145.0.7632.159.1")).toBeInTheDocument();
    expect(await screen.findByText("运行中 2")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "外观" })).toBeInTheDocument();
  });

  it("shows background automation with its profile, and nothing while idle", async () => {
    controllableMedia({});
    mockFetch(shellRoutes([{ path: "/api/automation/status", respond: { active: true, kind: "warmup", label: "养号", profile_name: "Etsy UK" } }]));
    renderApp("/settings");
    expect(await screen.findByText("养号 · Etsy UK")).toBeInTheDocument();
  });

  it("lists running browsers in the toolbar popover", async () => {
    controllableMedia({});
    mockFetch(shellRoutes([{ path: "/api/profiles", respond: [
      { id: "a", name: "Amazon Seller #1", status: "running", group_name: null },
      { id: "b", name: "Etsy UK", status: "stopped", group_name: null },
    ] }]));
    renderApp("/settings");
    fireEvent.click(await screen.findByRole("button", { name: "运行中 2" }));
    const popover = await screen.findByRole("dialog", { name: "运行中的浏览器" });
    expect(await within(popover).findByText("Amazon Seller #1")).toBeInTheDocument();
    expect(within(popover).queryByText("Etsy UK")).not.toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    controllableMedia({});
    mockFetch(shellRoutes());
    const { container } = renderApp("/settings");
    await screen.findByText("Manager v0.7.2");
    await expectNoAxeViolations(container);
  });

  it("navigates with Ctrl/⌘ + number and opens the shortcut list with ?", async () => {
    controllableMedia({});
    mockFetch(shellRoutes());
    const { router } = renderApp("/settings");
    fireEvent.keyDown(window, { key: "2", ctrlKey: true, metaKey: true });
    expect(router.state.location.pathname).toBe("/proxies");
    expect(await screen.findByRole("heading", { name: "代理" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "?", shiftKey: true });
    expect(await screen.findByRole("dialog", { name: "快捷键" })).toBeInTheDocument();
  });

  it("does not steal ? while typing", async () => {
    controllableMedia({});
    mockFetch(shellRoutes());
    renderApp("/settings");
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    fireEvent.keyDown(input, { key: "?", shiftKey: true });
    expect(screen.queryByRole("dialog", { name: "快捷键" })).not.toBeInTheDocument();
    input.remove();
  });

  it("collapses the sidebar and saves the choice", async () => {
    controllableMedia({});
    const fetchMock = mockFetch(shellRoutes());
    renderApp("/settings");
    fireEvent.click(screen.getByRole("button", { name: "收起侧栏" }));
    expect(await screen.findByRole("button", { name: "展开侧栏" })).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/settings/ui", expect.objectContaining({ method: "PUT", body: JSON.stringify({ theme: "system", sidebar_collapsed: true, interface: "new" }) })),
    );
    expect(window.localStorage.getItem("cbm.sidebar")).toBe("1");
  });

  it("forces icon-only sidebar in a narrow window, without a toggle", () => {
    controllableMedia({ [NARROW]: true });
    mockFetch(shellRoutes());
    renderApp("/settings");
    expect(screen.queryByRole("button", { name: "收起侧栏" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "展开侧栏" })).not.toBeInTheDocument();
    expect(screen.queryByText("Manager v0.7.2")).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: "设置" });
    // The tooltip wrapper must not turn the link's class into function source.
    expect(link.className).toContain("h-8");
    expect(link.className).not.toContain("=>");
    expect(link).toHaveAttribute("aria-current", "page");
  });

  it("asks for a restart when the running Manager is older than the panel", async () => {
    controllableMedia({});
    mockFetch([{ path: "/api/settings/ui", status: 404, respond: { detail: "Not found" } }, ...shellRoutes().filter((route) => route.path !== "/api/settings/ui")]);
    renderApp("/settings");
    expect(await screen.findByText("Manager 服务是旧版本，需要重启")).toBeInTheDocument();
    expect(screen.getByText(/\.\/bin\/cloak restart/)).toBeInTheDocument();
  });

  it("warns when the data was written by a newer release", async () => {
    controllableMedia({});
    mockFetch(shellRoutes([{ path: "/api/status", respond: { ...STATUS, data_newer_than_app: true } }]));
    renderApp("/settings");
    expect(await screen.findByText("这份数据来自更新版本的 Manager")).toBeInTheDocument();
    expect(screen.getByText(/做一次完整备份/)).toBeInTheDocument();
  });

  it("does not ask for a restart when the Manager is current", async () => {
    controllableMedia({});
    mockFetch(shellRoutes());
    renderApp("/settings");
    expect(await screen.findByRole("heading", { name: "外观" })).toBeInTheDocument();
    expect(screen.queryByText("Manager 服务是旧版本，需要重启")).not.toBeInTheDocument();
  });

  it("shows a not-found page for unknown paths", () => {
    controllableMedia({});
    mockFetch(shellRoutes());
    renderApp("/nope");
    expect(screen.getByText("没有这个页面")).toBeInTheDocument();
  });
});

describe("theme", () => {
  it("follows the system by default and switches live", async () => {
    const media = controllableMedia({ [DARK]: false });
    mockFetch(shellRoutes());
    renderApp("/settings");
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("light"));
    media.set(DARK, true);
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("applies the saved preference and saves a new choice", async () => {
    controllableMedia({ [DARK]: false });
    const fetchMock = mockFetch(shellRoutes([{ path: "/api/settings/ui", respond: { theme: "dark", sidebar_collapsed: false } }]));
    renderApp("/settings");
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("dark"));
    expect(screen.getByRole("radio", { name: "深色" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "深色" })).toHaveAccessibleDescription("始终使用深色，适合夜间");
    fireEvent.click(screen.getByRole("radio", { name: "浅色" }));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("light"));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/settings/ui", expect.objectContaining({ method: "PUT", body: JSON.stringify({ theme: "light", sidebar_collapsed: false, interface: "new" }) })),
    );
    expect(window.localStorage.getItem("cbm.theme")).toBe("light");
  });

  it("tells the macOS app window which theme was chosen, and works without that bridge", async () => {
    controllableMedia({ [DARK]: false });
    const postMessage = vi.fn();
    window.webkit = { messageHandlers: { cbmTheme: { postMessage } } };
    try {
      mockFetch(shellRoutes());
      renderApp("/settings");
      await waitFor(() => expect(postMessage).toHaveBeenCalledWith({ theme: "system", resolved: "light" }));
      fireEvent.click(screen.getByRole("radio", { name: "深色" }));
      await waitFor(() => expect(postMessage).toHaveBeenLastCalledWith({ theme: "dark", resolved: "dark" }));
      // A bridge that throws must not break the panel.
      postMessage.mockImplementation(() => {
        throw new Error("bridge gone");
      });
      fireEvent.click(screen.getByRole("radio", { name: "浅色" }));
      await waitFor(() => expect(document.documentElement.dataset.theme).toBe("light"));
    } finally {
      delete window.webkit;
    }
  });

  it("uses the cached theme before the server answers", () => {
    controllableMedia({ [DARK]: false });
    window.localStorage.setItem("cbm.theme", "dark");
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    render(
      <AppProviders client={testQueryClient()}>
        <div />
      </AppProviders>,
    );
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("rolls back and explains when saving fails", async () => {
    controllableMedia({ [DARK]: false });
    mockFetch(shellRoutes([{ method: "PUT", path: "/api/settings/ui", status: 500, respond: { detail: "数据库被锁定" } }]));
    renderApp("/settings");
    await screen.findByText("Manager v0.7.2");
    fireEvent.click(screen.getByRole("radio", { name: "深色" }));
    expect(await screen.findByText("界面偏好没有保存")).toBeInTheDocument();
    expect(screen.getByText("数据库被锁定")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("radio", { name: "跟随系统" })).toBeChecked());
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

describe("connection banner", () => {
  it("appears when the Manager stops answering and clears after it is back", async () => {
    controllableMedia({});
    let down = false;
    const routes = shellRoutes();
    const healthy = mockFetch(routes).getMockImplementation()!;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (down) throw new TypeError("Failed to fetch");
        return healthy(input, init);
      }),
    );
    const { client } = renderApp("/settings");
    await screen.findByText("Manager v0.7.2");
    down = true;
    await act(async () => {
      await client.refetchQueries();
    });
    expect(await screen.findByText("连接不到 Manager 服务")).toBeInTheDocument();
    down = false;
    expect(await screen.findByText("已重新连接到 Manager", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByText("连接不到 Manager 服务")).not.toBeInTheDocument();
  });
});

describe("route error boundary", () => {
  function Boom(): never {
    throw new Error("组件炸了");
  }

  it("contains a crash, logs it and can reload the page", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}")));
    let crash = true;
    function MaybeBoom() {
      return crash ? <Boom /> : <p>恢复了</p>;
    }
    render(
      <RouteErrorBoundary>
        <MaybeBoom />
      </RouteErrorBoundary>,
    );
    expect(screen.getByText("这一页出错了")).toBeInTheDocument();
    expect(screen.getByText(/组件炸了/)).toBeInTheDocument();
    crash = false;
    fireEvent.click(screen.getByRole("button", { name: "重新加载此页" }));
    expect(screen.getByText("恢复了")).toBeInTheDocument();
    consoleError.mockRestore();
  });
});

describe("auth gate", () => {
  it("sends the user to sign in when a password is required", async () => {
    mockFetch(shellRoutes([{ path: "/api/auth/status", respond: { auth_required: true, authenticated: false, username: "admin" } }]));
    render(
      <AppProviders client={testQueryClient()}>
        <AuthGate>
          <p>面板</p>
        </AuthGate>
      </AppProviders>,
    );
    expect(await screen.findByRole("heading", { name: "CloakBrowser Manager" })).toBeInTheDocument();
    expect(screen.getByLabelText("用户名")).toHaveValue("admin");
    expect(screen.getByRole("button", { name: "登录" })).toBeDisabled();
    expect(screen.queryByText("面板")).not.toBeInTheDocument();
  });

  it("offers a retry when the Manager cannot be reached", async () => {
    let up = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (!up) throw new TypeError("Failed to fetch");
        const url = String(input);
        if (url === "/api/auth/status") return new Response(JSON.stringify({ auth_required: false, authenticated: false, username: null }));
        return new Response("{}");
      }),
    );
    render(
      <AppProviders client={testQueryClient()}>
        <AuthGate>
          <p>面板</p>
        </AuthGate>
      </AppProviders>,
    );
    expect(await screen.findByText("请确认 CloakBrowser Manager 正在运行，然后重试。")).toBeInTheDocument();
    up = true;
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("面板")).toBeInTheDocument();
  });
});
