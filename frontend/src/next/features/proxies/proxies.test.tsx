import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetConnectionForTests } from "../../shared/api/connection";
import { expectNoAxeViolations, mockFetch, renderApp, shellRoutes, type MockRoute } from "../../test/utils";

const PRESETS = [
  { id: "p1", name: "美国 SOCKS5", proxy: "socks5://alice:secret@203.0.113.24:1080", mode: "socks5", created_at: "2026-10-20T08:00:00Z", updated_at: "2026-10-20T08:00:00Z" },
  { id: "p2", name: "日本 HTTP", proxy: "http://198.51.100.7:8080", mode: "http", created_at: "2026-10-21T08:00:00Z", updated_at: "2026-10-21T08:00:00Z" },
];

let presets: typeof PRESETS;

async function open(extra: MockRoute[] = []) {
  const fetchMock = mockFetch(shellRoutes([...extra, { path: "/api/proxy-presets", respond: () => presets }]));
  const utils = renderApp("/proxies");
  await screen.findByRole("heading", { name: "代理" });
  return { fetchMock, ...utils };
}

function bodies(fetchMock: ReturnType<typeof mockFetch>, method: string, url: string) {
  return fetchMock.mock.calls.filter(([u, init]) => String(u) === url && (init?.method ?? "GET") === method).map(([, init]) => JSON.parse(String((init as RequestInit).body)));
}

beforeEach(() => {
  presets = PRESETS;
  resetConnectionForTests();
});

afterEach(() => vi.unstubAllGlobals());

describe("saved proxies", () => {
  it("lists saved proxies without showing their passwords", async () => {
    await open();
    const row = await screen.findByRole("row", { name: /美国 SOCKS5/ });
    expect(within(row).getByText("socks5://alice:***@203.0.113.24:1080")).toBeInTheDocument();
    expect(screen.queryByText(/secret/)).not.toBeInTheDocument();
    expect(screen.getByText(/共 2 个保存的代理/)).toBeInTheDocument();
  });

  it("shows an empty state when nothing is saved", async () => {
    presets = [];
    await open();
    expect(await screen.findByText("还没有保存的代理")).toBeInTheDocument();
  });

  it("deletes after confirmation, saying profiles keep their own copy", async () => {
    const { fetchMock } = await open([{ method: "DELETE", path: "/api/proxy-presets/p2", respond: { ok: true } }]);
    fireEvent.click(await screen.findByRole("button", { name: "删除「日本 HTTP」" }));
    const dialog = await screen.findByRole("dialog", { name: "删除代理「日本 HTTP」？" });
    expect(dialog).toHaveTextContent("已经在用这个代理的环境不受影响");
    fireEvent.click(within(dialog).getByRole("button", { name: "删除" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, init]) => String(u) === "/api/proxy-presets/p2" && init?.method === "DELETE")).toBe(true));
  });

  it("checks a saved proxy's exit", async () => {
    const { fetchMock } = await open([
      { method: "POST", path: "/api/proxy/test", respond: { ok: true, ip: "203.0.113.24", country: "United States", country_code: "US", region: "WA", city: "Seattle", timezone: "America/Los_Angeles", suggested_locale: "en-US", org: "Example ISP", asn: "AS1", source: "t", ip_quality: { verdict: "clean", summary: "没有被标记", signals: [], links: [] } } },
    ]);
    fireEvent.click(await screen.findByRole("button", { name: "检测「美国 SOCKS5」的出口" }));
    const dialog = await screen.findByRole("dialog", { name: "检测「美国 SOCKS5」" });
    fireEvent.click(within(dialog).getByRole("button", { name: "开始检测" }));
    expect(await within(dialog).findByText("America/Los_Angeles")).toBeInTheDocument();
    expect(within(dialog).getByText("IP 质量：未标记")).toBeInTheDocument();
    expect(bodies(fetchMock, "POST", "/api/proxy/test")[0]).toEqual({ proxy: "socks5://alice:secret@203.0.113.24:1080" });
  });

  it("has no accessibility violations", async () => {
    const { container } = await open();
    await screen.findByRole("row", { name: /美国 SOCKS5/ });
    await expectNoAxeViolations(container);
  });
});

