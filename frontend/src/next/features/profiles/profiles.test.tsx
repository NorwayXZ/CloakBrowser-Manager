import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetConnectionForTests } from "../../shared/api/connection";
import { expectNoAxeViolations, mockFetch, renderApp, shellRoutes, type MockRoute } from "../../test/utils";
import { makeProfile } from "./testing";
import type { Preflight, Profile } from "./types";

vi.mock("@novnc/novnc/core/rfb.js", () => ({
  default: class {
    scaleViewport = false;
    resizeSession = false;
    showDotCursor = false;
    addEventListener() {}
    removeEventListener() {}
    disconnect() {}
    sendKey() {}
  },
}));

const PASS: Preflight = {
  status: "pass",
  browser_engine: "cloakbrowser",
  launch_mode: "manual",
  can_launch: true,
  issues: [],
  capabilities: { external_cdp: false, fingerprint_args: true, proxy_dns_policy: "proxy_host_resolver" },
};

const WARN: Preflight = {
  ...PASS,
  status: "warning",
  issues: [{ severity: "warning", code: "geo", message: "还没有保存的代理 GeoIP 结果；启动时会重新检测。" }],
};

const FAIL: Preflight = {
  ...PASS,
  status: "fail",
  can_launch: false,
  issues: [{ severity: "error", code: "os", message: "当前电脑是 macos，不能启动 windows 设备画像。" }],
};

const AMAZON = makeProfile({ id: "a", name: "Amazon Seller #1", group_name: "美国账号", proxy: "socks5://u:p@203.0.113.24:1080", notes: "主店铺" });
const ETSY = makeProfile({ id: "e", name: "Etsy UK", proxy: "https://192.0.2.55:443", user_agent: "Mozilla/5.0 Special" });
const TEMP = makeProfile({ id: "d1", name: "临时甲", disposable: true });

let profiles: Profile[];

