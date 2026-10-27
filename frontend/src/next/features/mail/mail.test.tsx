import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetConnectionForTests } from "../../shared/api/connection";
import { expectNoAxeViolations, mockFetch, renderApp, shellRoutes, type MockRoute } from "../../test/utils";
import type { MailAddress, MailMessage, MailSettings } from "./api";

const CONFIGURED: MailSettings = { configured: true, base_url: "https://mail.example.com", admin_email: "admin@example.com", has_password: true, domains: [] };
const UNCONFIGURED: MailSettings = { configured: false, base_url: null, admin_email: null, has_password: false, domains: [] };

const ADDRESSES: MailAddress[] = [
  { address: "emma.walker42@example.com", profile_id: "p1", profile_name: "注册用", created_at: "2026-10-27T08:00:00Z", last_delivered_id: 11 },
  { address: "noah.lee17@example.com", profile_id: null, profile_name: null, created_at: "2026-10-26T08:00:00Z", last_delivered_id: 0 },
];

const MESSAGES: MailMessage[] = [
  { id: 12, to: ADDRESSES[0].address, from: "noreply@github.com", from_name: "GitHub", subject: "Your GitHub launch code", received_at: "2026-10-27T09:00:00Z", code: "482913", link: "https://github.com/verify?t=1", text: "Your code is 482913" },
  { id: 11, to: ADDRESSES[0].address, from: "no-reply@aws.com", from_name: null, subject: "Verify your email", received_at: "2026-10-27T08:30:00Z", code: "905172", link: null, text: "code 905172" },
];

let settings: MailSettings;
let addresses: MailAddress[];

async function open(extra: MockRoute[] = []) {
  const fetchMock = mockFetch(
    shellRoutes([
      ...extra,
      { path: "/api/settings/mail", respond: () => settings },
      { path: "/api/mail/addresses", respond: () => addresses },
      { path: /^\/api\/mail\/messages\?address=emma/, respond: { address: ADDRESSES[0].address, last_delivered_id: 11, messages: MESSAGES } },
      { path: /^\/api\/mail\/messages\?address=noah/, respond: { address: ADDRESSES[1].address, last_delivered_id: 0, messages: [] } },
      { method: "POST", path: "/api/mail/check", respond: { ok: true, domains: ["example.com", "example.org"] } },
      { path: "/api/profiles", respond: [{ id: "p1", name: "注册用" }] },
    ]),
  );
  const utils = renderApp("/mail");
  await screen.findByRole("heading", { name: "邮箱", level: 1 });
  return { fetchMock, ...utils };
}

function bodies(fetchMock: ReturnType<typeof mockFetch>, method: string, url: string) {
  return fetchMock.mock.calls.filter(([u, init]) => String(u) === url && (init?.method ?? "GET") === method).map(([, init]) => JSON.parse(String((init as RequestInit).body)));
}

beforeEach(() => {
  settings = CONFIGURED;
  addresses = ADDRESSES;
  resetConnectionForTests();
});

afterEach(() => vi.unstubAllGlobals());

describe("connecting the mail server", () => {
  it("asks for the server first, then saves and checks the login", async () => {
    settings = UNCONFIGURED;
    const { fetchMock } = await open([
      {
        method: "PUT",
        path: "/api/settings/mail",
        respond: (body: unknown) => {
          settings = { ...CONFIGURED, ...(body as object), has_password: true, configured: true } as MailSettings;
          return settings;
        },
      },
    ]);
    const section = await screen.findByRole("region", { name: "连接邮箱服务器" });
    fireEvent.click(within(section).getByRole("button", { name: "保存并连接" }));
    expect(await within(section).findByText("服务器地址和管理员邮箱都要填")).toBeInTheDocument();
    fireEvent.change(within(section).getByLabelText("服务器地址"), { target: { value: "mail.example.com" } });
    fireEvent.change(within(section).getByLabelText("管理员邮箱"), { target: { value: "admin@example.com" } });
    fireEvent.change(within(section).getByLabelText(/^管理员密码/), { target: { value: "s3cret" } });
    fireEvent.click(within(section).getByRole("button", { name: "保存并连接" }));
    await waitFor(() =>
      expect(bodies(fetchMock, "PUT", "/api/settings/mail")[0]).toEqual({ base_url: "mail.example.com", admin_email: "admin@example.com", password: "s3cret", domains: [] }),
    );
    expect(await screen.findByText("已连接邮箱服务器")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "emma.walker42@example.com", pressed: true })).toBeInTheDocument();
  });

  it("shows why the login failed", async () => {
    settings = { ...CONFIGURED };
    await open([
      { method: "PUT", path: "/api/settings/mail", respond: CONFIGURED },
      { method: "POST", path: "/api/mail/check", status: 502, respond: { detail: "邮箱服务器：账号或密码错误" } },
    ]);
    fireEvent.click(await screen.findByRole("button", { name: "服务器设置" }));
    const dialog = await screen.findByRole("dialog", { name: "邮箱服务器" });
    expect(within(dialog).getByLabelText(/^管理员密码/)).toHaveValue("");
    expect(within(dialog).getByPlaceholderText("已保存（留空表示不修改）")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }));
    expect(await within(dialog).findByText("邮箱服务器：账号或密码错误")).toBeInTheDocument();
  });
});

