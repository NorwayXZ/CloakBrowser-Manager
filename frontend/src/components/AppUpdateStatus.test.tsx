import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type AppUpdateState } from "../lib/api";
import { AppUpdateStatus } from "./AppUpdateStatus";

function state(patch: Partial<AppUpdateState> = {}): AppUpdateState {
  return { phase: "idle", supported: true, current_version: "0.4.3", last_result: null, ...patch };
}

afterEach(() => vi.restoreAllMocks());

describe("AppUpdateStatus", () => {
  it("offers a one-click update only with browsers closed", async () => {
    vi.spyOn(api, "getAppUpdate").mockResolvedValue(state());
    const { rerender } = render(
      <AppUpdateStatus available="0.5.0" downloadUrl="https://example.com/dmg" runningCount={1} />,
    );

    const button = (await screen.findByRole("button", { name: "立即更新" })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText("请先关闭所有浏览器")).toBeTruthy();
    rerender(<AppUpdateStatus available="0.5.0" downloadUrl="https://example.com/dmg" runningCount={0} />);
    expect(button.disabled).toBe(false);
    expect(screen.getByRole("link", { name: "手动下载" })).toBeTruthy();
  });

  it("does not offer it where self-update is unsupported", async () => {
    const load = vi.spyOn(api, "getAppUpdate").mockResolvedValue(state({ supported: false }));
    render(<AppUpdateStatus available="0.5.0" downloadUrl={null} runningCount={0} />);
    await waitFor(() => expect(load).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "立即更新" })).toBeNull();
  });

  it("starts after confirmation and shows download progress", async () => {
    vi.spyOn(api, "getAppUpdate")
      .mockResolvedValueOnce(state())
      .mockResolvedValue(state({ phase: "downloading", label: "正在下载新版本", target: "0.5.0", done: 50, total: 100 }));
    const start = vi.spyOn(api, "startAppUpdate").mockResolvedValue(
      state({ phase: "checking", label: "正在检查新版本" }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<AppUpdateStatus available="0.5.0" downloadUrl={null} runningCount={0} />);

    fireEvent.click(await screen.findByRole("button", { name: "立即更新" }));

    await waitFor(() => expect(start).toHaveBeenCalledOnce());
    expect(await screen.findByText(/正在下载新版本 50%（0\.5\.0）/, {}, { timeout: 3000 })).toBeTruthy();
  });

  it("reloads once the new version answers", async () => {
    vi.spyOn(api, "getAppUpdate").mockResolvedValue(state({ phase: "restarting", label: "正在安装，应用会自动重启", target: "0.5.0" }));
    vi.spyOn(api, "getStatus").mockResolvedValue({
      running_count: 0, app_version: "0.5.0", binary_version: "154.0.8037.57.1", profiles_total: 5,
      host_os: "macos", runtime_mode: "native", viewer_mode: "native-window",
    });
    const onUpdated = vi.fn();
    render(<AppUpdateStatus available={null} downloadUrl={null} runningCount={0} onUpdated={onUpdated} />);

    expect(await screen.findByText(/新版本启动后这个页面会自动刷新/)).toBeTruthy();
    await waitFor(() => expect(onUpdated).toHaveBeenCalledOnce(), { timeout: 3000 });
  });

  it("reports the previous update's outcome and can dismiss it", async () => {
    vi.spyOn(api, "getAppUpdate")
      .mockResolvedValueOnce(state({
        last_result: {
          ok: false, from: "0.4.3", to: "0.5.0", running: "0.4.3",
          reason: "cannot move the current app aside (macOS App Management?)", finished_at: "2026-10-18T10:00:00+08:00",
        },
      }))
      .mockResolvedValue(state());
    const dismiss = vi.spyOn(api, "dismissAppUpdateResult").mockResolvedValue({ ok: true });
    render(<AppUpdateStatus available={null} downloadUrl={null} runningCount={0} />);

    expect(await screen.findByText("更新到 0.5.0 没有成功，仍在使用 0.4.3")).toBeTruthy();
    expect(screen.getByText(/App Management/)).toBeTruthy();
    fireEvent.click(screen.getByTitle("关闭"));
    await waitFor(() => expect(dismiss).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.queryByText(/没有成功/)).toBeNull());
  });

  it("shows why an update could not start", async () => {
    vi.spyOn(api, "getAppUpdate").mockResolvedValue(state());
    vi.spyOn(api, "startAppUpdate").mockRejectedValue(new Error("一键更新前请先关闭所有浏览器"));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<AppUpdateStatus available="0.5.0" downloadUrl="https://example.com/dmg" runningCount={0} />);

    fireEvent.click(await screen.findByRole("button", { name: "立即更新" }));

    expect(await screen.findByText(/一键更新前请先关闭所有浏览器/)).toBeTruthy();
  });
});
