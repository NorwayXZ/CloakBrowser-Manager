import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { BackupPanel, formatBytes } from "./BackupPanel";

const fullBackup = {
  name: "CloakBrowser-backup-20261014-120000.zip",
  kind: "full" as const,
  size: 39 * 1024 * 1024,
  created_at: "2026-10-14T12:00:00+08:00",
};
const autoSnapshot = {
  name: "profiles-20261014-110000.db",
  kind: "auto" as const,
  size: 69632,
  created_at: "2026-10-14T11:00:00+08:00",
};

afterEach(() => vi.restoreAllMocks());

describe("BackupPanel", () => {
  it("lists full backups and automatic snapshots", async () => {
    vi.spyOn(api, "listBackups").mockResolvedValue({ backups: [fullBackup, autoSnapshot], location: "/data/backups" });
    render(<BackupPanel runningCount={0} onRefresh={vi.fn()} />);

    expect(await screen.findByText(fullBackup.name)).toBeTruthy();
    expect(screen.getByText(autoSnapshot.name)).toBeTruthy();
    expect(screen.getByText("39.0 MB")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /下载/ })).toHaveLength(1);
  });

  it("creates a full backup", async () => {
    vi.spyOn(api, "listBackups").mockResolvedValue({ backups: [], location: "/data/backups" });
    const create = vi.spyOn(api, "createBackup").mockResolvedValue(fullBackup);
    render(<BackupPanel runningCount={0} onRefresh={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "立即完整备份" }));
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(await screen.findByText(/完整备份已生成/)).toBeTruthy();
  });

  it("blocks backup and restore while browsers run", async () => {
    vi.spyOn(api, "listBackups").mockResolvedValue({ backups: [fullBackup], location: "/data/backups" });
    render(<BackupPanel runningCount={2} onRefresh={vi.fn()} />);
    await screen.findByText(fullBackup.name);

    expect((screen.getByRole("button", { name: "立即完整备份" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "恢复" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("restores only after confirmation", async () => {
    vi.spyOn(api, "listBackups").mockResolvedValue({ backups: [fullBackup], location: "/data/backups" });
    const restore = vi
      .spyOn(api, "restoreBackup")
      .mockResolvedValue({ ok: true, profiles: 5, previous_data: "/data/backups/before-restore-1" });
    const onRefresh = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<BackupPanel runningCount={0} onRefresh={onRefresh} />);
    await screen.findByText(fullBackup.name);

    fireEvent.click(screen.getByRole("button", { name: "恢复" }));
    expect(restore).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "恢复" }));
    await waitFor(() => expect(restore).toHaveBeenCalledWith(fullBackup));
    expect(await screen.findByText(/已恢复 5 个浏览器/)).toBeTruthy();
    expect(onRefresh).toHaveBeenCalled();
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024 * 1024)).toBe("3.00 GB");
  });
});
