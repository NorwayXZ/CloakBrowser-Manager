import { describe, expect, it } from "vitest";
import {
  applyDeviceProfile,
  getDefaultDeviceProfileId,
  getDeviceProfile,
  getDeviceProfilesForPlatform,
  getDevicePlatformForHost,
} from "./deviceProfiles";

describe("deviceProfiles", () => {
  it("uses host-specific native defaults", () => {
    expect(getDefaultDeviceProfileId("macos")).toBe("native_macos");
    expect(getDefaultDeviceProfileId("windows")).toBe("native_windows");
    expect(getDevicePlatformForHost("windows")).toBe("windows");
    expect(getDevicePlatformForHost("macos")).toBe("macos");
  });

  it("keeps Windows profiles on the Windows platform", () => {
    const profile = getDeviceProfile("native_windows");
    const next = applyDeviceProfile({ name: "test", browser_engine: "cloakbrowser" }, profile);

    expect(next.platform).toBe("windows");
    expect(next.device_profile).toBe("native_windows");
    expect(next.device_memory).toBeNull();
  });

  it("uses logical CSS screen sizes for Retina Mac profiles", () => {
    const macbook = getDeviceProfile("mbp_14_m4_2024");
    const imac = getDeviceProfile("imac_24_m4_2024");

    expect([macbook.screen_width, macbook.screen_height]).toEqual([1512, 982]);
    expect([imac.screen_width, imac.screen_height]).toEqual([2240, 1260]);
  });

  it("applies the browser-visible memory cap to CloakBrowser presets", () => {
    const preset = getDeviceProfile("mbp_14_m4_2024");
    const next = applyDeviceProfile({ name: "test", browser_engine: "cloakbrowser" }, preset);

    expect(next.device_memory).toBe(8);
  });

  it("filters profile lists by platform", () => {
    const windowsProfiles = getDeviceProfilesForPlatform("windows");
    const macProfiles = getDeviceProfilesForPlatform("macos");

    expect(windowsProfiles.length).toBeGreaterThan(1);
    expect(windowsProfiles.every((profile) => profile.platform === "windows")).toBe(true);
    // A Mac also runs the iPhone looks; nothing else but its own system.
    expect(macProfiles.every((profile) => profile.platform === "macos" || profile.platform === "ios")).toBe(true);
    expect(macProfiles.filter((profile) => profile.platform === "macos").length).toBeGreaterThan(1);
  });
});

describe("iPhone presets in the previous panel", () => {
  it("are offered on a Mac only, and force the CloakBrowser engine", () => {
    expect(getDeviceProfilesForPlatform("macos").some((preset) => preset.platform === "ios")).toBe(true);
    expect(getDeviceProfilesForPlatform("windows").some((preset) => preset.platform === "ios")).toBe(false);
    const next = applyDeviceProfile({ name: "t", browser_engine: "system_chrome" }, getDeviceProfile("iphone_15"));
    expect(next).toMatchObject({ platform: "ios", browser_engine: "cloakbrowser", device_memory: null, gpu_renderer: "Apple GPU" });
    expect(next.user_agent).toContain("iPhone");
  });
});
