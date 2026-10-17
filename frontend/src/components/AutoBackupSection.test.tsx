import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type AutoBackupStatus } from "../lib/api";
import { AutoBackupSection } from "./AutoBackupSection";

const DEFAULT_DIR = "/Users/me/CloakBrowser Manager Backups";

function status(patch: Partial<AutoBackupStatus> = {}): AutoBackupStatus {
  return {
    enabled: true,
    interval_days: 7,
    keep: 4,
    copy_dir: DEFAULT_DIR,
    default_copy_dir: DEFAULT_DIR,
    last_at: "2026-10-10T20:00:00+08:00",
    next_due_at: "2026-10-17T20:00:00+08:00",
    last_error: null,
    last_copy: `${DEFAULT_DIR}/CloakBrowser-backup-auto-20261010-200000.zip`,
    waiting_for_browsers: false,
    ...patch,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("AutoBackupSection", () => {
  it("shows when it last ran and where the copy went", async () => {
    vi.spyOn(api, "getAutoBackup").mockResolvedValue(status({ waiting_for_browsers: true }));
    render(<AutoBackupSection runningCount={1} onBackedUp={vi.fn()} />);

    expect(await screen.findByText(/最近一份另存在/)).toBeTruthy();
    expect(screen.getByText(/等浏览器全部关闭后开始/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "立即备份一次" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("saves a new schedule and an empty folder as the default one", async () => {
    vi.spyOn(api, "getAutoBackup").mockResolvedValue(status({ copy_dir: DEFAULT_DIR }));
    const save = vi.spyOn(api, "saveAutoBackup").mockImplementation(async (settings) => status(settings));
    render(<AutoBackupSection runningCount={0} onBackedUp={vi.fn()} />);
    await screen.findByText(/最近一份另存在/);

    fireEvent.change(screen.getByLabelText("备份频率"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("另存目录"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({ enabled: true, interval_days: 1, keep: 4, copy_dir: DEFAULT_DIR }),
    );
    expect(await screen.findByText("自动备份设置已保存。")).toBeTruthy();
  });

  it("can keep backups only inside the data directory", async () => {
    vi.spyOn(api, "getAutoBackup").mockResolvedValue(status());
    const save = vi.spyOn(api, "saveAutoBackup").mockImplementation(async (settings) => status(settings));
    render(<AutoBackupSection runningCount={0} onBackedUp={vi.fn()} />);
    await screen.findByText(/最近一份另存在/);

    fireEvent.click(screen.getByRole("checkbox", { name: /复制到数据目录之外/ }));
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ copy_dir: null })));
  });

  it("runs a backup now and reports the copy", async () => {
    vi.spyOn(api, "getAutoBackup").mockResolvedValue(status());
    vi.spyOn(api, "runAutoBackup").mockResolvedValue({
      ok: true,
      name: "CloakBrowser-backup-auto-20261017-210000.zip",
      copy: `${DEFAULT_DIR}/CloakBrowser-backup-auto-20261017-210000.zip`,
      copy_error: null,
      status: status(),
    });
    const onBackedUp = vi.fn();
    render(<AutoBackupSection runningCount={0} onBackedUp={onBackedUp} />);
    await screen.findByText(/最近一份另存在/);

    fireEvent.click(screen.getByRole("button", { name: "立即备份一次" }));

    expect(await screen.findByText(/已备份：CloakBrowser-backup-auto-20261017-210000\.zip/)).toBeTruthy();
    expect(onBackedUp).toHaveBeenCalled();
  });
});
