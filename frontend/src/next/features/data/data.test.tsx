import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetConnectionForTests } from "../../shared/api/connection";
import { expectNoAxeViolations, mockFetch, renderApp, shellRoutes, type MockRoute } from "../../test/utils";
import { makeProfile } from "../profiles/testing";
import { daysLeft, formatBytes } from "./api";

const DEFAULT_DIR = "/Users/me/CloakBrowser Manager Backups";
const FULL = { name: "CloakBrowser-backup-20261014-120000.zip", kind: "full", size: 39 * 1024 * 1024, created_at: "2026-10-14T12:00:00+08:00" };
const SNAPSHOT = { name: "profiles-20261014-110000.db", kind: "auto", size: 69632, created_at: "2026-10-14T11:00:00+08:00" };

function autoStatus(overrides: Record<string, unknown> = {}) {
  return {
    enabled: true, interval_days: 7, keep: 4, copy_dir: DEFAULT_DIR, default_copy_dir: DEFAULT_DIR,
    last_at: "2026-10-17T21:00:00+08:00", next_due_at: "2026-10-24T21:00:00+08:00", last_error: null,
    last_copy: `${DEFAULT_DIR}/CloakBrowser-backup-auto-20261017-210000.zip`, waiting_for_browsers: false,
    ...overrides,
  };
}

let backups: unknown[];
let running: boolean;

async function open(path = "/data", extra: MockRoute[] = []) {
  const fetchMock = mockFetch(shellRoutes([
    ...extra,
    { path: "/api/backups", respond: () => ({ backups, location: "/data/backups" }) },
    { path: "/api/backups/auto", respond: autoStatus() },
    { method: "PUT", path: "/api/backups/auto", respond: (body: unknown) => autoStatus(body as Record<string, unknown>) },
    { path: "/api/profiles", respond: () => (running ? [makeProfile({ id: "r", status: "running" }), makeProfile({ id: "s", status: "running" })] : []) },
    { path: "/api/profiles/trash", respond: [] },
  ]));
  const utils = renderApp(path);
  await screen.findByRole("heading", { name: "数据" });
  return { fetchMock, ...utils };
}

function called(fetchMock: ReturnType<typeof mockFetch>, method: string, url: string | RegExp) {
  return fetchMock.mock.calls.filter(([u, init]) => (init?.method ?? "GET") === method && (typeof url === "string" ? String(u) === url : url.test(String(u))));
}