function routes(extra: MockRoute[] = []): MockRoute[] {
  return shellRoutes([
    ...extra,
    { path: "/api/profiles", respond: () => profiles },
    { path: "/api/groups", respond: [{ id: "g1", name: "美国账号", color: "#2f5bff", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" }] },
  ]);
}

function row(name: string) {
  return screen.getByRole("article", { name });
}

function openMenu(button: HTMLElement) {
  fireEvent.keyDown(button, { key: "Enter" });
}

async function renderList(extra: MockRoute[] = [], path = "/profiles") {
  const fetchMock = mockFetch(routes(extra));
  const utils = renderApp(path);
  // hidden: a dialog opened from the URL hides the list from the accessibility tree.
  if (profiles.length && !path.includes("/viewer")) await screen.findByRole("article", { name: profiles[0]!.name, hidden: true });
  return { fetchMock, ...utils };
}

function calls(fetchMock: ReturnType<typeof mockFetch>, method: string, pattern: RegExp) {
  return fetchMock.mock.calls.filter(([url, init]) => (init?.method ?? "GET") === method && pattern.test(String(url)));
}

function bodyOf(call: unknown[] | undefined) {
  const init = call?.[1] as RequestInit | undefined;
  return init?.body ? JSON.parse(String(init.body)) : undefined;
}

beforeEach(() => {
  profiles = [AMAZON, ETSY, TEMP];
  window.localStorage.clear();
  resetConnectionForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("environment list", () => {
  it("lists every environment with its exit, group and state, and counts them", async () => {
    await renderList();
    expect(screen.getByText("共 3 个 · 运行中 0")).toBeInTheDocument();
    const amazon = row("Amazon Seller #1");
    expect(within(amazon).getByText("203.0.113.24:1080")).toBeInTheDocument();
    expect(within(amazon).getByText("SOCKS5")).toBeInTheDocument();
    expect(within(amazon).queryByText(/u:p/)).not.toBeInTheDocument();
    expect(within(row("临时甲")).getByText("一次性")).toBeInTheDocument();
    expect(within(amazon).queryByText("一次性")).not.toBeInTheDocument();
  });

  it("explains a failed launch, translating the license exit code", async () => {
    profiles = [makeProfile({ id: "f", name: "失败号", last_exit_reason: "异常退出（代码 76）" })];
    await renderList();
    expect(within(row("失败号")).getByText("上次启动失败")).toBeInTheDocument();
    fireEvent.click(within(row("失败号")).getByText("失败号"));
    expect(await screen.findByText("授权并发已满，请先关闭其他伪装画像")).toBeInTheDocument();
  });

  it("searches notes, proxy and UA, and offers to clear a search that matches nothing", async () => {
    await renderList();
    const search = screen.getByRole("textbox", { name: "搜索环境" });
    fireEvent.change(search, { target: { value: "主店铺" } });
    expect(screen.getByRole("article", { name: "Amazon Seller #1" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Etsy UK" })).not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "special" } });
    expect(screen.getByRole("article", { name: "Etsy UK" })).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "没有这个" } });
    expect(screen.getByText("没有匹配的环境")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "清除筛选" }));
    expect(screen.getByRole("article", { name: "Etsy UK" })).toBeInTheDocument();
  });

  it("filters by group, including 未分组", async () => {
    await renderList();
    const rail = screen.getByRole("navigation", { name: "分组" });
    fireEvent.click(within(rail).getByRole("button", { name: /^美国账号/ }));
    expect(screen.queryByRole("article", { name: "Etsy UK" })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Amazon Seller #1" })).toBeInTheDocument();
    fireEvent.click(within(rail).getByRole("button", { name: /^未分组/ }));
    expect(screen.getByRole("article", { name: "Etsy UK" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Amazon Seller #1" })).not.toBeInTheDocument();
  });

  it("creates and deletes groups; deleting says the environments go back to 未分组", async () => {
    const { fetchMock } = await renderList([
      { method: "POST", path: "/api/groups", respond: { id: "g2", name: "日本账号", color: null, created_at: "", updated_at: "" } },
      { method: "DELETE", path: "/api/groups/g1", respond: { ok: true } },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "新建分组" }));
    fireEvent.change(screen.getByRole("textbox", { name: "新分组名称" }), { target: { value: "日本账号" } });
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    await waitFor(() => expect(bodyOf(calls(fetchMock, "POST", /\/api\/groups$/)[0])).toEqual({ name: "日本账号" }));

    fireEvent.click(screen.getByRole("button", { name: "删除分组「美国账号」" }));
    const dialog = await screen.findByRole("dialog", { name: "删除分组「美国账号」？" });
    expect(dialog).toHaveTextContent("其中 1 个环境会回到“未分组”");
    fireEvent.click(within(dialog).getByRole("button", { name: "删除分组" }));
    await waitFor(() => expect(calls(fetchMock, "DELETE", /\/api\/groups\/g1$/)).toHaveLength(1));
  });

  it("shows an empty state with all three ways to create", async () => {
    profiles = [];
    await renderList();
    expect(await screen.findByText("还没有环境")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "自定义创建" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "一句话建号" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "一次性身份" })).toBeInTheDocument();
  });

  it("shows why the list could not load and retries", async () => {
    let fail = true;
    mockFetch(routes([{ path: "/api/profiles", status: 500, respond: () => (fail ? { detail: "数据库被锁定" } : profiles) }]));
    renderApp("/profiles");
    expect(await screen.findByText("数据库被锁定")).toBeInTheDocument();
    fail = false;
    mockFetch(routes());
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByRole("article", { name: "Amazon Seller #1" })).toBeInTheDocument();
  });

  it("has no accessibility violations, with the details panel open", async () => {
    const { container } = await renderList([], "/profiles?p=a");
    await screen.findByRole("heading", { name: "Amazon Seller #1" });
    await expectNoAxeViolations(container);
  });
});

describe("selection and keyboard", () => {
  it("selects rows and offers batch actions; Esc clears", async () => {
    await renderList();
    fireEvent.click(screen.getByRole("checkbox", { name: "选择「Amazon Seller #1」" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择「Etsy UK」" }));
    const bar = screen.getByRole("toolbar", { name: "批量操作" });
    expect(bar).toHaveTextContent("已选 2 个");
    fireEvent.click(screen.getByRole("checkbox", { name: "全选当前列表" }));
    expect(bar).toHaveTextContent("已选 3 个");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("toolbar", { name: "批量操作" })).not.toBeInTheDocument();
  });

  it("closes, copies and trashes the selection in one go", async () => {
    profiles = [{ ...AMAZON, status: "running" }, { ...ETSY, status: "running" }, TEMP];
    const { fetchMock } = await renderList([
      { method: "POST", path: /\/stop$/, respond: { ok: true } },
      { method: "POST", path: "/api/profiles", respond: (body: unknown) => ({ ...AMAZON, id: "copy", ...(body as object) }) },
      { method: "DELETE", path: /\/api\/profiles\/[a-z0-9]+$/, respond: { ok: true } },
    ]);
    fireEvent.click(screen.getByRole("checkbox", { name: "选择「Amazon Seller #1」" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择「Etsy UK」" }));
    const bar = screen.getByRole("toolbar", { name: "批量操作" });

    fireEvent.click(within(bar).getByRole("button", { name: /关闭/ }));
    await waitFor(() => expect(calls(fetchMock, "POST", /stop$/)).toHaveLength(2));
    expect(await screen.findByText("已关闭 2 个浏览器")).toBeInTheDocument();

    fireEvent.click(within(bar).getByRole("button", { name: "复制" }));
    await waitFor(() => expect(calls(fetchMock, "POST", /\/api\/profiles$/)).toHaveLength(2));
    expect(calls(fetchMock, "POST", /\/api\/profiles$/).map((call) => bodyOf(call).name)).toEqual(["Amazon Seller #1 副本", "Etsy UK 副本"]);

    fireEvent.click(within(bar).getByRole("button", { name: "移到回收站" }));
    const dialog = await screen.findByRole("dialog", { name: "把 2 个环境移到回收站？" });
    fireEvent.click(within(dialog).getByRole("button", { name: "移到回收站" }));
    await waitFor(() => expect(calls(fetchMock, "DELETE", /\/api\/profiles\//)).toHaveLength(2));
    await waitFor(() => expect(screen.queryByRole("toolbar", { name: "批量操作" })).not.toBeInTheDocument());
  });

  it("refreshes on demand", async () => {
    const { fetchMock } = await renderList();
    const before = calls(fetchMock, "GET", /\/api\/profiles$/).length;
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(calls(fetchMock, "GET", /\/api\/profiles$/).length).toBeGreaterThan(before));
  });

  it("moves with the arrow keys, selects with Space and opens with Enter", async () => {
    const { router } = await renderList();
    const first = row("Amazon Seller #1");
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(row("Etsy UK")).toHaveFocus();
    fireEvent.keyDown(row("Etsy UK"), { key: " " });
    expect(screen.getByRole("checkbox", { name: "选择「Etsy UK」" })).toBeChecked();
    fireEvent.keyDown(row("Etsy UK"), { key: "Enter" });
    expect(await screen.findByRole("heading", { name: "Etsy UK" })).toBeInTheDocument();
    expect(router.state.location.search).toContain("p=e");
  });

  it("focuses the search with / and ⌘/Ctrl+F", async () => {
    await renderList();
    fireEvent.keyDown(window, { key: "/" });
    expect(screen.getByRole("textbox", { name: "搜索环境" })).toHaveFocus();
  });
});

describe("launching", () => {
  it("checks first, then opens in daily mode after confirmation", async () => {
    const { fetchMock } = await renderList([
      { path: /\/api\/profiles\/e\/preflight/, respond: WARN },
      { method: "POST", path: "/api/profiles/e/launch", respond: () => {
        profiles = profiles.map((p) => (p.id === "e" ? { ...p, status: "running", launch_mode: "manual" } : p));
        return { profile_id: "e", status: "running", runtime_mode: "native", viewer_mode: "native-window", launch_mode: "manual" };
      } },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "打开「Etsy UK」" }));
    const dialog = await screen.findByRole("dialog", { name: "启动前检查" });
    expect(String(calls(fetchMock, "GET", /preflight/)[0]?.[0])).toContain("launch_mode=manual");
    expect(dialog).toHaveTextContent("还没有保存的代理 GeoIP 结果");
    expect(dialog).toHaveTextContent("1 项提示不会阻止启动");
    expect(calls(fetchMock, "POST", /launch$/)).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "继续启动" }));
    await waitFor(() => expect(bodyOf(calls(fetchMock, "POST", /\/e\/launch$/)[0])).toEqual({ launch_mode: "manual" }));
    expect(await screen.findByText("已打开「Etsy UK」")).toBeInTheDocument();
    expect(await screen.findByText("运行中", { selector: "span" })).toBeInTheDocument();
  });

  it("will not continue when the check fails", async () => {
    const { fetchMock } = await renderList([{ path: /\/api\/profiles\/d1\/preflight/, respond: FAIL }]);
    fireEvent.click(screen.getByRole("button", { name: "打开「临时甲」" }));
    const dialog = await screen.findByRole("dialog", { name: "启动前检查" });
    expect(dialog).toHaveTextContent("不能启动 windows 设备画像");
    expect(within(dialog).getByRole("button", { name: "继续启动" })).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
    expect(calls(fetchMock, "POST", /launch$/)).toHaveLength(0);
  });

  it("debug launch asks for debug mode", async () => {
    const { fetchMock } = await renderList([
      { path: /\/api\/profiles\/e\/preflight/, respond: { ...PASS, launch_mode: "debug" } },
      { method: "POST", path: "/api/profiles/e/launch", respond: { profile_id: "e", status: "running", runtime_mode: "native", viewer_mode: "native-window", launch_mode: "debug" } },
    ]);
    openMenu(screen.getByRole("button", { name: "「Etsy UK」的更多操作" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "调试启动（开启 CDP）" }));
    await waitFor(() => expect(String(calls(fetchMock, "GET", /preflight/)[0]?.[0])).toContain("launch_mode=debug"));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "启动前检查" })).getByRole("button", { name: "继续启动" }));
    await waitFor(() => expect(bodyOf(calls(fetchMock, "POST", /\/e\/launch$/)[0])).toEqual({ launch_mode: "debug" }));
  });

  it("opens the remote viewer for a single VNC launch", async () => {
    const { router } = await renderList([
      { path: /\/api\/profiles\/e\/preflight/, respond: PASS },
      { method: "POST", path: "/api/profiles/e/launch", respond: () => {
        profiles = profiles.map((p) => (p.id === "e" ? { ...p, status: "running", viewer_mode: "vnc" } : p));
        return { profile_id: "e", status: "running", runtime_mode: "docker", viewer_mode: "vnc", launch_mode: "manual" };
      } },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "打开「Etsy UK」" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "启动前检查" })).getByRole("button", { name: "继续启动" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/profiles/e/viewer"));
    expect(await screen.findByRole("button", { name: "关闭浏览器" })).toBeInTheDocument();
  });

  it("leaves the remote viewer when the browser stops elsewhere", async () => {
    profiles = [{ ...ETSY, status: "running", viewer_mode: "vnc" }];
    const { router, client } = await renderList([], "/profiles/e/viewer");
    expect(await screen.findByRole("button", { name: "关闭浏览器" })).toBeInTheDocument();
    profiles = [{ ...ETSY, status: "stopped", viewer_mode: "vnc" }];
    await client.refetchQueries({ queryKey: ["profiles", "list"] });
    await waitFor(() => expect(router.state.location.pathname).toBe("/profiles"));
    expect(router.state.location.search).toBe("?p=e");
    expect(await screen.findByText("「Etsy UK」已关闭")).toBeInTheDocument();
  });

  it("batch launch checks every selected environment and stays on the list", async () => {
    const { fetchMock, router } = await renderList([
      { path: /\/preflight/, respond: PASS },
      { method: "POST", path: /\/launch$/, respond: { profile_id: "x", status: "running", runtime_mode: "docker", viewer_mode: "vnc", launch_mode: "manual" } },
    ]);
    fireEvent.click(screen.getByRole("checkbox", { name: "选择「Amazon Seller #1」" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择「Etsy UK」" }));
    fireEvent.click(within(screen.getByRole("toolbar", { name: "批量操作" })).getByRole("button", { name: /打开/ }));
    const dialog = await screen.findByRole("dialog", { name: "启动前检查（2 个环境）" });
    fireEvent.click(within(dialog).getByRole("button", { name: "继续启动" }));
    await waitFor(() => expect(calls(fetchMock, "POST", /launch$/)).toHaveLength(2));
    expect(await screen.findByText("已打开 2 个浏览器")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/profiles");
  });

  it("reports a launch the backend refuses", async () => {
    await renderList([
      { path: /\/preflight/, respond: PASS },
      { method: "POST", path: "/api/profiles/e/launch", status: 409, respond: { detail: "CloakBrowser 授权服务器连接失败" } },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "打开「Etsy UK」" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "启动前检查" })).getByRole("button", { name: "继续启动" }));
    expect(await screen.findByText("「Etsy UK」没能打开")).toBeInTheDocument();
    expect(screen.getByText("CloakBrowser 授权服务器连接失败")).toBeInTheDocument();
  });

  it("closes a running browser", async () => {
    profiles = [{ ...ETSY, status: "running" }];
    const { fetchMock } = await renderList([{ method: "POST", path: "/api/profiles/e/stop", respond: { ok: true } }]);
    fireEvent.click(screen.getByRole("button", { name: "关闭「Etsy UK」" }));
    await waitFor(() => expect(calls(fetchMock, "POST", /\/e\/stop$/)).toHaveLength(1));
    expect(await screen.findByText("已关闭「Etsy UK」")).toBeInTheDocument();
  });
});

describe("details panel", () => {
  it("shows the CDP address and runs the fingerprint self-check of a debug launch", async () => {
    profiles = [{ ...ETSY, status: "running", launch_mode: "debug", cdp_url: "/api/profiles/e/cdp" }];
    await renderList([
      {
        path: "/api/profiles/e/fingerprint-report",
        respond: {
          profile_id: "e",
          expected: { browser_engine: "cloakbrowser", launch_mode: "debug", external_cdp: true, locale: "en-GB", timezone: "Europe/London" },
          collection: "active",
          proxy_geo: null,
          network: { dns_externally_verified: false },
          analysis: { status: "warning", error_count: 0, warning_count: 1, issues: [{ severity: "warning", signal: "timezone", scope: "worker", expected: "Europe/London", actual: "Asia/Tokyo", message: "Worker 时区和主页面不一致" }] },
          raw: {},
        },
      },
    ], "/profiles?p=e");
    const panel = await screen.findByRole("complementary", { name: "Etsy UK" });
    expect(within(panel).getByText(`${window.location.origin}/api/profiles/e/cdp`)).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "指纹自检" }));
    const report = await screen.findByRole("dialog", { name: "指纹自检 · Etsy UK" });
    expect(await within(report).findByText("Worker · timezone")).toBeInTheDocument();
    expect(within(report).getByText("Asia/Tokyo")).toBeInTheDocument();
    expect(within(report).getByText("没有收到外部探针结果，TLS 和出口 IP 不能算作已验证。")).toBeInTheDocument();
  });

  it("saves notes on blur and keeps the draft when saving fails", async () => {
    let fail = false;
    const { fetchMock } = await renderList([
      { method: "PUT", path: "/api/profiles/e", status: 200, respond: (body: unknown) => (fail ? undefined : { ...ETSY, ...(body as object) }) },
    ], "/profiles?p=e");
    const notes = await screen.findAllByRole("textbox", { name: "「Etsy UK」的备注" });
    const field = notes[notes.length - 1]!;
    fireEvent.focus(field);
    fireEvent.change(field, { target: { value: "  备用号  " } });
    fireEvent.blur(field);
    await waitFor(() => expect(bodyOf(calls(fetchMock, "PUT", /\/api\/profiles\/e$/)[0])).toEqual({ notes: "备用号" }));

    fail = true;
    mockFetch(routes([{ method: "PUT", path: "/api/profiles/e", status: 500, respond: { detail: "磁盘已满" } }]));
    fireEvent.focus(field);
    fireEvent.change(field, { target: { value: "新的备注" } });
    fireEvent.blur(field);
    expect(await screen.findByText("备注没有保存：磁盘已满")).toBeInTheDocument();
    expect(field).toHaveValue("新的备注");
  });

  it("copies an environment as 「名称 副本」 with a fresh seed", async () => {
    const { fetchMock } = await renderList([{ method: "POST", path: "/api/profiles", respond: { ...AMAZON, id: "a2", name: "Amazon Seller #1 副本" } }]);
    openMenu(screen.getByRole("button", { name: "「Amazon Seller #1」的更多操作" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "复制" }));
    await waitFor(() => expect(calls(fetchMock, "POST", /\/api\/profiles$/)).toHaveLength(1));
    const body = bodyOf(calls(fetchMock, "POST", /\/api\/profiles$/)[0]);
    expect(body).toMatchObject({ name: "Amazon Seller #1 副本", fingerprint_seed: null, auto_launch: false, notes: "主店铺" });
    expect(await screen.findByText("已复制为「Amazon Seller #1 副本」")).toBeInTheDocument();
  });
});

describe("agent lease", () => {
  const LEASE = { holder: "codex", kind: "agent", acquired_at: "2026-10-26T01:00:00Z", expires_at: "2026-10-26T01:10:00Z", seconds_left: 540 };

  it("shows who drives a running environment and takes it over", async () => {
    profiles = [{ ...AMAZON, status: "running", agent_lease: LEASE }, ETSY];
    const { fetchMock } = await renderList([
      {
        method: "POST",
        path: "/api/profiles/a/lease/takeover",
        respond: () => {
          profiles = profiles.map((p) => (p.id === "a" ? { ...p, agent_lease: { ...LEASE, holder: "human", kind: "human" } } : p));
          return { lease: null, cdp_connections_closed: 1 };
        },
      },
    ]);
    const amazon = row("Amazon Seller #1");
    expect(within(amazon).getByText("AI 控制中：codex")).toHaveAttribute("title", "AI 控制中：codex（9 分钟内有效）");
    expect(within(row("Etsy UK")).queryByTestId("agent-lease")).not.toBeInTheDocument();
    // One line: the action may not wrap.
    expect(within(amazon).getByRole("button", { name: "接管「Amazon Seller #1」" })).toHaveClass("whitespace-nowrap", "shrink-0");
    await expectNoAxeViolations(document.body);

    fireEvent.click(within(amazon).getByRole("button", { name: "接管「Amazon Seller #1」" }));
    await waitFor(() => expect(calls(fetchMock, "POST", /\/api\/profiles\/a\/lease\/takeover$/)).toHaveLength(1));
    expect(await within(row("Amazon Seller #1")).findByText(/你已接管，AI 暂不能操作/)).toBeInTheDocument();
  });

  it("hands a taken-over environment back to the AI", async () => {
    profiles = [{ ...AMAZON, status: "running", agent_lease: { ...LEASE, holder: "human", kind: "human" } }];
    const { fetchMock } = await renderList([
      {
        method: "DELETE",
        path: "/api/profiles/a/lease",
        respond: () => {
          profiles = profiles.map((p) => ({ ...p, agent_lease: null }));
          return { released: true };
        },
      },
    ]);
    fireEvent.click(within(row("Amazon Seller #1")).getByRole("button", { name: "把「Amazon Seller #1」归还给 AI" }));
    await waitFor(() => expect(calls(fetchMock, "DELETE", /\/lease$/)).toHaveLength(1));
    await waitFor(() => expect(within(row("Amazon Seller #1")).queryByTestId("agent-lease")).not.toBeInTheDocument());
  });

  it("says why a takeover failed and does not open the details", async () => {
    profiles = [{ ...AMAZON, status: "running", agent_lease: LEASE }];
    await renderList([{ method: "POST", path: "/api/profiles/a/lease/takeover", status: 409, respond: { detail: "租约已过期" } }]);
    fireEvent.click(within(row("Amazon Seller #1")).getByRole("button", { name: "接管「Amazon Seller #1」" }));
    expect(await screen.findByText("没能接管「Amazon Seller #1」")).toBeInTheDocument();
    expect(screen.getByText("租约已过期")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows no lease on a stopped environment", async () => {
    profiles = [{ ...AMAZON, agent_lease: LEASE }];
    await renderList();
    expect(screen.queryByTestId("agent-lease")).not.toBeInTheDocument();
  });
});

describe("trash and burn", () => {
  it("moves a stopped environment to the trash at once, with undo", async () => {
    const { fetchMock } = await renderList([
      { method: "DELETE", path: "/api/profiles/e", respond: { ok: true } },
      { method: "POST", path: "/api/profiles/e/restore", respond: ETSY },
    ]);
    openMenu(screen.getByRole("button", { name: "「Etsy UK」的更多操作" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "移到回收站" }));
    await waitFor(() => expect(calls(fetchMock, "DELETE", /\/api\/profiles\/e$/)).toHaveLength(1));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "撤销" }));
    await waitFor(() => expect(calls(fetchMock, "POST", /\/e\/restore$/)).toHaveLength(1));
    expect(await screen.findByText("已恢复")).toBeInTheDocument();
  });

  it("asks first when the browser is running", async () => {
    profiles = [{ ...ETSY, status: "running" }];
    const { fetchMock } = await renderList([{ method: "DELETE", path: "/api/profiles/e", respond: { ok: true } }]);
    openMenu(screen.getByRole("button", { name: "「Etsy UK」的更多操作" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "移到回收站" }));
    const dialog = await screen.findByRole("dialog", { name: "把「Etsy UK」移到回收站？" });
    expect(dialog).toHaveTextContent("会先被关闭");
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(calls(fetchMock, "DELETE", /\/api\/profiles\/e$/)).toHaveLength(0);
  });

  it("burns a disposable identity only after confirmation", async () => {
    const { fetchMock } = await renderList([{ method: "POST", path: "/api/profiles/d1/burn", respond: { ok: true, profile_id: "d1", user_data_dir: "", files_removed: 3, was_running: false } }]);
    openMenu(screen.getByRole("button", { name: "「临时甲」的更多操作" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "焚毁（彻底删除）" }));
    const dialog = await screen.findByRole("dialog", { name: "焚毁「临时甲」？" });
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(calls(fetchMock, "POST", /burn$/)).toHaveLength(0);

    openMenu(screen.getByRole("button", { name: "「临时甲」的更多操作" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "焚毁（彻底删除）" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "焚毁「临时甲」？" })).getByRole("button", { name: "焚毁" }));
    await waitFor(() => expect(bodyOf(calls(fetchMock, "POST", /\/d1\/burn$/)[0])).toEqual({ confirm: true }));
  });

  it("offers no burn for a normal environment", async () => {
    await renderList();
    openMenu(screen.getByRole("button", { name: "「Etsy UK」的更多操作" }));
    expect(await screen.findByRole("menuitem", { name: "移到回收站" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "焚毁（彻底删除）" })).not.toBeInTheDocument();
  });
});

