import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetConnectionForTests } from "../../shared/api/connection";
import { expectNoAxeViolations, mockFetch, renderApp, shellRoutes, STATUS, type MockRoute } from "../../test/utils";
import type { AppUpdateState, KernelOverview } from "./api";
import { page } from "../../shared/lib/page";

const MB = 1024 * 1024;

function overview(patch: Partial<KernelOverview> = {}): KernelOverview {
  return {
    wrapper_version: "0.6.2",
    platform: "darwin-arm64",
    cache_dir: "/Users/me/.cloakbrowser",
    license: { tier: "free", plan: "free", expires: null, can_pin: false, key_stored: true },
    settings: { auto_update: true, release_channel: "stable", pinned_version: null },
    version: "154.0.8037.57.1",
    installed: true,
    pinned: false,
    bundled_version: "146.0.7680.177.5",
    installed_kernels: [
      { name: "chromium-154.0.8037.57.1-pro", version: "154.0.8037.57.1", pro: true, size_bytes: 408 * MB, in_use: true },
      { name: "chromium-145.0.7632.109.2", version: "145.0.7632.109.2", pro: false, size_bytes: 367 * MB, in_use: false },
    ],
    running_count: 0,
    ...patch,
  };
}

const NO_LICENSE = { tier: "none" as const, plan: null, expires: null, can_pin: true, key_stored: false };

function updateState(patch: Partial<AppUpdateState> = {}): AppUpdateState {
  return { phase: "idle", supported: true, current_version: "0.7.2", last_result: null, ...patch };
}

let running: number;

function routes(extra: MockRoute[] = []): MockRoute[] {
  return shellRoutes([...extra, { path: "/api/status", respond: () => ({ ...STATUS, running_count: running }) }]);
}

async function open(path: string, extra: MockRoute[] = [], heading?: string) {
  const fetchMock = mockFetch(routes(extra));
  const utils = renderApp(path, undefined, { auth: true });
  await screen.findByRole("heading", { name: "设置" });
  if (heading) await screen.findByRole("heading", { name: heading });
  return { fetchMock, ...utils };
}

function bodies(fetchMock: ReturnType<typeof mockFetch>, method: string, url: string) {
  return fetchMock.mock.calls
    .filter(([u, init]) => String(u) === url && (init?.method ?? "GET") === method)
    .map(([, init]) => (typeof init?.body === "string" ? JSON.parse(init.body) : init?.body));
}

async function confirmWith(label: string) {
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: label }));
}

