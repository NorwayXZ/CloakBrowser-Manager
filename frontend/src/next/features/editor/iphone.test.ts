import { describe, expect, it } from "vitest";
import {
  applyDeviceProfile,
  getDeviceProfile,
  getDeviceProfileFamiliesForExactPlatform,
  getDeviceProfileFamiliesForPlatform,
  getDeviceProfilesForExactPlatform,
  getDeviceProfilesForPlatform,
} from "./deviceProfiles";
import { buildPayload, changeDevice, changePlatform, createDefaultForm, initialState, platformLabel, randomizeDevice, screenFollowsDisplay, selectedDevice } from "./model";
import { deviceText } from "../profiles/format";
import type { Profile } from "../profiles/types";

describe("iPhone presets", () => {
  it("are offered on a Mac and not on a Windows PC", () => {
    expect(getDeviceProfileFamiliesForPlatform("macos")).toContain("iPhone");
    expect(getDeviceProfileFamiliesForPlatform("windows")).not.toContain("iPhone");
    expect(getDeviceProfilesForPlatform("windows").some((preset) => preset.platform === "ios")).toBe(false);
    expect(getDeviceProfilesForPlatform("macos").filter((preset) => preset.platform === "ios").length).toBeGreaterThanOrEqual(8);
  });

  it("look like the phone: Safari UA, Apple GPU, no deviceMemory, the phone's screen", () => {
    const phone = getDeviceProfile("iphone_16_pro");
    expect(phone).toMatchObject({ platform: "ios", family: "iPhone", screen_width: 402, screen_height: 874, device_memory: null });
    expect(phone.user_agent).toContain("iPhone; CPU iPhone OS");
    expect(phone.user_agent).not.toContain("Chrome");
    expect([phone.gpu_vendor, phone.gpu_renderer]).toEqual(["Apple Inc.", "Apple GPU"]);
  });

  it("force the CloakBrowser engine, because only the kernel takes the persona's switches", () => {
    const next = applyDeviceProfile({ name: "t", browser_engine: "system_chrome" }, getDeviceProfile("iphone_15"));
    expect(next.browser_engine).toBe("cloakbrowser");
    expect(next.platform).toBe("ios");
    expect(next.user_agent).toContain("iPhone");
    expect(next.gpu_renderer).toBe("Apple GPU");
  });
});

describe("an iPhone profile in the editor", () => {
  it("is picked from the Mac's device list and survives the save", () => {
    const form = changeDevice(createDefaultForm("macos"), "iphone_15", "macos");
    expect(form.platform).toBe("ios");
    const payload = buildPayload(form, "macos");
    expect(payload).toMatchObject({ platform: "ios", device_profile: "iphone_15", screen_width: 393, screen_height: 852 });
    expect(selectedDevice(form, "macos").id).toBe("iphone_15");
  });

  it("is not turned back into a Mac when it is opened", () => {
    const stored = { ...createDefaultForm("macos"), id: "p1", name: "iPhone", platform: "ios", device_profile: "iphone_16" } as unknown as Profile;
    const { form } = initialState(stored, "macos");
    expect(form.platform).toBe("ios");
    expect(form.device_profile).toBe("iphone_16");
  });

  it("has no place on a Windows PC and falls back to that PC's own device", () => {
    const stored = { ...createDefaultForm("macos"), id: "p1", name: "iPhone", platform: "ios", device_profile: "iphone_16" } as unknown as Profile;
    const { form } = initialState(stored, "windows");
    expect(form.platform).toBe("windows");
  });

  it("stays an iPhone when the model is re-rolled", () => {
    const start = changeDevice(createDefaultForm("macos"), "iphone_15", "macos");
    for (const roll of [0, 0.3, 0.6, 0.99]) {
      const next = randomizeDevice(start, "macos", () => roll);
      expect(next.platform).toBe("ios");
      expect(next.device_profile).not.toBe("iphone_15");
    }
  });

  it("re-rolling a Mac never picks an iPhone", () => {
    const start = createDefaultForm("macos");
    for (let step = 0; step < 20; step += 1) {
      expect(randomizeDevice(start, "macos", () => step / 20).platform).toBe("macos");
    }
  });

  it("is labelled as an iPhone", () => {
    expect(platformLabel("ios")).toContain("iPhone");
  });

  it("keeps the kernel engine and its own screen when an API-created profile is opened", () => {
    const stored = { ...createDefaultForm("macos"), id: "p1", name: "iPhone", platform: "ios", device_profile: "iphone_15", browser_engine: "auto" } as unknown as Profile;
    const { form } = initialState(stored, "macos");
    expect(form.browser_engine).toBe("cloakbrowser");
    expect(screenFollowsDisplay(form, [2560, 1440])).toBe(false);
    expect(screenFollowsDisplay({ ...form, platform: "macos" }, [2560, 1440])).toBe(true);
  });

  it("can re-roll to any iPhone but the current one, including the default model", () => {
    const start = changeDevice(createDefaultForm("macos"), "iphone_16", "macos");
    const reached = new Set<string>();
    for (let step = 0; step < 40; step += 1) reached.add(randomizeDevice(start, "macos", () => step / 40).device_profile ?? "");
    expect(reached.has("iphone_15")).toBe(true);
    expect(reached.has("iphone_16")).toBe(false);
  });

  it("is listed by its model name", () => {
    const stored = { id: "p1", name: "x", platform: "ios", device_profile: "iphone_16_pro" } as unknown as Profile;
    expect(deviceText(stored)).toBe("iPhone 16 Pro");
  });

  it("separates macOS desktop presets from iOS phone presets when OS is switched", () => {
    expect(getDeviceProfileFamiliesForExactPlatform("macos")).not.toContain("iPhone");
    expect(getDeviceProfilesForExactPlatform("macos").every((p) => p.platform === "macos")).toBe(true);
    expect(getDeviceProfileFamiliesForExactPlatform("ios")).toEqual(["iPhone"]);
    expect(getDeviceProfilesForExactPlatform("ios").every((p) => p.platform === "ios")).toBe(true);

    const start = createDefaultForm("macos");
    const iosForm = changePlatform({ ...start, fingerprint_options: { ...start.fingerprint_options, brand: "Edge", platform_version: "15.6.0" } }, "ios", "macos");
    expect(iosForm).toMatchObject({ platform: "ios", device_profile: "iphone_15", browser_engine: "cloakbrowser", screen_width: 393, screen_height: 852 });
    expect(iosForm.fingerprint_options?.brand).toBeNull();
    expect(iosForm.fingerprint_options?.platform_version).toBeNull();
    expect(iosForm.fingerprint_options?.noise).toBeNull();

    const backToMac = changePlatform(iosForm, "macos", "macos");
    expect(backToMac).toMatchObject({ platform: "macos", device_profile: "native_macos", user_agent: null });
    expect(backToMac.fingerprint_options?.noise).toBe(false);
  });
});
