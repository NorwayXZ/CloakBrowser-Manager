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
  sessionStorage.clear();
  presets = PRESETS;
  resetConnectionForTests();
});

afterEach(() => vi.unstubAllGlobals());

describe("relay nodes", () => {
  it("adds an encrypted relay independently of saved final proxies", async () => {
    const relays: object[] = [];
    const { fetchMock } = await open([
      { path: "/api/relay-nodes", respond: () => relays },
      { method: "POST", path: "/api/relay-nodes", respond: (body: unknown) => {
        const item = { ...(body as object), id: "relay-1", profile_count: 0, created_at: "2026-10-30", updated_at: "2026-10-30" };
        relays.push(item); return item;
      } },
    ]);
    fireEvent.mouseDown(screen.getByRole("tab", { name: "中转服务器" }), { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("button", { name: "添加中转服务器" }));
    const dialog = await screen.findByRole("dialog", { name: "添加中转服务器" });
    fireEvent.change(within(dialog).getByLabelText("中转名称"), { target: { value: "美国中转" } });
    fireEvent.change(within(dialog).getByLabelText("中转连接链接"), { target: { value: "trojan://private-password@relay.example:443" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "保存中转服务器" }));
    await screen.findByRole("row", { name: /美国中转/ });
    expect(screen.queryByText(/private-password/)).not.toBeInTheDocument();
    expect(bodies(fetchMock, "POST", "/api/relay-nodes")[0]).toEqual({ name: "美国中转", proxy: "trojan://private-password@relay.example:443" });
    expect(bodies(fetchMock, "POST", "/api/proxy-presets")).toHaveLength(0);
  });
});

it("saves the refresh link without executing it and rotates through the Manager only", async () => {
  let ready=false;
  const { fetchMock }=await open([
    {path:"/api/proxy-presets",respond:()=>[{...PRESETS[0],can_rotate_ip:ready}]},
    {path:"/api/proxy-presets/p1/rotation-settings",respond:{url:"",method:"GET",cooldown_seconds:60,shared_group:"",headers:{},body:null}},
    {method:"PUT",path:"/api/proxy-presets/p1/rotation-settings",respond:()=>{ready=true;return {ok:true};}},
    {path:"/api/proxy-presets/p1/capabilities",respond:{proxy_id:"p1",can_rotate_ip:true,affected_profile_ids:["profile-a"]}},
    {method:"POST",path:"/api/proxy-presets/p1/rotate",respond:{id:"job1",state:"queued"}},
    {path:"/api/proxy-rotations/job1",respond:{id:"job1",state:"verified",before_ip:"203.0.113.1",after_ip:"203.0.113.2",requires_reconnect:true}},
  ]);
  fireEvent.click(await screen.findByRole("button",{name:"切换链接"}));
  const dialog=await screen.findByRole("dialog",{name:"配置一键换 IP"});
  await waitFor(()=>expect(within(dialog).getByRole("button",{name:"保存切换设置"})).not.toBeDisabled());
  fireEvent.change(within(dialog).getByLabelText("换 IP 链接"),{target:{value:"https://supplier.example/refresh?token=PRIVATE_SECRET"}});
  fireEvent.click(within(dialog).getByRole("button",{name:"保存切换设置"}));
  await waitFor(()=>expect(screen.queryByRole("dialog",{name:"配置一键换 IP"})).not.toBeInTheDocument());
  const rotate=screen.getByRole("button",{name:"一键切换 IP"});
  await waitFor(()=>expect(rotate).not.toBeDisabled());
  expect(bodies(fetchMock,"POST","/api/proxy-presets/p1/rotate")).toHaveLength(0);
  fireEvent.click(rotate);
  await screen.findByText("已确认换 IP",{}, {timeout:4500});
  expect(screen.getByText(/203.0.113.1.*203.0.113.2/)).toBeInTheDocument();
  expect(bodies(fetchMock,"POST","/api/proxy-presets/p1/rotate")).toHaveLength(1);
  expect(fetchMock.mock.calls.every(([url])=>!String(url).includes("supplier.example"))).toBe(true);
  expect(screen.queryByText(/PRIVATE_SECRET/)).not.toBeInTheDocument();
});

it("preserves the request id after a lost response instead of rotating again", async () => {
  let calls=0;
  const {fetchMock}=await open([
    {path:"/api/proxy-presets",respond:()=>[{...PRESETS[0],can_rotate_ip:true}]},
    {path:"/api/proxy-presets/p1/capabilities",respond:{proxy_id:"p1",can_rotate_ip:true}},
    {method:"POST",path:"/api/proxy-presets/p1/rotate",respond:()=>{
      calls++;
      if(calls===1)throw new TypeError("lost response");
      return {id:"job1",state:"verified",before_ip:"203.0.113.1",after_ip:"203.0.113.2"};
    }},
  ]);
  fireEvent.click(await screen.findByRole("button",{name:"一键切换 IP"}));
  await screen.findByText(/请求结果未知/);
  const saved=sessionStorage.getItem("proxy-rotation:p1:");
  expect(saved).toBeTruthy();
  fireEvent.click(within(screen.getByRole("dialog",{name:"IP 切换结果"})).getByRole("button",{name:"查询本次请求"}));
  await screen.findByText("已确认换 IP");
  const requests=bodies(fetchMock,"POST","/api/proxy-presets/p1/rotate");
  expect(requests).toHaveLength(2);
  expect(requests[0].request_id).toBe(saved);
  expect(requests[1].request_id).toBe(saved);
  expect(sessionStorage.getItem("proxy-rotation:p1:")).toBeNull();
});

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