async function cancelDialog() {
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

beforeEach(() => {
  running = 0;
  resetConnectionForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("settings › kernel", () => {
  it("shows the kernel in use, the license and reclaimable versions", async () => {
    await open("/settings/kernel", [{ path: "/api/kernel", respond: overview() }], "浏览器内核");
    expect(await screen.findByText("免费 GitHub 密钥")).toBeInTheDocument();
    expect(screen.getAllByText("154.0.8037.57.1").length).toBeGreaterThan(0);
    expect(screen.getByText(/1 个旧版本没在用，共 367.0 MB/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /删除内核/ })).toHaveLength(1);
    expect(screen.getByText("位置：/Users/me/.cloakbrowser")).toBeInTheDocument();
    await expectNoAxeViolations(document.body);
  });

  it("does not let a free key pin a version", async () => {
    await open("/settings/kernel", [{ path: "/api/kernel", respond: overview() }], "浏览器内核");
    expect(await screen.findByLabelText("锁定版本")).toBeDisabled();
    expect(screen.getByText(/官方不允许锁定版本/)).toBeInTheDocument();
  });

  it("checks for a newer kernel and updates it", async () => {
    const { fetchMock } = await open(
      "/settings/kernel",
      [
        { path: "/api/kernel", respond: overview() },
        { method: "POST", path: "/api/kernel/check", respond: { current_version: "154.0.8037.57.1", latest_version: "155.0.1.1.1", update_available: true, pinned: false } },
        {
          method: "POST",
          path: "/api/kernel/update",
          respond: { ok: true, updated: true, wrapper_version: "0.6.2", current_version: "154.0.8037.57.1", available_version: "155.0.1.1.1", installed_version: "155.0.1.1.1", platform: "darwin-arm64", binary_verified: true, restart_required: true, message: "CloakBrowser 内核已更新并验证为 155.0.1.1.1" },
        },
      ],
      "浏览器内核",
    );
    fireEvent.click(await screen.findByRole("button", { name: "检查更新" }));
    expect(await screen.findByText(/发现新内核 155.0.1.1.1/)).toBeInTheDocument();
    expect(screen.getByText("155.0.1.1.1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "立即更新" }));
    expect(await screen.findByText(/已更新并验证为 155.0.1.1.1/)).toBeInTheDocument();
    expect(bodies(fetchMock, "POST", "/api/kernel/update")).toHaveLength(1);
  });

  it("saves update settings only after a change", async () => {
    const { fetchMock } = await open(
      "/settings/kernel",
      [
        { path: "/api/kernel", respond: overview() },
        { method: "PUT", path: "/api/kernel/settings", respond: (settings: unknown) => overview({ settings: settings as KernelOverview["settings"] }) },
      ],
      "浏览器内核",
    );
    const save = await screen.findByRole("button", { name: "保存设置" });
    expect(save).toBeDisabled();
    fireEvent.click(screen.getByRole("switch", { name: /自动下载新内核/ }));
    fireEvent.change(screen.getByLabelText("更新渠道"), { target: { value: "preview" } });
    fireEvent.click(save);
    expect(await screen.findByText("内核设置已保存")).toBeInTheDocument();
    expect(bodies(fetchMock, "PUT", "/api/kernel/settings")).toEqual([{ auto_update: false, release_channel: "preview", pinned_version: null }]);
    expect(await screen.findByText("预览渠道")).toBeInTheDocument();
  });

  it("saves a typed license key and clears the field", async () => {
    const { fetchMock } = await open(
      "/settings/kernel",
      [
        { path: "/api/kernel", respond: overview({ license: NO_LICENSE }) },
        { method: "POST", path: "/api/kernel/license", respond: overview() },
      ],
      "浏览器内核",
    );
    const input = (await screen.findByLabelText("CloakBrowser 授权密钥")) as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(screen.getByRole("button", { name: "保存密钥" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "cb_test_fixture_000" } });
    fireEvent.click(screen.getByRole("button", { name: "保存密钥" }));
    expect(await screen.findByText(/授权密钥已保存并通过验证/)).toBeInTheDocument();
    expect(bodies(fetchMock, "POST", "/api/kernel/license")).toEqual([{ license_key: "cb_test_fixture_000" }]);
    expect(input.value).toBe("");
    expect(screen.getByRole("button", { name: "更换密钥" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "移除密钥" })).toBeInTheDocument();
  });

  it("keeps the typed key and shows the error when the key is rejected", async () => {
    await open(
      "/settings/kernel",
      [
        { path: "/api/kernel", respond: overview({ license: NO_LICENSE }) },
        { method: "POST", path: "/api/kernel/license", status: 400, respond: { detail: "这个授权密钥没有通过官方验证，已恢复之前的设置。请核对密钥后重新输入。" } },
      ],
      "浏览器内核",
    );
    const input = (await screen.findByLabelText("CloakBrowser 授权密钥")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "cb_test_fixture_999" } });
    fireEvent.click(screen.getByRole("button", { name: "保存密钥" }));
    expect(await screen.findByText(/没有通过官方验证/)).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input.value).toBe("cb_test_fixture_999");
  });

  it("removes a stored license key after confirmation", async () => {
    const { fetchMock } = await open(
      "/settings/kernel",
      [
        { path: "/api/kernel", respond: overview() },
        { method: "DELETE", path: "/api/kernel/license", respond: overview({ license: NO_LICENSE }) },
      ],
      "浏览器内核",
    );
    expect(await screen.findByText(/已保存授权密钥/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "移除密钥" }));
    await cancelDialog();
    expect(bodies(fetchMock, "DELETE", "/api/kernel/license")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "移除密钥" }));
    await confirmWith("移除密钥");
    expect(await screen.findByText(/已移除保存的授权密钥/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存密钥" })).toBeInTheDocument();
  });

  it("does not delete old kernels while a browser runs", async () => {
    running = 1;
    await open("/settings/kernel", [{ path: "/api/kernel", respond: overview() }], "浏览器内核");
    const button = await screen.findByRole("button", { name: "删除内核 145.0.7632.109.2" });
    await waitFor(() => expect(button).toBeDisabled());
    expect(screen.getByText(/关闭全部浏览器后才能删除旧内核/)).toBeInTheDocument();
  });

  it("deletes an old kernel only after confirmation", async () => {
    const { fetchMock } = await open(
      "/settings/kernel",
      [
        { path: "/api/kernel", respond: overview() },
        { method: "DELETE", path: "/api/kernel/versions/chromium-145.0.7632.109.2", respond: { ok: true, freed_bytes: 367 * MB } },
      ],
      "浏览器内核",
    );
    const button = await screen.findByRole("button", { name: "删除内核 145.0.7632.109.2" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await cancelDialog();
    expect(bodies(fetchMock, "DELETE", "/api/kernel/versions/chromium-145.0.7632.109.2")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "删除内核 145.0.7632.109.2" }));
    await confirmWith("删除");
    expect(await screen.findByText(/释放 367.0 MB/)).toBeInTheDocument();
  });

  it("explains a failed load and retries", async () => {
    let fail = true;
    mockFetch(routes([{ path: "/api/kernel", respond: () => (fail ? new Error() : overview()) }]));
    const real = (globalThis.fetch as ReturnType<typeof vi.fn>).getMockImplementation()!;
    vi.mocked(globalThis.fetch).mockImplementation(async (input, init) =>
      String(input) === "/api/kernel" && fail ? new Response(JSON.stringify({ detail: "读取内核目录失败" }), { status: 500 }) : real(input, init),
    );
    renderApp("/settings/kernel");
    expect(await screen.findByText("读取内核目录失败")).toBeInTheDocument();
    expect(screen.getByText("内核信息没有读出来")).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("免费 GitHub 密钥")).toBeInTheDocument();
  });
});

