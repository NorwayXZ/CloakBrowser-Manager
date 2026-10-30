import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetConnectionForTests } from "../../shared/api/connection";
import { expectNoAxeViolations, mockFetch, renderApp, shellRoutes, STATUS, type MockRoute } from "../../test/utils";
import { makeProfile } from "../profiles/testing";
import type { Profile } from "../profiles/types";

const EXISTING = makeProfile({ id: "profile-1", name: "Awscnn", browser_engine: "cloakbrowser", fingerprint_seed: 12345, humanize: true });

let profiles: Profile[];

function routes(hostOS: "macos" | "windows" | "linux" = "macos", hostScreen: number[] | null = null, extra: MockRoute[] = []): MockRoute[] {
  return shellRoutes([
    ...extra,
    { path: "/api/status", respond: { ...STATUS, host_os: hostOS, host_screen: hostScreen } },
    { path: "/api/profiles", respond: () => profiles },
    { path: "/api/groups", respond: [] },
    { path: "/api/proxy-presets", respond: [] },
    { path: "/api/warmup/targets", respond: [{ id: "amazon", name: "Amazon" }, { id: "facebook", name: "Facebook" }] },
    { method: "POST", path: "/api/profiles", respond: (body: unknown) => ({ ...EXISTING, ...(body as object), id: "new-1" }) },
    { method: "PUT", path: /\/api\/profiles\/profile-1$/, respond: (body: unknown) => ({ ...EXISTING, ...(body as object) }) },
  ]);
}

async function openEditor(path: string, hostOS: "macos" | "windows" | "linux" = "macos", hostScreen: number[] | null = null, extra: MockRoute[] = []) {
  const fetchMock = mockFetch(routes(hostOS, hostScreen, extra));
  const utils = renderApp(path);
  await screen.findByRole("textbox", { name: /^名称/ });
  return { fetchMock, ...utils };
}

function saved(fetchMock: ReturnType<typeof mockFetch>, method = "POST") {
  const pattern = method === "POST" ? /\/api\/profiles$/ : /\/api\/profiles\/profile-1$/;
  const call = fetchMock.mock.calls.filter(([url, init]) => (init?.method ?? "GET") === method && pattern.test(String(url))).at(-1);
  return call ? JSON.parse(String((call[1] as RequestInit).body)) : undefined;
}

function setName(value: string) {
  fireEvent.change(screen.getByRole("textbox", { name: /^名称/ }), { target: { value } });
}

async function create(fetchMock: ReturnType<typeof mockFetch>) {
  fireEvent.click(screen.getByRole("button", { name: /^创建/ }));
  await waitFor(() => expect(saved(fetchMock)).toBeDefined());
  return saved(fetchMock);
}

function radio(group: string, name: string) {
  return within(screen.getByRole("radiogroup", { name: group })).getByRole("radio", { name });
}

