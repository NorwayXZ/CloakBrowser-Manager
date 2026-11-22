/**
 * The redesigned editor must send exactly what the current one sends. This
 * renders the current editor (src/components/ProfileForm.tsx), saves without
 * changes, and compares its payload with the new model's for the same
 * profile. Delete this file together with the old editor.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProfileForm } from "../../../components/ProfileForm";
import * as oldDevices from "../../../lib/deviceProfiles";
import oldSource from "../../../components/ProfileForm.tsx?raw";
import { makeProfile } from "../profiles/testing";
import type { Profile } from "../profiles/types";
import * as newDevices from "./deviceProfiles";
import { buildPayload, GPU_PRESETS, initialState, RESOLUTION_PRESETS } from "./model";
import type { HostOS } from "./types";

beforeEach(() => {
  // The current editor loads the warm-up target list on open; nothing else matters here.
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    String(url).endsWith("/warmup/targets") ? new Response("[]") : new Response('{"detail":"Not found"}', { status: 404 })));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function oldPayload(profile: Profile | null, hostOS: HostOS, hostScreen: number[] | null = null) {
  const onSave = vi.fn().mockResolvedValue(undefined);
  render(<ProfileForm profile={profile as never} hostOS={hostOS} hostScreen={hostScreen} onSave={onSave} onCancel={vi.fn()} />);
  if (!profile) fireEvent.change(screen.getByPlaceholderText("例如 Amazon Seller #1"), { target: { value: "新环境" } });
  fireEvent.click(screen.getByRole("button", { name: profile ? "保存" : "创建" }));
  await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
  return JSON.parse(JSON.stringify(onSave.mock.calls[0]![0]));
}

function newPayload(profile: Profile | null, hostOS: HostOS) {
  const { form } = initialState(profile, hostOS);
  return JSON.parse(JSON.stringify(buildPayload(profile ? form : { ...form, name: "新环境" }, hostOS)));
}

const CASES: [string, Profile, HostOS][] = [
  ["CloakBrowser on macOS", makeProfile({ device_profile: "native_macos", fingerprint_options: { noise: false } as never }), "macos"],
  ["system Chrome", makeProfile({ browser_engine: "system_chrome", gpu_vendor: "x", hardware_concurrency: 4 }), "macos"],
  ["unknown engine becomes system Chrome", makeProfile({ browser_engine: "auto" }), "macos"],
  ["Windows persona opened on macOS is moved to a macOS device", makeProfile({ platform: "windows", device_profile: "win-vega8-1920x1080-02" }), "macos"],
  ["Windows host", makeProfile({ platform: "windows", device_profile: null }), "windows"],
  ["SOCKS5 with credentials", makeProfile({ proxy: "socks5://alice:p%40ss@203.0.113.9:1080" }), "macos"],
  ["Xray link", makeProfile({ proxy: "vless://uuid@edge.example.com:443?security=tls#x" }), "macos"],
  ["empty proxy string is sent as null", makeProfile({ proxy: "" }), "macos"],
  [
    "everything filled",
    makeProfile({
      name: "Amazon US",
      group_name: "美国账号",
      account_platform: "Amazon",
      timezone: "America/Los_Angeles",
      locale: "en-US",
      user_agent: "Mozilla/5.0 Test",
      cookies_json: '[{"name":"sid","value":"1","domain":".example.com","path":"/"}]',
      startup_urls: ["https://example.com", "https://ip.example.org"],
      launch_args: ["--load-extension=/a,/b", "--lang=en"],
      notes: "备注",
      tags: [{ tag: "vip", color: "#f00" }],
      warmup_enabled: true,
      warmup_daily_max: 2,
      warmup_targets: ["amazon"],
      warmup_persona: "32 岁",
      humanize: false,
      human_preset: "careful",
      auto_launch: true,
      clipboard_sync: false,
      color_scheme: "dark",
      fingerprint_options: { brand: "Edge", webrtc: "custom", webrtc_ip: "1.2.3.4", storage_quota_mb: 1234, screen: "custom" } as never,
    }),
    "macos",
  ],
  ["group missing becomes 未分组", makeProfile({ group_name: null }), "macos"],
];

describe("save without changes sends the same payload as the current editor", () => {
  it.each(CASES)("%s", async (_name, profile, hostOS) => {
    expect(newPayload(profile, hostOS)).toEqual(await oldPayload(profile, hostOS));
  });

  it.each<HostOS>(["macos", "windows"])("a new profile on %s", async (hostOS) => {
    // The default form draws a random fingerprint seed; pin it for both.
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    expect(newPayload(null, hostOS)).toEqual(await oldPayload(null, hostOS));
  });
});

describe("choices are the current editor's", () => {
  it("offers the same device presets", () => {
    expect(newDevices.DEVICE_PROFILES).toEqual(oldDevices.DEVICE_PROFILES);
    expect(newDevices.DEFAULT_DEVICE_PROFILE_IDS).toEqual(oldDevices.DEFAULT_DEVICE_PROFILE_IDS);
  });

  it("offers the same GPU and resolution presets", () => {
    const gpu = [...oldSource.matchAll(/"([^"]+)": \{\s+vendor: "([^"]+)",\s+renderer: "([^"]+)",\s+\}/g)].map((m) => [m[1], { vendor: m[2], renderer: m[3] }]);
    expect(gpu.length).toBeGreaterThan(20);
    expect(Object.entries(GPU_PRESETS)).toEqual(gpu);
    const screens = [...oldSource.matchAll(/"([^"]+)": \{ width: (\d+), height: (\d+) \}/g)].map((m) => [m[1], { width: Number(m[2]), height: Number(m[3]) }]);
    expect(Object.entries(RESOLUTION_PRESETS)).toEqual(screens);
  });
});