describe("settings › AI", () => {
  const LLM = { configured: true, base_url: "https://api.example.com/v1", model: "gpt-4o-mini", has_api_key: true, executor_model: null, executor_effort: null };

  it("shows the saved endpoint without the key and saves edits", async () => {
    const { fetchMock } = await open(
      "/settings/ai",
      [
        { path: "/api/settings/llm", respond: LLM },
        { method: "PUT", path: "/api/settings/llm", respond: (body: { base_url: string; model: string; executor_model: string; executor_effort: string }) => ({ ...LLM, ...body, executor_effort: body.executor_effort || null, executor_model: body.executor_model || null }) },
      ],
      "AI 接口",
    );
    expect(await screen.findByLabelText("接口地址")).toHaveValue("https://api.example.com/v1");
    expect(screen.getByText("已配置")).toBeInTheDocument();
    const key = screen.getByLabelText("API 密钥");
    expect(key).toHaveValue("");
    expect(key).toHaveAttribute("placeholder", "已配置（留空表示不修改）");
    expect(screen.getByRole("button", { name: "保存设置" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "deepseek-chat" } });
    fireEvent.change(screen.getByLabelText("执行强度"), { target: { value: "high" } });
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));
    expect(await screen.findByText("AI 接口设置已保存")).toBeInTheDocument();
    // An empty key field means "keep the stored key".
    expect(bodies(fetchMock, "PUT", "/api/settings/llm")).toEqual([
      { base_url: "https://api.example.com/v1", model: "deepseek-chat", api_key: null, executor_model: "", executor_effort: "high" },
    ]);
    await expectNoAxeViolations(document.body);
  });

  it("sends a new key once and clears the field", async () => {
    const { fetchMock } = await open(
      "/settings/ai",
      [
        { path: "/api/settings/llm", respond: { ...LLM, configured: false, has_api_key: false } },
        { method: "PUT", path: "/api/settings/llm", respond: LLM },
      ],
      "AI 接口",
    );
    expect(await screen.findByText(/还没配置完整/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("API 密钥"), { target: { value: "sk-test-fixture" } });
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));
    expect(await screen.findByText("已配置，AI 功能可用。")).toBeInTheDocument();
    expect(bodies(fetchMock, "PUT", "/api/settings/llm")[0].api_key).toBe("sk-test-fixture");
    expect(screen.getByLabelText("API 密钥")).toHaveValue("");
  });

  it("shows why saving failed", async () => {
    await open(
      "/settings/ai",
      [
        { path: "/api/settings/llm", respond: LLM },
        { method: "PUT", path: "/api/settings/llm", status: 422, respond: { detail: [{ msg: "接口地址必须以 http:// 或 https:// 开头" }] } },
      ],
      "AI 接口",
    );
    fireEvent.change(await screen.findByLabelText("接口地址"), { target: { value: "api.example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));
    expect(await screen.findByText("接口地址必须以 http:// 或 https:// 开头")).toBeInTheDocument();
  });
});

describe("settings › AI 接入", () => {
  const NO_TOKENS = { enforced: true, scopes: ["read", "control", "cdp"], tokens: [] };
  const TOKEN = { id: "t1", name: "codex 笔记本", scope: "control", created_at: 1_700_000_000 };
  const AUDIT = [{ id: "a1", ts: "2026-10-26T01:00:00+00:00", client_name: "codex", client_version: null, tool: "open_browser", args_summary: {}, ok: false, reason: "profile_leased", duration_ms: 12 }];
  let mode: string;

  function agentRoutes(extra: MockRoute[] = [], tokens: unknown = NO_TOKENS, audit: unknown = []): MockRoute[] {
    return [
      ...extra,
      { path: "/api/settings/mcp", respond: () => ({ mode }) },
      { method: "PUT", path: "/api/settings/mcp", respond: (body: { mode: string }) => ((mode = body.mode), { mode }) },
      { path: "/api/agent/tokens", respond: tokens },
      { path: "/api/mcp/audit?limit=30", respond: audit },
    ];
  }

  beforeEach(() => {
    mode = "read-only";
  });

  it("shows the current mode and saves a change", async () => {
    const { fetchMock } = await open("/settings/agent", agentRoutes(), "AI agent 权限");
    expect(await screen.findByRole("radio", { name: "只读（默认）" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "可启停" }));
    expect(await screen.findByText("AI agent 权限已保存")).toBeInTheDocument();
    expect(screen.getByText(/MCP 客户端需要重启/)).toBeInTheDocument();
    expect(bodies(fetchMock, "PUT", "/api/settings/mcp")).toEqual([{ mode: "full" }]);
    expect(screen.getByRole("radio", { name: "可启停" })).toBeChecked();
    await expectNoAxeViolations(document.body);
  });

  it("warns that page control can read cookies and does nothing when declined", async () => {
    const { fetchMock } = await open("/settings/agent", agentRoutes(), "AI agent 权限");
    fireEvent.click(await screen.findByRole("radio", { name: "可操作页面" }));
    expect(await within(await screen.findByRole("dialog")).findByText(/全部 Cookie/)).toBeInTheDocument();
    await cancelDialog();
    expect(bodies(fetchMock, "PUT", "/api/settings/mcp")).toEqual([]);
    expect(screen.getByRole("radio", { name: "只读（默认）" })).toBeChecked();

    fireEvent.click(screen.getByRole("radio", { name: "可操作页面" }));
    await confirmWith("确定开启");
    expect(await screen.findByText(/当前允许 AI 操作页面/)).toBeInTheDocument();
    expect(bodies(fetchMock, "PUT", "/api/settings/mcp")).toEqual([{ mode: "automation" }]);
  });

  it("shows why saving the mode failed", async () => {
    await open("/settings/agent", agentRoutes([{ method: "PUT", path: "/api/settings/mcp", status: 500, respond: { detail: "写不进去" } }]), "AI agent 权限");
    fireEvent.click(await screen.findByRole("radio", { name: "关闭" }));
    expect(await screen.findByText("写不进去")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "只读（默认）" })).toBeChecked();
  });

  it("lists connection addresses for this Manager", async () => {
    await open("/settings/agent", agentRoutes(), "接入地址");
    expect(screen.getByText(`${window.location.origin}/api/agent/mcp`)).toBeInTheDocument();
    expect(screen.getByText(`${window.location.origin}/api/agent/tools?format=openai`)).toBeInTheDocument();
    expect(screen.getByText(`${window.location.origin}/api/agent/guide`)).toBeInTheDocument();
    expect(screen.getByText("python -m backend.mcp_server")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "复制HTTP MCP" })).toBeInTheDocument();
  });

  it("issues a token, shows it once, and lists it", async () => {
    let tokens: unknown[] = [];
    const { fetchMock } = await open(
      "/settings/agent",
      agentRoutes([
        { path: "/api/agent/tokens", respond: () => ({ ...NO_TOKENS, tokens }) },
        { method: "POST", path: "/api/agent/tokens", status: 201, respond: () => ((tokens = [TOKEN]), { token: "cbm_control_SECRET", record: TOKEN, enforced: true, note: "" }) },
      ]),
      "Agent token",
    );
    const issue = await screen.findByRole("button", { name: "签发 token" });
    expect(issue).toBeDisabled();
    expect(screen.getByText("还没有签发过 token。")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: " codex 笔记本 " } });
    fireEvent.change(screen.getByLabelText("权限范围"), { target: { value: "control" } });
    fireEvent.click(issue);
    expect(await screen.findByText("cbm_control_SECRET")).toBeInTheDocument();
    expect(screen.getByText(/只显示这一次/)).toBeInTheDocument();
    expect(bodies(fetchMock, "POST", "/api/agent/tokens")).toEqual([{ name: "codex 笔记本", scope: "control" }]);
    expect(await screen.findByRole("button", { name: "撤销 codex 笔记本" })).toBeInTheDocument();
    await expectNoAxeViolations(document.body);
    fireEvent.click(screen.getByRole("button", { name: "我已保存，关闭" }));
    expect(screen.queryByText("cbm_control_SECRET")).not.toBeInTheDocument();
  });

  it("revokes a token only after confirmation", async () => {
    let tokens = [TOKEN];
    const { fetchMock } = await open(
      "/settings/agent",
      agentRoutes([
        { path: "/api/agent/tokens", respond: () => ({ ...NO_TOKENS, tokens }) },
        { method: "DELETE", path: "/api/agent/tokens/t1", respond: () => ((tokens = []), { ok: true }) },
      ]),
      "Agent token",
    );
    fireEvent.click(await screen.findByRole("button", { name: "撤销 codex 笔记本" }));
    await cancelDialog();
    expect(bodies(fetchMock, "DELETE", "/api/agent/tokens/t1")).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "撤销 codex 笔记本" }));
    await confirmWith("撤销");
    expect(await screen.findByText("还没有签发过 token。")).toBeInTheDocument();
    expect(bodies(fetchMock, "DELETE", "/api/agent/tokens/t1")).toHaveLength(1);
  });

  it("tells the user tokens are not checked when the Manager has no sign-in", async () => {
    await open("/settings/agent", agentRoutes([], { ...NO_TOKENS, enforced: false }), "Agent token");
    expect(await screen.findByText(/token 不会被检查/)).toBeInTheDocument();
  });

  it("shows recent agent calls, failures with their reason", async () => {
    await open("/settings/agent", agentRoutes([], NO_TOKENS, AUDIT), "最近的 agent 操作");
    const table = await screen.findByRole("table", { name: "agent 操作记录" });
    expect(within(table).getByText("open_browser")).toBeInTheDocument();
    expect(within(table).getByText("profile_leased")).toBeInTheDocument();
    expect(within(table).getByText("codex")).toBeInTheDocument();
    expect(within(table).getByText("12 ms")).toBeInTheDocument();
    await expectNoAxeViolations(document.body);
  });

  it("says when there are no agent calls yet, and reloads on demand", async () => {
    const { fetchMock } = await open("/settings/agent", agentRoutes(), "最近的 agent 操作");
    expect(await screen.findByText("还没有 agent 调用记录。")).toBeInTheDocument();
    const before = fetchMock.mock.calls.filter(([u]) => String(u).startsWith("/api/mcp/audit")).length;
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([u]) => String(u).startsWith("/api/mcp/audit")).length).toBe(before + 1));
  });

  it("shows why the mode could not be read", async () => {
    await open("/settings/agent", agentRoutes([{ path: "/api/settings/mcp", status: 500, respond: { detail: "读不到" } }]), "AI agent 权限");
    expect(await screen.findByText("AI 接入设置没有读出来")).toBeInTheDocument();
    expect(screen.getByText("读不到")).toBeInTheDocument();
  });
});