beforeEach(() => {
  profiles = [EXISTING];
  window.sessionStorage.clear();
  resetConnectionForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("persists a relay per environment and compares both paths using the same final SOCKS5", async () => {
  const relay = { id: "relay-us", name: "美国中转", proxy: "trojan://secret@relay.example:443", created_at: "2026-10-30", updated_at: "2026-10-30" };
  const { fetchMock } = await openEditor("/profiles/new", "macos", null, [
    { path: "/api/relay-nodes", respond: [relay] },
    { method: "POST", path: "/api/proxy/test", respond: { ok: true, ip: "203.0.113.99", elapsed_ms: 123, country: "US" } },
  ]);
  setName("独立 SOCKS5 环境");
  fireEvent.click(radio("代理方式", "自定义代理"));
  fireEvent.change(screen.getByLabelText("代理类型"), { target: { value: "socks5" } });
  fireEvent.change(screen.getByPlaceholderText("192.168.100.1"), { target: { value: "exit.example" } });
  fireEvent.change(screen.getByPlaceholderText("1090"), { target: { value: "1080" } });
  fireEvent.change(screen.getByLabelText("SOCKS5 连接方式"), { target: { value: "relay" } });
  await screen.findByRole("option", { name: "美国中转" });
  fireEvent.change(screen.getByLabelText("中转服务器"), { target: { value: "relay-us" } });
  fireEvent.click(screen.getByRole("button", { name: "对比直连与中转" }));
  await screen.findByText(/检测耗时包含出口信息查询/);
  const calls = fetchMock.mock.calls.filter(([url]) => String(url) === "/api/proxy/test").map(([, init]) => JSON.parse(String(init?.body)));
  expect(calls).toEqual([{ proxy: "socks5://exit.example:1080" }, { proxy: "socks5://exit.example:1080", proxy_connection_mode: "relay", relay_id: "relay-us" }]);
  const payload = await create(fetchMock);
  expect(payload.proxy).toBe("socks5://exit.example:1080");
  expect(payload.proxy_connection_mode).toBe("relay");
  expect(payload.relay_id).toBe("relay-us");
});

describe("proxy mode", () => {
  it("creates a direct profile without a proxy value", async () => {
    const { fetchMock } = await openEditor("/profiles/new", "windows");
    expect(radio("代理方式", "直连")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("直连已启用")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "主机" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /根据出口 IP/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: "检查直连出口" })).toBeInTheDocument();
    setName("Direct profile");
    const body = await create(fetchMock);
    expect(body.proxy ?? null).toBeNull();
    expect(body.geoip).toBe(true);
  });

  it("clears a custom proxy when direct mode is selected", async () => {
    const { fetchMock } = await openEditor("/profiles/new");
    setName("Switch to direct");
    fireEvent.click(radio("代理方式", "自定义代理"));
    fireEvent.change(screen.getByPlaceholderText("192.168.100.1"), { target: { value: "127.0.0.1" } });
    fireEvent.change(screen.getByPlaceholderText("1090"), { target: { value: "1080" } });
    fireEvent.click(radio("代理方式", "直连"));
    expect((await create(fetchMock)).proxy).toBeNull();
  });

  it("builds an authenticated SOCKS5 address and fills from a saved proxy", async () => {
    const { fetchMock } = await openEditor("/profiles/new", "macos", null, [
      { path: "/api/proxy-presets", respond: [{ id: "pp", name: "日本 HTTP", proxy: "http://198.51.100.7:8080", mode: "http" }] },
    ]);
    setName("Proxied");
    fireEvent.click(radio("代理方式", "自定义代理"));
    fireEvent.change(screen.getByLabelText("代理类型"), { target: { value: "socks5" } });
    fireEvent.change(screen.getByPlaceholderText("192.168.100.1"), { target: { value: "203.0.113.9" } });
    fireEvent.change(screen.getByPlaceholderText("1090"), { target: { value: "1080" } });
    fireEvent.change(screen.getByLabelText("代理账号"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("代理密码"), { target: { value: "p@ss" } });
    expect(screen.getByText("socks5://alice:***@203.0.113.9:1080")).toBeInTheDocument();
    expect((await create(fetchMock)).proxy).toBe("socks5://alice:p%40ss@203.0.113.9:1080");

    await waitFor(() => expect(screen.queryByRole("textbox", { name: /^名称/ })).not.toBeInTheDocument());
  });

  it("uses a saved proxy", async () => {
    const { fetchMock } = await openEditor("/profiles/new", "macos", null, [
      { path: "/api/proxy-presets", respond: [{ id: "pp", name: "日本 HTTP", proxy: "http://198.51.100.7:8080", mode: "http" }] },
    ]);
    setName("Preset");
    const select = await screen.findByLabelText("已保存代理");
    await within(select).findByRole("option", { name: "日本 HTTP · HTTP" });
    fireEvent.change(select, { target: { value: "pp" } });
    expect(screen.getByPlaceholderText("192.168.100.1")).toHaveValue("198.51.100.7");
    expect((await create(fetchMock)).proxy).toBe("http://198.51.100.7:8080");
  });
});

describe("extra fingerprint options", () => {
  it("saves brand, WebRTC and cookie options with the profile", async () => {
    const { fetchMock } = await openEditor("/profiles/new", "windows");
    setName("Edge profile");
    fireEvent.change(screen.getByLabelText("浏览器品牌"), { target: { value: "Edge" } });
    fireEvent.click(radio("WebRTC", "指定 IP"));
    fireEvent.change(screen.getByPlaceholderText("例如 203.0.113.9"), { target: { value: "203.0.113.9" } });
    fireEvent.click(radio("地理位置", "禁止"));
    fireEvent.click(screen.getByRole("checkbox", { name: /跨电脑 Cookie/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Windows 语音列表/ }));
    expect((await create(fetchMock)).fingerprint_options).toEqual({
      noise: false,
      storage_quota_mb: 50000,
      brand: "Edge",
      webrtc: "custom",
      webrtc_ip: "203.0.113.9",
      geolocation: "block",
      portable_cookies: true,
      speech_voices: false,
    });
  });

  it("applies the recommended noise and quota preset to new profiles", async () => {
    const { fetchMock } = await openEditor("/profiles/new", "windows");
    setName("Preset");
    const body = await create(fetchMock);
    expect(body.fingerprint_options.noise).toBe(false);
    expect(body.fingerprint_options.storage_quota_mb).toBe(50000);
  });

  it("rolls the noise and quota preset back to kernel defaults", async () => {
    const { fetchMock } = await openEditor("/profiles/new", "windows");
    fireEvent.click(radio("指纹噪声", "自动"));
    fireEvent.click(radio("存储配额", "按种子自动"));
    setName("Rollback");
    const body = await create(fetchMock);
    expect(body.fingerprint_options.noise).toBeNull();
    expect(body.fingerprint_options.storage_quota_mb).toBeNull();
  });

  it("keeps transparent proxy off until a proxy is set", async () => {
    await openEditor("/profiles/new");
    expect(screen.getByRole("checkbox", { name: /透明代理/ })).toBeDisabled();
    expect(screen.queryByRole("checkbox", { name: /Windows 语音列表/ })).not.toBeInTheDocument();
  });

  it("moves between segment choices with the arrow keys", async () => {
    await openEditor("/profiles/new");
    const auto = radio("指纹噪声", "关闭");
    auto.focus();
    fireEvent.keyDown(auto, { key: "ArrowLeft" });
    expect(radio("指纹噪声", "开启")).toHaveAttribute("aria-checked", "true");
    expect(radio("指纹噪声", "开启")).toHaveFocus();
  });

  it("hides the extra options for system Chrome", async () => {
    await openEditor("/profiles/new");
    fireEvent.change(screen.getByLabelText("浏览器"), { target: { value: "system_chrome" } });
    expect(screen.queryByRole("radiogroup", { name: "WebRTC" })).not.toBeInTheDocument();
    expect(screen.getByText(/不支持浏览器品牌、WebRTC IP 等额外伪装项/)).toBeInTheDocument();
  });
});

describe("exit check", () => {
  it("shows whether the exit IP is flagged as a proxy, and applies its timezone when following the IP", async () => {
    const { fetchMock } = await openEditor("/profiles/new", "macos", null, [
      {
        method: "POST",
        path: "/api/proxy/test",
        respond: {
          ok: true, ip: "150.31.13.127", country: "Japan", country_code: "JP", suggested_locale: "ja-JP", region: null, city: "Toyama",
          timezone: "Asia/Tokyo", org: "IIJ", asn: "AS2497", source: "test", connection_mode: "direct",
          ip_quality: {
            verdict: "flagged",
            summary: "已被标记为代理 / VPN / 机房 IP（proxycheck.io）：网站能看出你在用代理",
            signals: [
              { source: "proxycheck.io", status: "flagged", detail: "代理（Shadowsocks，风险 66）" },
              { source: "ip-api.com", status: "clean", detail: "没有标记（家庭宽带，IIJ）" },
            ],
            links: [{ name: "Scamalytics", url: "https://scamalytics.com/ip/150.31.13.127" }],
          },
        },
      },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "检查直连出口" }));
    const panel = await screen.findByTestId("ip-quality");
    expect(panel).toHaveTextContent("IP 质量：已被标记");
    expect(panel).toHaveTextContent("proxycheck.io：已被标记 · 代理（Shadowsocks，风险 66）");
    expect(within(panel).getByRole("link", { name: "Scamalytics" })).toHaveAttribute("href", "https://scamalytics.com/ip/150.31.13.127");
    expect(screen.getByLabelText("时区")).toHaveValue("Asia/Tokyo");
    expect(screen.getByLabelText("语言区域")).toHaveValue("ja-JP");
    setName("Checked");
    expect((await create(fetchMock)).timezone).toBe("Asia/Tokyo");
  });

  it("asks for an address before checking a custom proxy", async () => {
    await openEditor("/profiles/new");
    fireEvent.click(radio("代理方式", "自定义代理"));
    expect(screen.getByRole("button", { name: "检查代理" })).toBeDisabled();
  });
});

