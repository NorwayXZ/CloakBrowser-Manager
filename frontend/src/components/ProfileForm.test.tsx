import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProfileForm } from "./ProfileForm";

describe("ProfileForm proxy mode", () => {
  it("creates a direct profile without a proxy value", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <ProfileForm
        profile={null}
        hostOS="windows"
        onSave={onSave}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "直连" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("直连已启用")).toBeTruthy();
    expect(screen.queryByText("主机:端口")).toBeNull();
    expect((screen.getByRole("checkbox", { name: /根据代理 IP/ }) as HTMLInputElement).disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText("例如 Amazon Seller #1"), { target: { value: "Direct profile" } });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].proxy ?? null).toBeNull();
    expect(onSave.mock.calls[0][0].geoip).toBe(false);
  });

  it("clears a custom proxy when direct mode is selected", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <ProfileForm
        profile={null}
        hostOS="macos"
        onSave={onSave}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText("例如 Amazon Seller #1"), { target: { value: "Switch to direct" } });
    fireEvent.click(screen.getByRole("button", { name: "自定义代理" }));
    fireEvent.change(screen.getByPlaceholderText("192.168.100.1"), { target: { value: "127.0.0.1" } });
    fireEvent.change(screen.getByPlaceholderText("1090"), { target: { value: "1080" } });
    fireEvent.click(screen.getByRole("button", { name: "直连" }));
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].proxy).toBeNull();
  });
});
