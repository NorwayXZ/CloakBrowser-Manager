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
    expect((screen.getByRole("checkbox", { name: /根据出口 IP/ }) as HTMLInputElement).disabled).toBe(false);
    expect(screen.getByRole("button", { name: "检查直连出口" })).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("例如 Amazon Seller #1"), { target: { value: "Direct profile" } });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].proxy ?? null).toBeNull();
    expect(onSave.mock.calls[0][0].geoip).toBe(true);
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

describe("ProfileForm extra fingerprint options", () => {
  it("saves brand, WebRTC and cookie options with the profile", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ProfileForm profile={null} hostOS="windows" onSave={onSave} onCancel={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText("例如 Amazon Seller #1"), { target: { value: "Edge profile" } });
    fireEvent.change(screen.getByDisplayValue("Chrome（默认）"), { target: { value: "Edge" } });
    fireEvent.change(screen.getByDisplayValue("跟随代理出口 IP（推荐）"), { target: { value: "custom" } });
    fireEvent.change(screen.getByPlaceholderText("例如 203.0.113.9"), { target: { value: "203.0.113.9" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /跨电脑 Cookie/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Windows 语音列表/ }));
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].fingerprint_options).toEqual({
      brand: "Edge",
      webrtc_ip: "203.0.113.9",
      portable_cookies: true,
      speech_voices: false,
    });
  });

  it("keeps transparent proxy off until a proxy is set", () => {
    render(<ProfileForm profile={null} hostOS="macos" onSave={vi.fn()} onCancel={vi.fn()} />);

    expect((screen.getByRole("checkbox", { name: /透明代理/ }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByRole("checkbox", { name: /Windows 语音列表/ })).toBeNull();
  });
});