describe("settings › automation", () => {
  it("loads the current window and saves edits", async () => {
    const { fetchMock } = await open(
      "/settings/automation",
      [
        { path: "/api/automation/hours", respond: { hours: "09-18", open_now: true } },
        { method: "PUT", path: "/api/automation/hours", respond: (body: { hours: string | null }) => ({ hours: body.hours, open_now: false }) },
      ],
      "自动化时段",
    );
    const input = await screen.findByLabelText("允许的时段");
    expect(input).toHaveValue("09-18");
    expect(screen.getByText(/现在在时段（09-18）内/)).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "23-07" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("自动化时段已设为 23-07")).toBeInTheDocument();
    expect(bodies(fetchMock, "PUT", "/api/automation/hours")).toEqual([{ hours: "23-07" }]);
    expect(await screen.findByText(/现在不在时段（23-07）内/)).toBeInTheDocument();
    await expectNoAxeViolations(document.body);
  });

  it("saves an empty value as no restriction", async () => {
    const { fetchMock } = await open(
      "/settings/automation",
      [
        { path: "/api/automation/hours", respond: { hours: "09-18", open_now: true } },
        { method: "PUT", path: "/api/automation/hours", respond: { hours: null, open_now: true } },
      ],
      "自动化时段",
    );
    fireEvent.change(await screen.findByLabelText("允许的时段"), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("已取消自动化时段限制")).toBeInTheDocument();
    expect(bodies(fetchMock, "PUT", "/api/automation/hours")).toEqual([{ hours: null }]);
    expect(screen.getByText(/现在不限制时段/)).toBeInTheDocument();
  });

  it("keeps the input and shows the reason when the backend rejects it", async () => {
    await open(
      "/settings/automation",
      [
        { path: "/api/automation/hours", respond: { hours: null, open_now: true } },
        { method: "PUT", path: "/api/automation/hours", status: 400, respond: { detail: "时段格式应为 HH-HH，例如 09-18" } },
      ],
      "自动化时段",
    );
    const input = await screen.findByLabelText("允许的时段");
    fireEvent.change(input, { target: { value: "9点到6点" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("时段格式应为 HH-HH，例如 09-18")).toBeInTheDocument();
    expect(input).toHaveValue("9点到6点");
  });

  it("warns on the checks page when now is outside the window, and not inside it", async () => {
    for (const [hours, outside] of [["09-18", true], ["00-24", false]] as const) {
      mockFetch(
        routes([
          { path: "/api/automation/hours", respond: { hours, open_now: !outside } },
          { path: "/api/site-checks/sites", respond: [] },
          { path: "/api/site-checks/current", respond: { phase: "idle" } },
          { path: "/api/site-checks", respond: [] },
          { path: "/api/evolution/status", respond: { busy: false, pending_proposals: 0 } },
        ]),
      );
      const { unmount } = renderApp("/checks");
      await screen.findByRole("heading", { name: "检测" });
      if (outside) expect(await screen.findByText(/当前不在自动化时段（09-18）内/)).toBeInTheDocument();
      else {
        await screen.findByText("一键检测报告");
        expect(screen.queryByText(/当前不在自动化时段/)).not.toBeInTheDocument();
      }
      unmount();
    }
  });
});

describe("settings › account", () => {
  const AUTH = { auth_required: true, authenticated: true, username: "boss" };

  it("explains how to turn sign-in on when it is off", async () => {
    await open("/settings/account", [], "账号与安全");
    expect(screen.getByText("没有开启登录保护")).toBeInTheDocument();
    expect(screen.getByText(/ADMIN_PASSWORD/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "退出登录" })).not.toBeInTheDocument();
  });

  it("checks that the new password is typed twice the same", async () => {
    const { fetchMock } = await open("/settings/account", [{ path: "/api/auth/status", respond: AUTH }], "管理员账号");
    expect(screen.getByLabelText("用户名")).toHaveValue("boss");
    fireEvent.change(screen.getByLabelText(/当前密码/), { target: { value: "old-password" } });
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "short" } });
    expect(screen.getByText("新密码至少 8 个字符")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "new-password-1" } });
    fireEvent.change(screen.getByLabelText("确认新密码"), { target: { value: "new-password-2" } });
    expect(screen.getByText("两次输入的新密码不一致")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
    expect(bodies(fetchMock, "PUT", "/api/auth/account")).toHaveLength(0);
  });

  it("saves a new name and password, then clears the password fields", async () => {
    const { fetchMock } = await open(
      "/settings/account",
      [
        { path: "/api/auth/status", respond: AUTH },
        { method: "PUT", path: "/api/auth/account", respond: { ok: true, username: "chief" } },
      ],
      "管理员账号",
    );
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "chief" } });
    fireEvent.change(screen.getByLabelText(/当前密码/), { target: { value: "old-password" } });
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "new-password" } });
    fireEvent.change(screen.getByLabelText("确认新密码"), { target: { value: "new-password" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("用户名和密码已保存")).toBeInTheDocument();
    expect(bodies(fetchMock, "PUT", "/api/auth/account")).toEqual([{ current_password: "old-password", username: "chief", new_password: "new-password" }]);
    expect(screen.getByLabelText(/当前密码/)).toHaveValue("");
    expect(screen.getByLabelText("新密码")).toHaveValue("");
    await expectNoAxeViolations(document.body);
  });

  it("shows a wrong current password", async () => {
    await open(
      "/settings/account",
      [
        { path: "/api/auth/status", respond: AUTH },
        { method: "PUT", path: "/api/auth/account", status: 403, respond: { detail: "当前密码错误" } },
      ],
      "管理员账号",
    );
    fireEvent.change(screen.getByLabelText(/当前密码/), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("当前密码错误")).toBeInTheDocument();
  });

  it("signs out to the login page", async () => {
    let signedIn = true;
    const { fetchMock } = await open(
      "/settings/account",
      [
        { path: "/api/auth/status", respond: () => ({ ...AUTH, authenticated: signedIn }) },
        { method: "POST", path: "/api/auth/logout", respond: () => ((signedIn = false), { ok: true }) },
      ],
      "退出登录",
    );
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    expect(await screen.findByRole("heading", { name: "CloakBrowser Manager" })).toBeInTheDocument();
    expect(screen.getByLabelText("用户名")).toHaveValue("boss");
    expect(screen.queryByRole("navigation", { name: "页面" })).not.toBeInTheDocument();
    expect(bodies(fetchMock, "POST", "/api/auth/logout")).toHaveLength(1);
  });

  it("still signs out on this device when the Manager cannot be reached", async () => {
    await open("/settings/account", [{ path: "/api/auth/status", respond: AUTH }, { method: "POST", path: "/api/auth/logout", status: 500, respond: { detail: "boom" } }], "退出登录");
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    expect(await screen.findByRole("button", { name: "登录" })).toBeInTheDocument();
  });
});