describe("addresses and inbox", () => {
  it("lists addresses and opens the first inbox with its codes", async () => {
    await open();
    const table = await screen.findByRole("table", { name: "邮箱地址" });
    expect(within(table).getByText("注册用")).toBeInTheDocument();
    expect(within(table).getByText("未绑定")).toBeInTheDocument();
    const inbox = await screen.findByRole("region", { name: "收件箱" });
    expect(await within(inbox).findByText("Your GitHub launch code")).toBeInTheDocument();
    expect(within(inbox).getByText("482913")).toBeInTheDocument();
    expect(within(inbox).getByRole("link", { name: "验证链接" })).toHaveAttribute("href", "https://github.com/verify?t=1");
    // Mail the AI already took is marked.
    const items = within(inbox).getAllByRole("listitem");
    expect(within(items[0]).queryByText("AI 已取用")).not.toBeInTheDocument();
    expect(within(items[1]).getByText("AI 已取用")).toBeInTheDocument();
  });

  it("switches inbox and says when nothing arrived yet", async () => {
    await open();
    fireEvent.click(await screen.findByRole("button", { name: "noah.lee17@example.com" }));
    expect(await screen.findByText("还没有收到邮件")).toBeInTheDocument();
  });

  it("filters by address or environment", async () => {
    await open();
    const search = await screen.findByLabelText("搜索地址或环境");
    fireEvent.change(search, { target: { value: "注册" } });
    expect(screen.queryByRole("button", { name: "noah.lee17@example.com" })).not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "zzz" } });
    expect(screen.getByText("没有匹配「zzz」的地址")).toBeInTheDocument();
  });

  it("shows an empty state when there are no addresses", async () => {
    addresses = [];
    await open();
    expect(await screen.findByText("还没有地址")).toBeInTheDocument();
  });

  it("forgets an address after confirming it stays on the server", async () => {
    const { fetchMock } = await open([{ method: "DELETE", path: "/api/mail/addresses/noah.lee17%40example.com", respond: { ok: true } }]);
    fireEvent.click(await screen.findByRole("button", { name: "忘记 noah.lee17@example.com" }));
    const dialog = await screen.findByRole("dialog", { name: "忘记 noah.lee17@example.com？" });
    expect(dialog).toHaveTextContent("邮箱服务器上的邮箱和邮件都还在");
    fireEvent.click(within(dialog).getByRole("button", { name: "忘记" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, init]) => String(u) === "/api/mail/addresses/noah.lee17%40example.com" && init?.method === "DELETE")).toBe(true));
  });

  it("creates an address for an environment", async () => {
    const created: MailAddress = { address: "ava.king55@example.org", profile_id: "p1", profile_name: "注册用", created_at: "2026-10-28T08:00:00Z", last_delivered_id: 0 };
    const { fetchMock } = await open([{ method: "POST", path: "/api/mail/addresses", respond: created }]);
    fireEvent.click(await screen.findByRole("button", { name: "新地址" }));
    const dialog = await screen.findByRole("dialog", { name: "新地址" });
    await within(dialog).findByRole("option", { name: "注册用" });
    fireEvent.change(within(dialog).getByLabelText("归属环境"), { target: { value: "p1" } });
    await within(dialog).findByRole("option", { name: "example.org" });
    fireEvent.change(within(dialog).getByLabelText("域名"), { target: { value: "example.org" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "创建" }));
    await waitFor(() => expect(bodies(fetchMock, "POST", "/api/mail/addresses")[0]).toEqual({ profile_id: "p1", domain: "example.org" }));
    expect(await screen.findByText("已创建地址")).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = await open();
    await screen.findByText("Your GitHub launch code");
    await expectNoAxeViolations(container);
  });
});