beforeEach(() => {
  backups = [FULL, SNAPSHOT];
  running = false;
  resetConnectionForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("backups", () => {
  it("lists full backups and automatic snapshots, with a download only for full ones", async () => {
    await open();
    expect(await screen.findByText(FULL.name)).toBeInTheDocument();
    expect(screen.getByText(SNAPSHOT.name)).toBeInTheDocument();
    expect(screen.getByText("39.0 MB")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /下载/ })).toHaveLength(1);
    expect(screen.getByRole("link", { name: `下载 ${FULL.name}` })).toHaveAttribute("href", `/api/backups/full/${FULL.name}/download`);
  });

  it("names automatic and pre-update backups", async () => {
    backups = [
      { ...FULL, name: "CloakBrowser-backup-auto-20261017-120000.zip", origin: "auto" },
      { ...FULL, name: "CloakBrowser-backup-pre-update-20261017-110000.zip", origin: "pre-update" },
    ];
    await open();
    const table = await screen.findByRole("table", { name: "备份记录" });
    expect(within(table).getByText("自动完整备份")).toBeInTheDocument();
    expect(within(table).getByText("更新前备份")).toBeInTheDocument();
  });

  it("creates a full backup and starts the download", async () => {
    backups = [];
    const clicks = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const { fetchMock } = await open("/data", [{ method: "POST", path: "/api/backups", respond: FULL }]);
    fireEvent.click(await screen.findByRole("button", { name: "立即完整备份" }));
    await waitFor(() => expect(called(fetchMock, "POST", "/api/backups")).toHaveLength(1));
    expect(await screen.findByText(/完整备份已生成（39.0 MB）/)).toBeInTheDocument();
    expect((clicks.mock.contexts[0] as HTMLAnchorElement).getAttribute("href")).toBe(`/api/backups/full/${FULL.name}/download`);
  });

  it("blocks backup and restore while browsers run", async () => {
    running = true;
    await open();
    expect(await screen.findByText("有 2 个浏览器正在运行")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "立即完整备份" })).toBeDisabled();
    expect(screen.getByRole("button", { name: `恢复到 ${FULL.name}` })).toBeDisabled();
    expect(screen.getByRole("button", { name: "从备份文件恢复" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "立即备份一次" })).toBeDisabled();
  });

  it("restores only after confirmation and says where the old data went", async () => {
    const { fetchMock } = await open("/data", [{ method: "POST", path: /\/full\/.*\/restore$/, respond: { ok: true, profiles: 5, previous_data: "/data/backups/before-restore-1" } }]);
    fireEvent.click(await screen.findByRole("button", { name: `恢复到 ${FULL.name}` }));
    let dialog = await screen.findByRole("dialog", { name: "恢复这个完整备份？" });
    expect(dialog).toHaveTextContent("before-restore-");
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(called(fetchMock, "POST", /restore$/)).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: `恢复到 ${FULL.name}` }));
    dialog = await screen.findByRole("dialog", { name: "恢复这个完整备份？" });
    fireEvent.click(within(dialog).getByRole("button", { name: "恢复" }));
    await waitFor(() => expect(called(fetchMock, "POST", `/api/backups/full/${FULL.name}/restore`)).toHaveLength(1));
    expect(await screen.findByText("/data/backups/before-restore-1")).toBeInTheDocument();
  });

  it("warns that a snapshot keeps the browser data as it is", async () => {
    await open();
    fireEvent.click(await screen.findByRole("button", { name: `恢复到 ${SNAPSHOT.name}` }));
    expect(await screen.findByRole("dialog", { name: "恢复这个自动快照？" })).toHaveTextContent("不包含 Cookie 等浏览器数据");
  });

  it("restores from a chosen file, sent as the zip itself", async () => {
    const { fetchMock } = await open("/data", [{ method: "POST", path: "/api/backups/restore-upload", respond: { ok: true, profiles: 3, previous_data: "/x" } }]);
    const input = document.querySelector<HTMLInputElement>('input[type="file"][accept*="zip"]')!;
    const file = new File(["PK"], "backup.zip", { type: "application/zip" });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(within(await screen.findByRole("dialog", { name: "从这个文件恢复？" })).getByRole("button", { name: "恢复" }));
    await waitFor(() => expect(called(fetchMock, "POST", "/api/backups/restore-upload")).toHaveLength(1));
    const init = called(fetchMock, "POST", "/api/backups/restore-upload")[0]![1] as RequestInit;
    expect(init.body).toBe(file);
    expect(init.headers).toEqual({ "Content-Type": "application/zip" });
    expect(await screen.findByText("已恢复 3 个环境")).toBeInTheDocument();
  });

  it("deletes a backup after confirmation", async () => {
    const { fetchMock } = await open("/data", [{ method: "DELETE", path: `/api/backups/auto/${SNAPSHOT.name}`, respond: { ok: true } }]);
    fireEvent.click(await screen.findByRole("button", { name: `删除备份 ${SNAPSHOT.name}` }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "删除" }));
    await waitFor(() => expect(called(fetchMock, "DELETE", `/api/backups/auto/${SNAPSHOT.name}`)).toHaveLength(1));
  });

  it("explains a failed backup", async () => {
    await open("/data", [{ method: "POST", path: "/api/backups", status: 409, respond: { detail: "磁盘空间不足" } }]);
    fireEvent.click(await screen.findByRole("button", { name: "立即完整备份" }));
    expect(await screen.findByText("备份没有完成")).toBeInTheDocument();
    expect(screen.getByText("磁盘空间不足")).toBeInTheDocument();
  });

  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024 * 1024)).toBe("3.00 GB");
  });

  it("has no accessibility violations", async () => {
    const { container } = await open();
    await screen.findByText(FULL.name);
    await expectNoAxeViolations(container);
  });
});

describe("configuration export and import", () => {
  it("imports a configuration file and reports what was added", async () => {
    const { fetchMock } = await open("/data", [{ method: "POST", path: "/api/configuration/import", respond: { ok: true, profiles: 2, groups: 1, proxy_presets: 3 } }]);
    const input = document.querySelector<HTMLInputElement>('input[type="file"][accept*="json"]')!;
    fireEvent.change(input, { target: { files: [new File(['{"profiles":[]}'], "c.json", { type: "application/json" })] } });
    expect(await screen.findByText("新增 2 个环境、1 个分组、3 个代理。")).toBeInTheDocument();
    expect(JSON.parse(String((called(fetchMock, "POST", "/api/configuration/import")[0]![1] as RequestInit).body))).toEqual({ profiles: [] });
  });

  it("refuses a file that is not a configuration backup", async () => {
    const { fetchMock } = await open();
    const input = document.querySelector<HTMLInputElement>('input[type="file"][accept*="json"]')!;
    fireEvent.change(input, { target: { files: [new File(["not json"], "c.json", { type: "application/json" })] } });
    expect(await screen.findByText("这不是一个配置备份文件（无法读取 JSON）")).toBeInTheDocument();
    expect(called(fetchMock, "POST", "/api/configuration/import")).toHaveLength(0);
  });
});

