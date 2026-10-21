import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type KernelOverview } from "../lib/api";
import { KernelPanel } from "./KernelPanel";

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
      { name: "chromium-154.0.8037.57.1-pro", version: "154.0.8037.57.1", pro: true, size_bytes: 408 * 1024 * 1024, in_use: true },
      { name: "chromium-145.0.7632.109.2", version: "145.0.7632.109.2", pro: false, size_bytes: 367 * 1024 * 1024, in_use: false },
    ],
    running_count: 0,
    ...patch,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("KernelPanel", () => {
  it("shows the kernel in use, the license and reclaimable versions", async () => {
    vi.spyOn(api, "getKernel").mockResolvedValue(overview());
    render(<KernelPanel runningCount={0} />);

    expect(await screen.findByText("154.0.8037.57.1", { selector: "div" })).toBeTruthy();
    expect(screen.getByText("免费 GitHub 密钥")).toBeTruthy();
    expect(screen.getByText(/1 个旧版本没在用，共 367.0 MB/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /删除内核/ })).toHaveLength(1);
  });

  it("does not let a free key pin a version", async () => {
    vi.spyOn(api, "getKernel").mockResolvedValue(overview());
    render(<KernelPanel runningCount={0} />);
    await screen.findByText("免费 GitHub 密钥");

    const pin = screen.getByDisplayValue("不锁定，跟随最新") as HTMLSelectElement;
    expect(pin.disabled).toBe(true);
    expect(screen.getByText(/官方不允许锁定版本/)).toBeTruthy();
  });

  it("checks for a newer kernel and updates it", async () => {
    vi.spyOn(api, "getKernel").mockResolvedValue(overview());
    vi.spyOn(api, "checkKernel").mockResolvedValue({
      current_version: "154.0.8037.57.1", latest_version: "155.0.1.1.1", update_available: true, pinned: false,
    });
    const update = vi.spyOn(api, "updateKernel").mockResolvedValue({
      ok: true, updated: true, wrapper_version: "0.6.2", current_version: "154.0.8037.57.1",
      available_version: "155.0.1.1.1", installed_version: "155.0.1.1.1", platform: "darwin-arm64",
      binary_verified: true, restart_required: true, message: "CloakBrowser 内核已更新并验证为 155.0.1.1.1",
    });
    render(<KernelPanel runningCount={0} />);
    await screen.findByText("免费 GitHub 密钥");

    fireEvent.click(screen.getByRole("button", { name: "检查更新" }));
    expect(await screen.findByText(/发现新内核 155.0.1.1.1/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "立即更新" }));
    await waitFor(() => expect(update).toHaveBeenCalledOnce());
    expect(await screen.findByText(/已更新并验证为 155.0.1.1.1/)).toBeTruthy();
  });

  it("saves update settings", async () => {
    vi.spyOn(api, "getKernel").mockResolvedValue(overview());
    const save = vi.spyOn(api, "saveKernelSettings").mockImplementation(async (settings) => overview({ settings }));
    render(<KernelPanel runningCount={0} />);
    await screen.findByText("免费 GitHub 密钥");

    const saveButton = screen.getByRole("button", { name: "保存设置" }) as HTMLButtonElement;
    expect(saveButton.disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: /自动下载新内核/ }));
    fireEvent.click(saveButton);

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({ auto_update: false, release_channel: "stable", pinned_version: null }),
    );
    expect(await screen.findByText(/内核设置已保存/)).toBeTruthy();
  });

  it("saves a typed license key and clears the field", async () => {
    vi.spyOn(api, "getKernel").mockResolvedValue(
      overview({ license: { tier: "none", plan: null, expires: null, can_pin: true, key_stored: false } }),
    );
    const save = vi
      .spyOn(api, "saveLicenseKey")
      .mockResolvedValue(
        overview({ license: { tier: "free", plan: "free", expires: null, can_pin: false, key_stored: true } }),
      );
    render(<KernelPanel runningCount={0} />);
    await screen.findByText("未登录授权");

    const input = screen.getByLabelText("CloakBrowser 授权密钥") as HTMLInputElement;
    expect(input.type).toBe("password");
    const button = screen.getByRole("button", { name: "保存密钥" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(input, { target: { value: "cb_test_fixture_000" } });
    fireEvent.click(button);

    await waitFor(() => expect(save).toHaveBeenCalledWith("cb_test_fixture_000"));
    expect(await screen.findByText(/授权密钥已保存并通过验证/)).toBeTruthy();
    expect(input.value).toBe("");
    expect(screen.queryByRole("button", { name: "保存密钥" })).toBeNull();
    expect(screen.getByRole("button", { name: /移除密钥/ })).toBeTruthy();
  });

  it("keeps the typed key and shows the error when the key is rejected", async () => {
    vi.spyOn(api, "getKernel").mockResolvedValue(
      overview({ license: { tier: "none", plan: null, expires: null, can_pin: true, key_stored: false } }),
    );
    vi.spyOn(api, "saveLicenseKey").mockRejectedValue(
      new Error("这个授权密钥没有通过官方验证，已恢复之前的设置。请核对密钥后重新输入。"),
    );
    render(<KernelPanel runningCount={0} />);
    await screen.findByText("未登录授权");

    const input = screen.getByLabelText("CloakBrowser 授权密钥") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "cb_test_fixture_999" } });
    fireEvent.click(screen.getByRole("button", { name: "保存密钥" }));

    expect(await screen.findByText(/没有通过官方验证/)).toBeTruthy();
    expect(input.value).toBe("cb_test_fixture_999");
  });

  it("removes a stored license key after confirmation", async () => {
    vi.spyOn(api, "getKernel").mockResolvedValue(overview());
    const remove = vi.spyOn(api, "removeLicenseKey").mockResolvedValue(
      overview({ license: { tier: "none", plan: null, expires: null, can_pin: true, key_stored: false } }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<KernelPanel runningCount={0} />);
    await screen.findByText("免费 GitHub 密钥");

    expect(screen.getByText(/已保存授权密钥/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /移除密钥/ }));
    expect(remove).not.toHaveBeenCalled();

    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: /移除密钥/ }));
    await waitFor(() => expect(remove).toHaveBeenCalledOnce());
    expect(await screen.findByText(/已移除保存的授权密钥/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "保存密钥" })).toBeTruthy();
  });

  it("deletes an old kernel only after confirmation and while no browser runs", async () => {
    vi.spyOn(api, "getKernel").mockResolvedValue(overview());
    const remove = vi.spyOn(api, "deleteKernel").mockResolvedValue({ ok: true, freed_bytes: 367 * 1024 * 1024 });
    vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const { rerender } = render(<KernelPanel runningCount={1} />);
    await screen.findByText("免费 GitHub 密钥");

    const button = () => screen.getByRole("button", { name: /删除内核 145/ }) as HTMLButtonElement;
    expect(button().disabled).toBe(true);
    rerender(<KernelPanel runningCount={0} />);
    fireEvent.click(button());
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(button());
    await waitFor(() => expect(remove).toHaveBeenCalledWith("chromium-145.0.7632.109.2"));
    expect(await screen.findByText(/释放 367.0 MB/)).toBeTruthy();
  });
});