describe("login", () => {
  it("rejects a wrong password, then signs in and shows the panel", async () => {
    let signedIn = false;
    const fetchMock = mockFetch(
      routes([
        { path: "/api/auth/status", respond: () => ({ auth_required: true, authenticated: signedIn, username: "admin" }) },
        {
          method: "POST",
          path: "/api/auth/login",
          respond: () => ((signedIn = true), { ok: true, username: "admin" }),
        },
      ]),
    );
    // The mock router cannot vary the status per call; answer the wrong password by hand.
    const real = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input) === "/api/auth/login" && typeof init?.body === "string" && JSON.parse(init.body).password !== "right-password") {
        return new Response(JSON.stringify({ detail: "用户名或密码错误" }), { status: 401 });
      }
      return real(input, init);
    });
    renderApp("/profiles", undefined, { auth: true });
    const password = await screen.findByLabelText("密码");
    await expectNoAxeViolations(document.body);
    fireEvent.change(password, { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByText("用户名或密码错误")).toBeInTheDocument();
    expect(password).toHaveValue("");

    fireEvent.change(password, { target: { value: "right-password" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByRole("navigation", { name: "页面" })).toBeInTheDocument();
  });

  it("goes back to the login page when a request answers 401", async () => {
    let signedIn = true;
    mockFetch(
      routes([
        { path: "/api/auth/status", respond: () => ({ auth_required: true, authenticated: signedIn, username: "admin" }) },
        { path: "/api/settings/llm", status: 401, respond: () => ((signedIn = false), { detail: "Unauthorized" }) },
      ]),
    );
    renderApp("/settings/ai", undefined, { auth: true });
    expect(await screen.findByRole("button", { name: "登录" })).toBeInTheDocument();
  });
});