describe("adding", () => {
  it("builds the address from its parts and saves it", async () => {
    const { fetchMock } = await open([{ method: "POST", path: "/api/proxy-presets", respond: { ...PRESETS[0], id: "p3" } }]);
    fireEvent.change(screen.getByLabelText(/^代理名称/), { target: { value: "新加坡" } });
    fireEvent.change(screen.getByPlaceholderText("192.168.100.1 或 proxy.example.com"), { target: { value: "2001:db8::1" } });
    fireEvent.change(screen.getByPlaceholderText("1090"), { target: { value: "1080" } });
    fireEvent.change(screen.getByLabelText("代理账号"), { target: { value: "u" } });
    fireEvent.change(screen.getByLabelText("代理密码"), { target: { value: "p w" } });
    expect(screen.getByLabelText("将保存的地址")).toHaveTextContent("socks5://u:***@[2001:db8::1]:1080");
    fireEvent.click(screen.getByRole("button", { name: "保存代理" }));
    await waitFor(() => expect(bodies(fetchMock, "POST", "/api/proxy-presets")[0]).toEqual({ name: "新加坡", proxy: "socks5://u:p%20w@[2001:db8::1]:1080", mode: "socks5" }));
    expect(await screen.findByText("已保存「新加坡」")).toBeInTheDocument();
  });

  it("asks for a name, then for an address", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "保存代理" }));
    expect(await screen.findByText("请先填写代理名称")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^代理名称/), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "保存代理" }));
    expect(await screen.findByText("请填写主机和端口")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("代理类型"), { target: { value: "vless" } });
    fireEvent.click(screen.getByRole("button", { name: "保存代理" }));
    expect(await screen.findByText("请粘贴代理链接")).toBeInTheDocument();
  });

  it("shows the backend's reason when it refuses", async () => {
    await open([{ method: "POST", path: "/api/proxy-presets", status: 400, respond: { detail: "代理端口无效" } }]);
    fireEvent.change(screen.getByLabelText(/^代理名称/), { target: { value: "x" } });
    fireEvent.change(screen.getByPlaceholderText("192.168.100.1 或 proxy.example.com"), { target: { value: "1.2.3.4" } });
    fireEvent.change(screen.getByPlaceholderText("1090"), { target: { value: "99999" } });
    fireEvent.click(screen.getByRole("button", { name: "保存代理" }));
    expect(await screen.findByText("代理端口无效")).toBeInTheDocument();
  });

  it("previews a batch before saving it, skipping lines it cannot read", async () => {
    const { fetchMock } = await open([{ method: "POST", path: "/api/proxy-presets/bulk", respond: [] }]);
    fireEvent.mouseDown(screen.getByRole("tab", { name: "批量导入" }), { button: 0 });
    const box = await screen.findByLabelText("批量代理");
    fireEvent.change(box, { target: { value: "192.168.0.1:8000\n# 注释\nsocks5://u:p@10.0.0.1:1080\n不是代理\n10.0.0.2:9000:user:pass" } });
    const preview = screen.getByRole("list", { name: "将保存的代理" });
    expect(within(preview).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("1 行无法识别，会跳过")).toBeInTheDocument();
    expect(within(preview).getByText("socks5://u:***@10.0.0.1:1080")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存 3 个代理" }));
    await waitFor(() => expect(bodies(fetchMock, "POST", "/api/proxy-presets/bulk")[0].items).toEqual([
      { name: "SOCKS5 192.168.0.1:8000", proxy: "socks5://192.168.0.1:8000", mode: "socks5" },
      { name: "SOCKS5 10.0.0.1:1080", proxy: "socks5://u:p@10.0.0.1:1080", mode: "socks5" },
      { name: "SOCKS5 10.0.0.2:9000", proxy: "socks5://user:pass@10.0.0.2:9000", mode: "socks5" },
    ]));
    expect(await screen.findByText("已保存 3 个代理")).toBeInTheDocument();
  });
});