describe("automatic backups", () => {
  it("shows when it last ran, when it runs next and where the copy went", async () => {
    mockFetch(shellRoutes([
      { path: "/api/backups", respond: { backups: [], location: "/data/backups" } },
      { path: "/api/backups/auto", respond: autoStatus({ waiting_for_browsers: true }) },
      { path: "/api/profiles", respond: [] },
      { path: "/api/profiles/trash", respond: [] },
    ]));
    renderApp("/data");
    expect(await screen.findByText(/等浏览器全部关闭后开始/)).toBeInTheDocument();
    expect(screen.getByText("最近一份另存在")).toBeInTheDocument();
  });

  it("saves a new schedule, and an empty folder as the default one", async () => {
    const { fetchMock } = await open();
    const save = await screen.findByRole("button", { name: "保存设置" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("备份频率"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText(/另存目录/), { target: { value: "" } });
    fireEvent.click(save);
    await waitFor(() => expect(JSON.parse(String((called(fetchMock, "PUT", "/api/backups/auto")[0]![1] as RequestInit).body))).toEqual({ enabled: true, interval_days: 1, keep: 4, copy_dir: DEFAULT_DIR }));
    expect(await screen.findByText("自动备份设置已保存。")).toBeInTheDocument();
  });

  it("can keep backups only inside the data directory", async () => {
    const { fetchMock } = await open();
    fireEvent.click(await screen.findByRole("checkbox", { name: /复制到数据目录之外/ }));
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));
    await waitFor(() => expect(JSON.parse(String((called(fetchMock, "PUT", "/api/backups/auto")[0]![1] as RequestInit).body)).copy_dir).toBeNull());
  });

  it("runs a backup now and reports the copy", async () => {
    await open("/data", [{ method: "POST", path: "/api/backups/auto/run", respond: { ok: true, name: "CloakBrowser-backup-auto-20261017-210000.zip", copy: `${DEFAULT_DIR}/x.zip`, copy_error: null, status: autoStatus() } }]);
    fireEvent.click(await screen.findByRole("button", { name: "立即备份一次" }));
    expect(await screen.findByText(/已备份：CloakBrowser-backup-auto-20261017-210000\.zip/)).toBeInTheDocument();
  });
});

describe("trash", () => {
  const deleted = (id: string, name: string, daysAgo: number) =>
    makeProfile({ id, name, deleted_at: new Date(Date.now() - daysAgo * 86_400_000).toISOString() });

  async function openTrash(extra: MockRoute[] = [], items = [deleted("t1", "旧环境", 2), deleted("t2", "快到期", 6.5)]) {
    const fetchMock = mockFetch(shellRoutes([
      ...extra,
      { path: "/api/profiles/trash", respond: () => items },
      { path: "/api/backups", respond: { backups: [], location: "" } },
      { path: "/api/backups/auto", respond: autoStatus() },
    ]));
    const utils = renderApp("/data/trash");
    await screen.findByRole("heading", { name: "数据" });
    return { fetchMock, ...utils };
  }

  it("lists deleted profiles with the days left", async () => {
    await openTrash();
    const row = await screen.findByRole("row", { name: /旧环境/ });
    expect(within(row).getByText("5 天")).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: /快到期/ })).getByText("1 天")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /回收站/ })).toHaveTextContent("2");
  });

  it("restores a profile", async () => {
    const { fetchMock } = await openTrash([{ method: "POST", path: "/api/profiles/t1/restore", respond: makeProfile({ id: "t1" }) }]);
    fireEvent.click(await screen.findByRole("button", { name: "恢复「旧环境」" }));
    await waitFor(() => expect(called(fetchMock, "POST", "/api/profiles/t1/restore")).toHaveLength(1));
    expect(await screen.findByText("已恢复「旧环境」")).toBeInTheDocument();
  });

  it("deletes for good only after confirmation", async () => {
    const { fetchMock } = await openTrash([{ method: "DELETE", path: "/api/profiles/t1/purge", respond: { ok: true } }]);
    fireEvent.click(await screen.findByRole("button", { name: "彻底删除「旧环境」" }));
    const dialog = await screen.findByRole("dialog", { name: "彻底删除「旧环境」？" });
    fireEvent.click(within(dialog).getByRole("button", { name: "彻底删除" }));
    await waitFor(() => expect(called(fetchMock, "DELETE", "/api/profiles/t1/purge")).toHaveLength(1));
  });

  it("says when the trash is empty", async () => {
    await openTrash([], []);
    expect(await screen.findByText("回收站是空的")).toBeInTheDocument();
  });

  it("counts the days left", () => {
    const now = Date.parse("2026-10-24T00:00:00Z");
    expect(daysLeft("2026-10-24T00:00:00Z", now)).toBe(7);
    expect(daysLeft("2026-10-17T00:00:00Z", now)).toBe(0);
    expect(daysLeft("2026-10-20T12:00:00Z", now)).toBe(4);
    expect(daysLeft(null, now)).toBeNull();
  });
});