describe("settings › interface switch", () => {
  it("stores the choice of the old panel, then opens it", async () => {
    const assign = vi.spyOn(page, "assign").mockImplementation(() => undefined);
    const { fetchMock } = await open(
      "/settings/about",
      [{ path: "/api/settings/ui", respond: { theme: "dark", sidebar_collapsed: true, interface: "new" } }],
      "界面版本",
    );
    fireEvent.click(await screen.findByRole("button", { name: "切换回旧版界面" }));
    await cancelDialog();
    expect(assign).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "切换回旧版界面" }));
    await confirmWith("切换");
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/legacy/"));
    // The theme and sidebar choices travel with it, so nothing else is reset.
    expect(bodies(fetchMock, "PUT", "/api/settings/ui")).toEqual([{ theme: "dark", sidebar_collapsed: true, interface: "legacy" }]);
  });

  it("stays in the new panel and says so when the choice cannot be stored", async () => {
    const assign = vi.spyOn(page, "assign").mockImplementation(() => undefined);
    await open(
      "/settings/about",
      [
        { path: "/api/settings/ui", respond: { theme: "system", sidebar_collapsed: false, interface: "new" } },
        { method: "PUT", path: "/api/settings/ui", status: 500, respond: { detail: "数据库被锁定" } },
      ],
      "界面版本",
    );
    fireEvent.click(await screen.findByRole("button", { name: "切换回旧版界面" }));
    await confirmWith("切换");
    expect(await screen.findByText("界面偏好没有保存")).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "切换回旧版界面" })).toBeEnabled();
  });

  it("keeps the saved choice of panel when only the theme changes", async () => {
    const { fetchMock } = await open(
      "/settings",
      [{ path: "/api/settings/ui", respond: { theme: "system", sidebar_collapsed: false, interface: "legacy" } }],
      "外观",
    );
    fireEvent.click(await screen.findByRole("radio", { name: "深色" }));
    await waitFor(() => expect(bodies(fetchMock, "PUT", "/api/settings/ui")).toHaveLength(1));
    expect(bodies(fetchMock, "PUT", "/api/settings/ui")[0]).toEqual({ theme: "dark", sidebar_collapsed: false, interface: "legacy" });
  });
});

