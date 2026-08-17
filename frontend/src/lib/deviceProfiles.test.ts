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
  });

  it("filters profile lists by platform", () => {
    const windowsProfiles = getDeviceProfilesForPlatform("windows");
    const macProfiles = getDeviceProfilesForPlatform("macos");

    expect(windowsProfiles.length).toBeGreaterThan(1);
    expect(windowsProfiles.every((profile) => profile.platform === "windows")).toBe(true);
    expect(macProfiles.every((profile) => profile.platform === "macos")).toBe(true);
  });
});
