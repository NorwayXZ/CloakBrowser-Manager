import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Profile } from "../lib/api";
import { ProfileForm } from "./ProfileForm";

function makeProfile(overrides: Partial<Profile> = {}): Profile {
  return {
    id: "profile-1",
    name: "Awscnn",
    browser_engine: "cloakbrowser",
    device_profile: null,
    fingerprint_seed: 12345,
    proxy: null,
    timezone: null,
    locale: null,
    platform: "macos",
    user_agent: null,
    screen_width: 1440,
    screen_height: 900,
    gpu_vendor: null,
    gpu_renderer: null,
    hardware_concurrency: null,
    device_memory: null,
    humanize: true,
    human_preset: "default",
    headless: false,
    geoip: true,
    clipboard_sync: true,
    auto_launch: false,
    group_name: "未分组",
    account_platform: null,
    cookies_json: null,
    startup_urls: [],
    color_scheme: null,
    launch_args: [],
    fingerprint_options: {},
    notes: null,
    user_data_dir: "/tmp/profiles/profile-1",
    created_at: "2026-10-21T00:00:00Z",
    updated_at: "2026-10-21T00:00:00Z",
    last_opened_at: null,
    last_exit_at: null,
    last_exit_reason: null,
    deleted_at: null,
    tags: [],
    status: "stopped",
    runtime_mode: "native",
    viewer_mode: "native-window",
    vnc_ws_port: null,
    cdp_url: null,
    launch_mode: null,
    proxy_geo: null,
    ...overrides,
  };
}

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
      noise: false,
      storage_quota_mb: 50000,
      brand: "Edge",
      webrtc: "custom",
      webrtc_ip: "203.0.113.9",
      geolocation: "block",
      portable_cookies: true,
      speech_voices: false,
    });
  });

  it("applies the recommended noise/quota preset to new profiles and can roll back to auto", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ProfileForm profile={null} hostOS="windows" onSave={onSave} onCancel={vi.fn()} />);

    // New form defaults to the 2026-10-21 recommended preset.
    fireEvent.change(screen.getByPlaceholderText("例如 Amazon Seller #1"), { target: { value: "Preset" } });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].fingerprint_options.noise).toBe(false);
    expect(onSave.mock.calls[0][0].fingerprint_options.storage_quota_mb).toBe(50000);
  });

  it("rolls the noise/quota preset back to kernel defaults (auto)", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ProfileForm profile={null} hostOS="windows" onSave={onSave} onCancel={vi.fn()} />);

    fireEvent.click(within(screen.getByRole("radiogroup", { name: "指纹噪声" })).getByRole("radio", { name: "自动" }));
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "存储配额" })).getByRole("radio", { name: "按种子自动" }));
    fireEvent.change(screen.getByPlaceholderText("例如 Amazon Seller #1"), { target: { value: "Rollback" } });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].fingerprint_options.noise).toBeNull();
    expect(onSave.mock.calls[0][0].fingerprint_options.storage_quota_mb).toBeNull();
  });

  it("keeps transparent proxy off until a proxy is set", () => {
    render(<ProfileForm profile={null} hostOS="macos" onSave={vi.fn()} onCancel={vi.fn()} />);

    expect((screen.getByRole("checkbox", { name: /透明代理/ }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByRole("checkbox", { name: /Windows 语音列表/ })).toBeNull();
  });
});

describe("ProfileForm proxy IP quality", () => {
  it("shows whether the exit IP is flagged as a proxy", async () => {
    vi.spyOn(api, "testProxy").mockResolvedValue({
      ok: true,
      ip: "150.31.13.127",
      country: "Japan",
      country_code: "JP",
      suggested_locale: "ja-JP",
      region: null,
      city: "Toyama",
      timezone: "Asia/Tokyo",
      org: "IIJ",
      asn: "AS2497",
      source: "test",
      connection_mode: "proxy",
      ip_quality: {
        verdict: "flagged",
        summary: "已被标记为代理 / VPN / 机房 IP（proxycheck.io）：网站能看出你在用代理",
        signals: [
          { source: "proxycheck.io", status: "flagged", detail: "代理（Shadowsocks，风险 66）" },
          { source: "ip-api.com", status: "clean", detail: "没有标记（家庭宽带，IIJ）" },
        ],
        links: [{ name: "Scamalytics", url: "https://scamalytics.com/ip/150.31.13.127" }],
      },
    });
    render(<ProfileForm profile={null} hostOS="macos" onSave={vi.fn()} onCancel={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "检查直连出口" }));

    const panel = await screen.findByTestId("ip-quality");
    expect(panel.textContent).toContain("IP 质量：已被标记");
    expect(panel.textContent).toContain("proxycheck.io：已被标记 · 代理（Shadowsocks，风险 66）");
    expect(within(panel).getByRole("link", { name: "Scamalytics" }).getAttribute("href"))
      .toBe("https://scamalytics.com/ip/150.31.13.127");
  });
});