describe("settings › about and update", () => {
  const PACKAGED_CHECK = {
    ok: true,
    updated: false,
    before: "0.7.2",
    after: "0.8.0",
    branch: null,
    restart_required: false,
    message: "发现新版本 0.8.0（当前 0.7.2）。点击下方链接下载，打开后把新 App 拖到「应用程序」覆盖旧版即可；画像、Cookie 等数据不受影响。",
    log: [],
    download_url: "https://example.com/CloakBrowser-Manager-0.8.0.dmg",
  };
  const BROWSER = { ok: true, updated: false, wrapper_version: "0.6.2", current_version: "154.0.8037.57.1", available_version: "154.0.8037.57.1", installed_version: "154.0.8037.57.1", platform: "darwin-arm64", binary_verified: true, restart_required: false, message: "内核已是最新" };

  it("shows the versions", async () => {
    await open("/settings/about", [], "关于");
    expect(await screen.findByText("v0.7.2")).toBeInTheDocument();
    expect(screen.getAllByText("145.0.7632.159.1").length).toBeGreaterThan(0);
    expect(screen.getByText("macOS")).toBeInTheDocument();
    expect(screen.getByText("还没有检查过。")).toBeInTheDocument();
    await expectNoAxeViolations(document.body);
  });

  it("finds a new version, says it needs installing, and offers a one-click update with browsers closed", async () => {
    running = 1;
    const { fetchMock } = await open(
      "/settings/about",
      [
        { path: "/api/app/update", respond: updateState() },
        { method: "POST", path: "/api/update", respond: PACKAGED_CHECK },
        { method: "POST", path: "/api/browser/update", respond: BROWSER },
      ],
      "更新",
    );
    fireEvent.click(await screen.findByRole("button", { name: "检查更新" }));
    await confirmWith("继续");
    expect(await screen.findByText("发现新版本 0.8.0，需要下载安装")).toBeInTheDocument();
    expect(screen.queryByText(/已更新/)).not.toBeInTheDocument();
    expect(screen.getByText("内核：已验证")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "手动下载安装包" })).toHaveAttribute("href", PACKAGED_CHECK.download_url);
    expect(bodies(fetchMock, "POST", "/api/update")).toHaveLength(1);
    expect(bodies(fetchMock, "POST", "/api/browser/update")).toHaveLength(1);

    const button = await screen.findByRole("button", { name: "立即更新" });
    expect(button).toBeDisabled();
    expect(screen.getAllByText("请先关闭所有浏览器").length).toBeGreaterThan(0);
    // The toolbar mentions the new version on every page.
    expect(screen.getByRole("link", { name: "新版本 0.8.0" })).toHaveAttribute("href", "/settings/about");
  });

  it("does not offer the one-click update where it is unsupported", async () => {
    running = 0;
    await open(
      "/settings/about",
      [
        { path: "/api/app/update", respond: updateState({ supported: false }) },
        { method: "POST", path: "/api/update", respond: PACKAGED_CHECK },
        { method: "POST", path: "/api/browser/update", respond: BROWSER },
      ],
      "更新",
    );
    fireEvent.click(await screen.findByRole("button", { name: "检查更新" }));
    expect(await screen.findByText("发现新版本 0.8.0，需要下载安装")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "立即更新" })).not.toBeInTheDocument();
  });

  it("starts after confirmation and shows download progress", async () => {
    let state = updateState();
    const { fetchMock } = await open(
      "/settings/about",
      [
        { path: "/api/app/update", respond: () => state },
        { method: "POST", path: "/api/app/update", respond: () => ((state = updateState({ phase: "downloading", label: "正在下载新版本", target: "0.8.0", done: 50, total: 100 })), updateState({ phase: "checking", label: "正在检查新版本" })) },
        { method: "POST", path: "/api/update", respond: PACKAGED_CHECK },
        { method: "POST", path: "/api/browser/update", respond: BROWSER },
      ],
      "更新",
    );
    fireEvent.click(await screen.findByRole("button", { name: "检查更新" }));
    fireEvent.click(await screen.findByRole("button", { name: "立即更新" }));
    await cancelDialog();
    expect(bodies(fetchMock, "POST", "/api/app/update")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "立即更新" }));
    await confirmWith("开始更新");
    expect(await screen.findByText("正在下载新版本（0.8.0） 50%", {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "更新进度" })).toHaveAttribute("aria-valuenow", "50");
    expect(bodies(fetchMock, "POST", "/api/app/update")).toHaveLength(1);
  });

  it("reloads once the new version answers", async () => {
    const reload = vi.spyOn(page, "reload").mockImplementation(() => undefined);
    let version = "0.7.2";
    mockFetch(
      shellRoutes([
        { path: "/api/app/update", respond: updateState({ phase: "restarting", label: "正在安装，应用会自动重启", target: "0.8.0" }) },
        { path: "/api/status", respond: () => ({ ...STATUS, running_count: 0, app_version: version }) },
      ]),
    );
    renderApp("/settings/about");
    expect(await screen.findByText(/新版本启动后这个页面会自动刷新/)).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
    version = "0.8.0";
    await waitFor(() => expect(reload).toHaveBeenCalledOnce(), { timeout: 5000 });
  });

  it("says the restart looks stuck after 3 minutes without the new version", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const reload = vi.spyOn(page, "reload").mockImplementation(() => undefined);
    mockFetch(shellRoutes([{ path: "/api/app/update", respond: updateState({ phase: "restarting", label: "正在安装，应用会自动重启", target: "0.8.0" }) }]));
    renderApp("/settings/about");
    expect(await screen.findByText(/新版本启动后这个页面会自动刷新/)).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(181_000);
    expect(await screen.findByText(/等了 3 分钟还没看到新版本/)).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("reports the previous update's outcome and can dismiss it", async () => {
    let result: AppUpdateState["last_result"] = {
      ok: false,
      from: "0.7.2",
      to: "0.8.0",
      running: "0.7.2",
      reason: "cannot move the current app aside (macOS App Management?)",
      finished_at: "2026-10-18T10:00:00+08:00",
    };
    const { fetchMock } = await open(
      "/settings/about",
      [
        { path: "/api/app/update", respond: () => updateState({ last_result: result }) },
        { method: "DELETE", path: "/api/app/update/result", respond: () => ((result = null), { ok: true }) },
      ],
      "更新",
    );
    expect(await screen.findByText("更新到 0.8.0 没有成功，仍在使用 0.7.2")).toBeInTheDocument();
    expect(screen.getByText(/App Management/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "更新没有成功" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭更新结果" }));
    await waitFor(() => expect(screen.queryByText(/没有成功/)).not.toBeInTheDocument());
    expect(bodies(fetchMock, "DELETE", "/api/app/update/result")).toHaveLength(1);
  });

  it("shows why an update could not start", async () => {
    await open(
      "/settings/about",
      [
        { path: "/api/app/update", respond: updateState() },
        { method: "POST", path: "/api/app/update", status: 409, respond: { detail: "一键更新前请先关闭所有浏览器" } },
        { method: "POST", path: "/api/update", respond: PACKAGED_CHECK },
        { method: "POST", path: "/api/browser/update", respond: BROWSER },
      ],
      "更新",
    );
    fireEvent.click(await screen.findByRole("button", { name: "检查更新" }));
    fireEvent.click(await screen.findByRole("button", { name: "立即更新" }));
    await confirmWith("开始更新");
    expect(await screen.findByText(/一键更新前请先关闭所有浏览器/)).toBeInTheDocument();
    expect(screen.getByText("更新没有完成")).toBeInTheDocument();
  });

  it("on a Git install says new code was pulled and a restart is needed, not that it is upgraded", async () => {
    mockFetch(
      shellRoutes([
        { path: "/api/status", respond: { ...STATUS, running_count: 0, app_version: null } },
        { path: "/api/app/update", respond: updateState({ supported: false, current_version: null }) },
        { method: "POST", path: "/api/update", respond: { ok: true, updated: true, before: "abc1234", after: "def5678", branch: "main", restart_required: true, message: "已拉取 main：abc1234 → def5678，并重建了面板。", log: [] } },
        { method: "POST", path: "/api/browser/update", respond: BROWSER },
      ]),
    );
    renderApp("/settings/about");
    expect(await screen.findByText("源码版（Git 安装）")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "拉取更新" }));
    expect(await screen.findByText("已拉取更新，需要重启才生效")).toBeInTheDocument();
    expect(screen.getByText(/已拉取 main/)).toBeInTheDocument();
    expect(screen.getByText(/请关闭当前终端里的 Manager/)).toBeInTheDocument();
  });

  it("shows why the check failed", async () => {
    await open("/settings/about", [{ method: "POST", path: "/api/update", status: 409, respond: { detail: "当前目录有未提交的修改，没有拉取。" } }], "更新");
    fireEvent.click(await screen.findByRole("button", { name: "检查更新" }));
    expect(await screen.findByText("当前目录有未提交的修改，没有拉取。")).toBeInTheDocument();
    expect(screen.getByText("检查更新失败")).toBeInTheDocument();
  });
});