describe("screen and browser language", () => {
  it("follows the computer's screen by default and can switch to a preset", async () => {
    const { fetchMock } = await openEditor("/profiles/new", "macos", [2560, 1440]);
    const picker = screen.getByRole("combobox", { name: "分辨率" });
    expect(picker).toHaveValue("real");
    expect(screen.getByRole("option", { name: "跟随电脑屏幕 2560 × 1440（推荐）" })).toBeInTheDocument();
    fireEvent.change(picker, { target: { value: "1920 × 1080 (Windows 常见)" } });
    setName("Custom screen");
    const body = await create(fetchMock);
    expect(body.fingerprint_options.screen).toBe("custom");
    expect([body.screen_width, body.screen_height]).toEqual([1920, 1080]);
  });

  it("hides the follow option when the screen cannot be read", async () => {
    await openEditor("/profiles/new", "windows");
    const picker = screen.getByRole("combobox", { name: "分辨率" });
    expect(within(picker).queryByRole("option", { name: /跟随电脑屏幕/ })).not.toBeInTheDocument();
  });

  it("saves a fixed browser language", async () => {
    const { fetchMock } = await openEditor("/profiles/new");
    fireEvent.change(screen.getByRole("combobox", { name: "浏览器语言" }), { target: { value: "zh-CN" } });
    setName("Chinese UI");
    expect((await create(fetchMock)).fingerprint_options.language).toBe("zh-CN");
  });
});