describe("ProfileForm screen and browser language", () => {
  it("follows the computer's screen by default and can switch to a preset", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ProfileForm profile={null} hostOS="macos" hostScreen={[2560, 1440]} onSave={onSave} onCancel={vi.fn()} />);

    const picker = screen.getByRole("combobox", { name: "分辨率" }) as HTMLSelectElement;
    expect(picker.value).toBe("real");
    expect(screen.getByText("跟随电脑屏幕 2560 × 1440（推荐）")).toBeTruthy();

    fireEvent.change(picker, { target: { value: "1920 × 1080 (Windows 常见)" } });
    fireEvent.change(screen.getByPlaceholderText("例如 Amazon Seller #1"), { target: { value: "Custom screen" } });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    const saved = onSave.mock.calls[0][0];
    expect(saved.fingerprint_options.screen).toBe("custom");
    expect([saved.screen_width, saved.screen_height]).toEqual([1920, 1080]);
  });

  it("hides the follow option when the screen cannot be read", () => {
    render(<ProfileForm profile={null} hostOS="windows" onSave={vi.fn()} onCancel={vi.fn()} />);

    const picker = screen.getByRole("combobox", { name: "分辨率" }) as HTMLSelectElement;
    expect(Array.from(picker.options).some((option) => option.value === "real")).toBe(false);
  });

  it("saves a fixed browser language", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<ProfileForm profile={null} hostOS="macos" onSave={onSave} onCancel={vi.fn()} />);

    fireEvent.change(screen.getByRole("combobox", { name: "浏览器语言" }), { target: { value: "zh-CN" } });
    fireEvent.change(screen.getByPlaceholderText("例如 Amazon Seller #1"), { target: { value: "Chinese UI" } });
    fireEvent.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
    expect(onSave.mock.calls[0][0].fingerprint_options.language).toBe("zh-CN");
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

  it("pulls the running browser's cookies back into the form", async () => {
    const pulledJson = '[{"name":"sid","value":"abc","domain":".example.com","path":"/"}]';
    const pull = vi.spyOn(api, "pullProfileCookies").mockResolvedValue({
      cookies: [{ name: "sid", value: "abc", domain: ".example.com", path: "/" }],
      cookies_json: pulledJson,
      count: 1,
    });
    render(<ProfileForm profile={makeProfile()} hostOS="macos" onSave={vi.fn()} onCancel={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /从浏览器导回 Cookie/ }));

    await waitFor(() => expect(pull).toHaveBeenCalledWith("profile-1"));
    expect(await screen.findByText(/已从浏览器导回 1 条 Cookie/)).toBeTruthy();
    expect((screen.getByPlaceholderText(/支持 JSON、Netscape/) as HTMLTextAreaElement).value).toBe(pulledJson);
  });

  it("shows the backend error when the browser cannot be read", async () => {
    vi.spyOn(api, "pullProfileCookies").mockRejectedValue(new Error("浏览器没有在运行：请先用「调试模式」启动这个浏览器，再导回它的 Cookie"));
    render(<ProfileForm profile={makeProfile()} hostOS="macos" onSave={vi.fn()} onCancel={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /从浏览器导回 Cookie/ }));

    expect(await screen.findByText(/浏览器没有在运行/)).toBeTruthy();
    expect((screen.getByPlaceholderText(/支持 JSON、Netscape/) as HTMLTextAreaElement).value).toBe("");
  });

  it("exports cookies in the chosen format", async () => {
    const download = vi.spyOn(api, "downloadCookieExport").mockResolvedValue(undefined);
    render(<ProfileForm profile={makeProfile()} hostOS="macos" onSave={vi.fn()} onCancel={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("导出格式"), { target: { value: "netscape" } });
    fireEvent.click(screen.getByRole("button", { name: /导出 Cookie/ }));

    await waitFor(() => expect(download).toHaveBeenCalledWith("profile-1", "netscape", "Awscnn-cookies.txt"));
    expect(await screen.findByText("Cookie 文件已开始下载")).toBeTruthy();
  });

  it("hides pull and export until the profile exists", () => {
    render(<ProfileForm profile={null} hostOS="macos" onSave={vi.fn()} onCancel={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /从浏览器导回 Cookie/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /导出 Cookie/ })).toBeNull();
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