describe("one-click creation", () => {
  const OPTIONS = {
    countries: [
      { code: "JP", name: "日本", locale: "ja-JP", timezone: "Asia/Tokyo" },
      { code: "US", name: "美国", locale: "en-US", timezone: "America/New_York" },
    ],
    cities: {
      US: [
        { name: "Seattle", name_zh: "西雅图", timezone: "America/Los_Angeles" },
        { name: "New York", name_zh: "纽约", timezone: "America/New_York" },
      ],
      JP: [{ name: "Tokyo", name_zh: "东京", timezone: "Asia/Tokyo" }],
    },
    interests: [{ id: "camping", name: "露营户外", targets: ["youtube"] }],
    targets: [{ id: "youtube", name: "YouTube" }],
  };
  const TEMPLATES = [{ id: "tpl-a", name: "模板甲", family: "intel", cpu: "Intel i5", gpu_vendor: "Intel", gpu_renderer: "ANGLE (Intel)", screen_width: 1920, screen_height: 1080, hardware_concurrency: 12, device_memory: 8, device_scale_factor: 1 }];
  const draft = (overrides: Record<string, unknown> = {}) => ({
    source: "fallback",
    spec: { country: "US", city: "Seattle", interests: ["camping"], persona_notes: null, purpose: null, disposable: false },
    assembled: {
      name: "西雅图 · 露营 10-23-a1b2", platform: "macos", device_profile: "tpl-a", screen_width: 1920, screen_height: 1080,
      gpu_vendor: "Intel", gpu_renderer: "ANGLE (Intel)", hardware_concurrency: 12, device_memory: 8,
      timezone: "America/Los_Angeles", locale: "en-US", warmup_targets: ["youtube"], warmup_enabled: true,
      warmup_persona: "西雅图，喜欢露营", notes: "一句话建号：建个美国号", disposable: false, fingerprint_options: {},
    },
    warnings: ["未配置 AI，已用关键词解析（理解有限）"],
    ...overrides,
  });
  const sentenceRoutes = (draftResult: unknown = draft()): MockRoute[] => [
    { method: "POST", path: "/api/profiles/from-sentence/draft", respond: draftResult },
    { path: "/api/profiles/from-sentence/options", respond: OPTIONS },
    { path: "/api/device-templates", respond: TEMPLATES },
    { method: "POST", path: "/api/profiles/from-sentence", respond: { ...AMAZON, id: "new-1", name: "我的西雅图号", warnings: [] } },
  ];

  async function parse(sentence = "建个美国号，西雅图，喜欢露营") {
    fireEvent.change(await screen.findByRole("textbox", { name: "一句话描述" }), { target: { value: sentence } });
    fireEvent.click(screen.getByRole("button", { name: "解析" }));
  }

  it("parses, previews with a fallback badge, and creates with the edits", async () => {
    const { fetchMock, router } = await renderList(sentenceRoutes(), "/profiles?create=sentence");
    await parse();
    const dialog = await screen.findByRole("dialog", { name: /一句话建号预览/ });
    expect(within(dialog).getByText("关键词解析")).toBeInTheDocument();
    expect(within(dialog).getByText("未配置 AI，已用关键词解析（理解有限）")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("城市")).toHaveValue("Seattle");
    fireEvent.change(within(dialog).getByLabelText(/^名称/), { target: { value: "我的西雅图号" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认创建" }));
    await waitFor(() => expect(calls(fetchMock, "POST", /from-sentence$/)).toHaveLength(1));
    const body = bodyOf(calls(fetchMock, "POST", /from-sentence$/)[0]);
    expect(body.sentence).toBe("建个美国号，西雅图，喜欢露营");
    expect(body.assembled).toMatchObject({ name: "我的西雅图号", device_profile: "tpl-a", timezone: "America/Los_Angeles" });
    await waitFor(() => expect(router.state.location.search).toBe("?p=new-1"));
  });

  it("links country → cities, language and timezone, and city → timezone", async () => {
    await renderList(sentenceRoutes(), "/profiles?create=sentence");
    await parse();
    const dialog = await screen.findByRole("dialog", { name: /一句话建号预览/ });
    await within(dialog).findByRole("option", { name: "纽约（New York）" });
    const timezone = within(dialog).getByLabelText("时区");
    fireEvent.change(within(dialog).getByLabelText("城市"), { target: { value: "New York" } });
    expect(timezone).toHaveValue("America/New_York");
    fireEvent.change(within(dialog).getByLabelText("国家"), { target: { value: "JP" } });
    expect(within(dialog).getByLabelText("城市")).toHaveValue("");
    expect(within(dialog).queryByRole("option", { name: "西雅图（Seattle）" })).not.toBeInTheDocument();
    expect(timezone).toHaveValue("Asia/Tokyo");
    expect(within(dialog).getByLabelText("语言区域")).toHaveValue("ja-JP");
  });

  it("marks AI drafts and says the sentence went to the model", async () => {
    await renderList(sentenceRoutes(draft({ source: "llm", warnings: [] })), "/profiles?create=sentence");
    await parse();
    const dialog = await screen.findByRole("dialog", { name: /一句话建号预览/ });
    expect(within(dialog).getByText("AI 解析")).toBeInTheDocument();
    expect(within(dialog).getByText(/发送到你配置的模型接口/)).toBeInTheDocument();
  });

  it("pre-ticks 一次性 when the sentence asked for it", async () => {
    const base = draft();
    await renderList(sentenceRoutes({ ...base, assembled: { ...base.assembled, disposable: true } }), "/profiles?create=sentence");
    await parse();
    const dialog = await screen.findByRole("dialog", { name: /一句话建号预览/ });
    expect(within(dialog).getByRole("checkbox", { name: /一次性身份/ })).toBeChecked();
  });

  it("shows the backend's reason and opens no preview", async () => {
    await renderList([{ method: "POST", path: "/api/profiles/from-sentence/draft", status: 422, respond: { detail: "没认出国家，请在句子里写明国家" } }], "/profiles?create=sentence");
    await parse("来个号");
    expect(await screen.findByText("没认出国家，请在句子里写明国家")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: /一句话建号预览/ })).not.toBeInTheDocument();
  });

  it("blocks a second submit while parsing", async () => {
    let release: () => void = () => undefined;
    const pending = new Promise<void>((resolve) => (release = resolve));
    const fetchMock = mockFetch(routes(sentenceRoutes()));
    const base = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).endsWith("/from-sentence/draft")) await pending;
      return base(input, init);
    });
    renderApp("/profiles?create=sentence");
    await parse();
    const button = await screen.findByRole("button", { name: "解析中…" });
    expect(button).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "一句话描述" })).toBeDisabled();
    release();
    expect(await screen.findByRole("dialog", { name: /一句话建号预览/ })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/draft"))).toHaveLength(1);
  });

  it("creates a disposable identity for the chosen region and opens it", async () => {
    const { fetchMock, router } = await renderList([{ method: "POST", path: "/api/profiles/disposable", respond: { ...TEMP, id: "d9", name: "一次性身份 JP" } }], "/profiles?create=disposable");
    const dialog = await screen.findByRole("dialog", { name: "新建一次性身份" });
    fireEvent.change(within(dialog).getByLabelText(/地区/), { target: { value: "JP" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "创建" }));
    await waitFor(() => expect(bodyOf(calls(fetchMock, "POST", /disposable$/)[0])).toEqual({ region: "JP" }));
    await waitFor(() => expect(router.state.location.search).toBe("?p=d9"));
  });
});
