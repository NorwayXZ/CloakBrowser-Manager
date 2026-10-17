import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
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
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "WebRTC" })).getByRole("radio", { name: "指定 IP" }));
    fireEvent.change(screen.getByPlaceholderText("例如 203.0.113.9"), { target: { value: "203.0.113.9" } });
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "地理位置" })).getByRole("radio", { name: "禁止" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /跨电脑 Cookie/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Windows 语音列表/ }));
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].fingerprint_options).toEqual({
      brand: "Edge",
      webrtc: "custom",
      webrtc_ip: "203.0.113.9",
      geolocation: "block",
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

afterEach(() => vi.restoreAllMocks());

describe("ProfileForm cookies and layout", () => {
  it("merges pasted Name=Value cookies through the backend", async () => {
    const merge = vi.spyOn(api, "mergeCookies").mockResolvedValue({
      cookies_json: '[{"name":"sid","value":"abc","domain":".example.com","path":"/"}]',
      format: "header",
      added: 1,
      total: 1,
    });
    render(<ProfileForm profile={null} hostOS="macos" onSave={vi.fn()} onCancel={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "合并 Cookie" }));
    fireEvent.change(screen.getByPlaceholderText(/粘贴要加进来的 Cookie/), { target: { value: "sid=abc" } });
    fireEvent.change(screen.getByPlaceholderText(/网站域名/), { target: { value: "example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "合并" }));

    await waitFor(() => expect(merge).toHaveBeenCalledWith("sid=abc", null, "example.com"));
    expect(await screen.findByText(/已合并 1 条（Name=Value），现在共 1 条/)).toBeTruthy();
    expect((screen.getByPlaceholderText(/支持 JSON、Netscape/) as HTMLTextAreaElement).value).toContain('"sid"');
  });

  it("shows the merge error from the backend", async () => {
    vi.spyOn(api, "mergeCookies").mockRejectedValue(new Error("Name=Value 格式不带域名"));
    render(<ProfileForm profile={null} hostOS="macos" onSave={vi.fn()} onCancel={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "合并 Cookie" }));
    fireEvent.change(screen.getByPlaceholderText(/粘贴要加进来的 Cookie/), { target: { value: "sid=abc" } });
    fireEvent.click(screen.getByRole("button", { name: "合并" }));

    expect(await screen.findByText("Name=Value 格式不带域名")).toBeTruthy();
  });

  it("lists every form section in the top navigation", () => {
    render(<ProfileForm profile={null} hostOS="windows" onSave={vi.fn()} onCancel={vi.fn()} />);

    const nav = screen.getByRole("navigation", { name: "表单分区" });
    expect(within(nav).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "基础设置", "代理信息", "指纹配置", "更多指纹", "高级设置",
    ]);
    for (const id of ["basic", "proxy", "fingerprint", "more-fingerprint", "advanced"]) {
      expect(document.getElementById(`form-${id}`)).toBeTruthy();
    }
  });

  it("summarises the geolocation and WebRTC choices", () => {
    render(<ProfileForm profile={null} hostOS="windows" onSave={vi.fn()} onCancel={vi.fn()} />);

    expect(screen.getByText("真实（直连）", { selector: "aside div" })).toBeTruthy();
    expect(screen.getByText("基于 IP", { selector: "aside div" })).toBeTruthy();
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "地理位置" })).getByRole("radio", { name: "禁止" }));
    expect(screen.getByText("禁止", { selector: "aside div" })).toBeTruthy();
    expect(within(screen.getByRole("radiogroup", { name: "WebRTC" })).queryByRole("radio", { name: /禁用/ })).toBeNull();
  });
});