describe("cookies", () => {
  it("merges pasted Name=Value cookies through the backend", async () => {
    const { fetchMock } = await openEditor("/profiles/new", "macos", null, [
      { method: "POST", path: "/api/cookies/merge", respond: { cookies_json: '[{"name":"sid","value":"abc","domain":".example.com","path":"/"}]', format: "header", added: 1, total: 1 } },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "合并 Cookie" }));
    fireEvent.change(screen.getByPlaceholderText(/粘贴要加进来的 Cookie/), { target: { value: "sid=abc" } });
    fireEvent.change(screen.getByPlaceholderText(/网站域名/), { target: { value: "example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "合并" }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url) === "/api/cookies/merge");
      expect(JSON.parse(String((call?.[1] as RequestInit).body))).toEqual({ text: "sid=abc", existing: null, domain: "example.com" });
    });
    expect(await screen.findByText(/已合并 1 条（Name=Value），现在共 1 条/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/支持 JSON、Netscape/)).toHaveValue('[{"name":"sid","value":"abc","domain":".example.com","path":"/"}]');
  });

  it("shows the merge error from the backend", async () => {
    await openEditor("/profiles/new", "macos", null, [{ method: "POST", path: "/api/cookies/merge", status: 400, respond: { detail: "Name=Value 格式不带域名" } }]);
    fireEvent.click(screen.getByRole("button", { name: "合并 Cookie" }));
    fireEvent.change(screen.getByPlaceholderText(/粘贴要加进来的 Cookie/), { target: { value: "sid=abc" } });
    fireEvent.click(screen.getByRole("button", { name: "合并" }));
    expect(await screen.findByText("Name=Value 格式不带域名")).toBeInTheDocument();
  });

  it("pulls the running browser's cookies back into the form", async () => {
    const pulled = '[{"name":"sid","value":"abc","domain":".example.com","path":"/"}]';
    const { fetchMock } = await openEditor("/profiles/profile-1/edit", "macos", null, [
      { method: "POST", path: "/api/profiles/profile-1/cookies/pull", respond: { cookies_json: pulled, count: 1 } },
    ]);
    fireEvent.click(screen.getByRole("button", { name: /从浏览器导回 Cookie/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/profiles/profile-1/cookies/pull")).toBe(true));
    expect(await screen.findByText(/已从浏览器导回 1 条 Cookie/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/支持 JSON、Netscape/)).toHaveValue(pulled);
  });

  it("shows the backend error when the browser cannot be read", async () => {
    await openEditor("/profiles/profile-1/edit", "macos", null, [
      { method: "POST", path: "/api/profiles/profile-1/cookies/pull", status: 409, respond: { detail: "浏览器没有在运行：请先启动这个浏览器，再导回它的 Cookie" } },
    ]);
    fireEvent.click(screen.getByRole("button", { name: /从浏览器导回 Cookie/ }));
    expect(await screen.findByText(/浏览器没有在运行/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/支持 JSON、Netscape/)).toHaveValue("");
  });

  it("exports cookies in the chosen format", async () => {
    const createObjectURL = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
    const clicks = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const { fetchMock } = await openEditor("/profiles/profile-1/edit", "macos", null, [{ path: /\/cookies\/export/, respond: [] }]);
    fireEvent.change(screen.getByLabelText("导出格式"), { target: { value: "netscape" } });
    fireEvent.click(screen.getByRole("button", { name: /导出 Cookie/ }));
    expect(await screen.findByText("Cookie 文件已开始下载")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/profiles/profile-1/cookies/export?format=netscape")).toBe(true);
    expect(clicks).toHaveBeenCalled();
    expect((clicks.mock.contexts[0] as HTMLAnchorElement).download).toBe("Awscnn-cookies.txt");
  });

  it("hides pull and export until the profile exists", async () => {
    await openEditor("/profiles/new");
    expect(screen.queryByRole("button", { name: /从浏览器导回 Cookie/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /导出 Cookie/ })).not.toBeInTheDocument();
  });
});

describe("layout and summary", () => {
  it("lists every form section in the section navigation", async () => {
    await openEditor("/profiles/new", "windows");
    const nav = screen.getByRole("navigation", { name: "表单分区" });
    expect(within(nav).getAllByRole("button").map((b) => b.textContent)).toEqual(["基础设置", "代理信息", "指纹配置", "更多指纹", "高级设置"]);
    for (const id of ["basic", "proxy", "fingerprint", "more-fingerprint", "advanced"]) expect(document.getElementById(`form-${id}`)).toBeInTheDocument();
  });

  it("summarises the geolocation and WebRTC choices", async () => {
    await openEditor("/profiles/new", "windows");
    const summary = screen.getByRole("complementary", { name: "概要" });
    expect(within(summary).getByText("真实（直连）")).toBeInTheDocument();
    expect(within(summary).getByText("基于 IP")).toBeInTheDocument();
    fireEvent.click(radio("地理位置", "禁止"));
    expect(within(summary).getByText("禁止")).toBeInTheDocument();
    expect(within(screen.getByRole("radiogroup", { name: "WebRTC" })).queryByRole("radio", { name: /禁用/ })).not.toBeInTheDocument();
  });

  it("swaps to another device of this computer's platform", async () => {
    await openEditor("/profiles/new");
    const device = screen.getByLabelText("设备画像");
    const before = (device as HTMLSelectElement).value;
    fireEvent.click(screen.getByRole("button", { name: "随机设备画像" }));
    expect((device as HTMLSelectElement).value).not.toBe(before);
    expect(within(screen.getByRole("complementary", { name: "概要" })).getByText("macOS")).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = await openEditor("/profiles/profile-1/edit");
    await expectNoAxeViolations(container);
  });
});

describe("warm-up", () => {
  it("shows the target-aging copy, age stats and saves warm-up fields", async () => {
    profiles = [{ ...EXISTING, warmup_enabled: true, warmup_daily_max: 1, warmup_targets: ["amazon"] }];
    const { fetchMock } = await openEditor("/profiles/profile-1/edit", "macos", null, [
      {
        path: "/api/profiles/profile-1/warmup",
        respond: {
          age: { created_at: "2026-10-01T00:00:00Z", age_days: 21, warmup_sessions: 3, last_warmup_at: "2026-10-21T08:00:00Z" },
          runs: [{ id: "run-1", started_at: "2026-10-21T08:00:00Z", pages_visited: 6, status: "ok", reason: null }],
          warming: false,
        },
      },
      { path: "/api/profiles/profile-1/warmup/scripts", respond: { llm_configured: false, generating: false, last_generation: null, batches: [] } },
      { path: "/api/automation/hours", respond: { hours: null, open_now: true } },
    ]);
    expect(await screen.findByText(/定向养护：在目标平台留下并积累第一方 Cookie 年龄/)).toBeInTheDocument();
    expect(await screen.findByText(/已养号 3 次/)).toBeInTheDocument();
    expect(screen.getByText(/6 页/)).toBeInTheDocument();
    expect(await screen.findByText(/还没有配置 AI 接口/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Facebook" }));
    fireEvent.click(screen.getByRole("button", { name: /^保存/ }));
    await waitFor(() => expect(saved(fetchMock, "PUT")).toBeDefined());
    const body = saved(fetchMock, "PUT");
    expect(body.warmup_enabled).toBe(true);
    expect(body.warmup_targets).toEqual(["amazon", "facebook"]);
  });

  it("keeps warm-up controls hidden until enabled", async () => {
    await openEditor("/profiles/new", "windows");
    expect(screen.getByText("养号（定时自动浏览养护）")).toBeInTheDocument();
    expect(screen.queryByText(/定向养护：在目标平台/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /养号/ }));
    expect(await screen.findByText(/定向养护：在目标平台/)).toBeInTheDocument();
  });

  it("approves an AI script batch and runs a warm-up on demand", async () => {
    profiles = [{ ...EXISTING, warmup_enabled: true }];
    const { fetchMock } = await openEditor("/profiles/profile-1/edit", "macos", null, [
      { path: "/api/profiles/profile-1/warmup", respond: { age: { created_at: null, age_days: null, warmup_sessions: 0, last_warmup_at: null }, runs: [], warming: false } },
      {
        path: "/api/profiles/profile-1/warmup/scripts",
        respond: {
          llm_configured: true, generating: false, last_generation: null,
          batches: [{ batch_id: "b1", created_at: "2026-10-24T08:00:00Z", status: "draft", model: "m", scripts: [{ id: "s1", theme: "周末露营", steps: [{ kind: "target", platform: "youtube", platform_name: "YouTube", search_query: "露营装备", dwell: "long", follow_link: true }] }] }],
        },
      },
      { method: "POST", path: /\/batches\/b1\/approve$/, respond: { ok: true } },
      { method: "POST", path: "/api/profiles/profile-1/warmup/run", respond: { ok: true, started: true } },
      { path: "/api/automation/hours", respond: { hours: "09-18", open_now: false } },
    ]);
    expect(await screen.findByText("YouTube · 搜「露营装备」 · 长停 · 跟一条链接")).toBeInTheDocument();
    expect(screen.getByText(/当前不在自动化时段（09-18）内/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "整批批准" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => /\/batches\/b1\/approve$/.test(String(url)))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "立即养一次" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/profiles/profile-1/warmup/run")).toBe(true));
  });
});

describe("saving and leaving", () => {
  it("requires a name and focuses it", async () => {
    const { fetchMock } = await openEditor("/profiles/new");
    fireEvent.click(screen.getByRole("button", { name: /^创建/ }));
    expect(await screen.findByText("请填写名称")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /^名称/ })).toHaveFocus();
    expect(saved(fetchMock)).toBeUndefined();
  });

  it("saves with ⌘/Ctrl+S, then returns to the list with the profile open", async () => {
    const { fetchMock, router } = await openEditor("/profiles/profile-1/edit");
    setName("改过的名字");
    expect(screen.getByText("有未保存的修改")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "s", ctrlKey: true, metaKey: true });
    await waitFor(() => expect(saved(fetchMock, "PUT")?.name).toBe("改过的名字"));
    await waitFor(() => expect(router.state.location.pathname).toBe("/profiles"));
    expect(router.state.location.search).toBe("?p=profile-1");
    expect(await screen.findByText("已保存「改过的名字」")).toBeInTheDocument();
  });

  it("shows why the backend refused, and stays", async () => {
    const { router } = await openEditor("/profiles/profile-1/edit", "macos", null, [
      { method: "PUT", path: /\/api\/profiles\/profile-1$/, status: 422, respond: { detail: [{ msg: "端口必须是 1–65535" }] } },
    ]);
    setName("x");
    fireEvent.click(screen.getByRole("button", { name: /^保存/ }));
    expect(await screen.findByText("端口必须是 1–65535")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/profiles/profile-1/edit");
  });

  it("asks before leaving with unsaved changes", async () => {
    const { router } = await openEditor("/profiles/profile-1/edit");
    setName("没保存");
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    const dialog = await screen.findByRole("dialog", { name: "放弃没保存的修改？" });
    fireEvent.click(within(dialog).getByRole("button", { name: "继续编辑" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(router.state.location.pathname).toBe("/profiles/profile-1/edit");
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent.click(within(await screen.findByRole("dialog", { name: "放弃没保存的修改？" })).getByRole("button", { name: "放弃修改" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/profiles"));
  });

  it("leaves without asking when nothing changed", async () => {
    const { router } = await openEditor("/profiles/profile-1/edit");
    expect(screen.getByText("没有修改")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/profiles"));
  });

  it("offers to restore an unsaved draft after a reload", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const first = await openEditor("/profiles/profile-1/edit");
    setName("草稿名字");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    vi.useRealTimers();
    first.unmount();

    await openEditor("/profiles/profile-1/edit");
    expect(screen.getByText("有一份没保存的修改")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /^名称/ })).toHaveValue("Awscnn");
    fireEvent.click(screen.getByRole("button", { name: "恢复" }));
    expect(screen.getByRole("textbox", { name: /^名称/ })).toHaveValue("草稿名字");
    expect(screen.getByText("有未保存的修改")).toBeInTheDocument();
  });

  it("moves the profile to the trash from the editor", async () => {
    const { fetchMock, router } = await openEditor("/profiles/profile-1/edit", "macos", null, [{ method: "DELETE", path: "/api/profiles/profile-1", respond: { ok: true } }]);
    fireEvent.click(screen.getByRole("button", { name: "移到回收站" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => init?.method === "DELETE" && String(url) === "/api/profiles/profile-1")).toBe(true));
    await waitFor(() => expect(router.state.location.pathname).toBe("/profiles"));
  });

  it("says so when the profile does not exist", async () => {
    mockFetch(routes());
    renderApp("/profiles/nope/edit");
    expect(await screen.findByText("没有这个环境")).toBeInTheDocument();
  });
});
