import type { BrowserEngine, ProfileCreateData } from "./api";

export type DeviceProfileId = string;

export type DeviceProfileFamily =
  | "原生"
  | "MacBook Air"
  | "MacBook Pro"
  | "iMac"
  | "Mac mini"
  | "Mac Studio"
  | "Mac Pro";

export interface DeviceProfilePreset {
  id: DeviceProfileId;
  name: string;
  family: DeviceProfileFamily;
  chip: string;
  platform: "macos";
  screen_width: number;
  screen_height: number;
  hardware_concurrency: number | null;
  gpu_vendor: string | null;
  gpu_renderer: string | null;
  user_agent: string | null;
  color_scheme?: "light" | "dark" | "no-preference" | null;
}

const APPLE_GPU_VENDOR = "Google Inc. (Apple)";

function appleRenderer(chip: string): string {
  return `ANGLE (Apple, ANGLE Metal Renderer: Apple ${chip}, Unspecified Version)`;
}

function appleProfile(
  id: string,
  family: DeviceProfileFamily,
  name: string,
  chip: string,
  screenWidth: number,
  screenHeight: number,
  cpuThreads: number,
): DeviceProfilePreset {
  return {
    id,
    name,
    family,
    chip,
    platform: "macos",
    screen_width: screenWidth,
    screen_height: screenHeight,
    hardware_concurrency: cpuThreads,
    gpu_vendor: APPLE_GPU_VENDOR,
    gpu_renderer: appleRenderer(chip),
    user_agent: null,
    color_scheme: null,
  };
}

export const DEVICE_PROFILES: DeviceProfilePreset[] = [
  {
    id: "native_macos",
    name: "真实 Mac 原生",
    family: "原生",
    chip: "Native",
    platform: "macos",
    screen_width: 1280,
    screen_height: 720,
    hardware_concurrency: null,
    gpu_vendor: null,
    gpu_renderer: null,
    user_agent: null,
    color_scheme: null,
  },

  appleProfile("mba_13_m1_2020", "MacBook Air", "MacBook Air 13 M1 (2020)", "M1", 2560, 1600, 8),
  appleProfile("mba_13_m2_2022", "MacBook Air", "MacBook Air 13 M2 (2022)", "M2", 2560, 1664, 8),
  appleProfile("mba_15_m2_2023", "MacBook Air", "MacBook Air 15 M2 (2023)", "M2", 2880, 1864, 8),
  appleProfile("mba_13_m3_2024", "MacBook Air", "MacBook Air 13 M3 (2024)", "M3", 2560, 1664, 8),
  appleProfile("mba_15_m3_2024", "MacBook Air", "MacBook Air 15 M3 (2024)", "M3", 2880, 1864, 8),
  appleProfile("mba_13_m4_2025", "MacBook Air", "MacBook Air 13 M4 (2025)", "M4", 2560, 1664, 10),
  appleProfile("mba_15_m4_2025", "MacBook Air", "MacBook Air 15 M4 (2025)", "M4", 2880, 1864, 10),
  appleProfile("mba_13_m5", "MacBook Air", "MacBook Air 13 M5", "M5", 2560, 1664, 10),
  appleProfile("mba_15_m5", "MacBook Air", "MacBook Air 15 M5", "M5", 2880, 1864, 10),

  appleProfile("mbp_13_m1_2020", "MacBook Pro", "MacBook Pro 13 M1 (2020)", "M1", 2560, 1600, 8),
  appleProfile("mbp_13_m2_2022", "MacBook Pro", "MacBook Pro 13 M2 (2022)", "M2", 2560, 1600, 8),
  appleProfile("mbp_14_m1_pro_2021", "MacBook Pro", "MacBook Pro 14 M1 Pro (2021)", "M1 Pro", 3024, 1964, 10),
  appleProfile("mbp_14_m1_max_2021", "MacBook Pro", "MacBook Pro 14 M1 Max (2021)", "M1 Max", 3024, 1964, 10),
  appleProfile("mbp_16_m1_pro_2021", "MacBook Pro", "MacBook Pro 16 M1 Pro (2021)", "M1 Pro", 3456, 2234, 10),
  appleProfile("mbp_16_m1_max_2021", "MacBook Pro", "MacBook Pro 16 M1 Max (2021)", "M1 Max", 3456, 2234, 10),
  appleProfile("mbp_14_m2_pro_2023", "MacBook Pro", "MacBook Pro 14 M2 Pro (2023)", "M2 Pro", 3024, 1964, 12),
  appleProfile("mbp_14_m2_max_2023", "MacBook Pro", "MacBook Pro 14 M2 Max (2023)", "M2 Max", 3024, 1964, 12),
  appleProfile("mbp_16_m2_pro_2023", "MacBook Pro", "MacBook Pro 16 M2 Pro (2023)", "M2 Pro", 3456, 2234, 12),
  appleProfile("mbp_16_m2_max_2023", "MacBook Pro", "MacBook Pro 16 M2 Max (2023)", "M2 Max", 3456, 2234, 12),
  appleProfile("mbp_14_m3_2023", "MacBook Pro", "MacBook Pro 14 M3 (2023)", "M3", 3024, 1964, 8),
  appleProfile("mbp_14_m3_pro_2023", "MacBook Pro", "MacBook Pro 14 M3 Pro (2023)", "M3 Pro", 3024, 1964, 12),
  appleProfile("mbp_14_m3_max_2023", "MacBook Pro", "MacBook Pro 14 M3 Max (2023)", "M3 Max", 3024, 1964, 16),
  appleProfile("mbp_16_m3_pro_2023", "MacBook Pro", "MacBook Pro 16 M3 Pro (2023)", "M3 Pro", 3456, 2234, 12),
  appleProfile("mbp_16_m3_max_2023", "MacBook Pro", "MacBook Pro 16 M3 Max (2023)", "M3 Max", 3456, 2234, 16),
  appleProfile("mbp_14_m4_2024", "MacBook Pro", "MacBook Pro 14 M4 (2024)", "M4", 3024, 1964, 10),
  appleProfile("mbp_14_m4_pro_2024", "MacBook Pro", "MacBook Pro 14 M4 Pro (2024)", "M4 Pro", 3024, 1964, 14),
  appleProfile("mbp_14_m4_max_2024", "MacBook Pro", "MacBook Pro 14 M4 Max (2024)", "M4 Max", 3024, 1964, 16),
  appleProfile("mbp_16_m4_pro_2024", "MacBook Pro", "MacBook Pro 16 M4 Pro (2024)", "M4 Pro", 3456, 2234, 14),
  appleProfile("mbp_16_m4_max_2024", "MacBook Pro", "MacBook Pro 16 M4 Max (2024)", "M4 Max", 3456, 2234, 16),
  appleProfile("mbp_14_m5", "MacBook Pro", "MacBook Pro 14 M5", "M5", 3024, 1964, 10),
  appleProfile("mbp_14_m5_pro", "MacBook Pro", "MacBook Pro 14 M5 Pro", "M5 Pro", 3024, 1964, 14),
  appleProfile("mbp_14_m5_max", "MacBook Pro", "MacBook Pro 14 M5 Max", "M5 Max", 3024, 1964, 16),
  appleProfile("mbp_16_m5_pro", "MacBook Pro", "MacBook Pro 16 M5 Pro", "M5 Pro", 3456, 2234, 14),
  appleProfile("mbp_16_m5_max", "MacBook Pro", "MacBook Pro 16 M5 Max", "M5 Max", 3456, 2234, 16),

  appleProfile("imac_24_m1_2021", "iMac", "iMac 24 M1 (2021)", "M1", 4480, 2520, 8),
  appleProfile("imac_24_m3_2023", "iMac", "iMac 24 M3 (2023)", "M3", 4480, 2520, 8),
  appleProfile("imac_24_m4_2024", "iMac", "iMac 24 M4 (2024)", "M4", 4480, 2520, 10),

  appleProfile("mac_mini_m1_2020", "Mac mini", "Mac mini M1 (2020)", "M1", 2560, 1440, 8),
  appleProfile("mac_mini_m2_2023", "Mac mini", "Mac mini M2 (2023)", "M2", 2560, 1440, 8),
  appleProfile("mac_mini_m2_pro_2023", "Mac mini", "Mac mini M2 Pro (2023)", "M2 Pro", 3840, 2160, 12),
  appleProfile("mac_mini_m4_2024", "Mac mini", "Mac mini M4 (2024)", "M4", 2560, 1440, 10),
  appleProfile("mac_mini_m4_pro_2024", "Mac mini", "Mac mini M4 Pro (2024)", "M4 Pro", 3840, 2160, 14),

  appleProfile("mac_studio_m1_max_2022", "Mac Studio", "Mac Studio M1 Max (2022)", "M1 Max", 3840, 2160, 10),
  appleProfile("mac_studio_m1_ultra_2022", "Mac Studio", "Mac Studio M1 Ultra (2022)", "M1 Ultra", 5120, 2880, 20),
  appleProfile("mac_studio_m2_max_2023", "Mac Studio", "Mac Studio M2 Max (2023)", "M2 Max", 3840, 2160, 12),
  appleProfile("mac_studio_m2_ultra_2023", "Mac Studio", "Mac Studio M2 Ultra (2023)", "M2 Ultra", 5120, 2880, 24),
  appleProfile("mac_studio_m4_max_2025", "Mac Studio", "Mac Studio M4 Max (2025)", "M4 Max", 3840, 2160, 16),
  appleProfile("mac_studio_m3_ultra_2025", "Mac Studio", "Mac Studio M3 Ultra (2025)", "M3 Ultra", 5120, 2880, 28),

  appleProfile("mac_pro_m2_ultra_2023", "Mac Pro", "Mac Pro M2 Ultra (2023)", "M2 Ultra", 5120, 2880, 24),
];

export const DEVICE_PROFILE_FAMILIES: DeviceProfileFamily[] = [
  "原生",
  "MacBook Air",
  "MacBook Pro",
  "iMac",
  "Mac mini",
  "Mac Studio",
  "Mac Pro",
];

export const DEFAULT_DEVICE_PROFILE_ID: DeviceProfileId = "native_macos";

export function getDeviceProfile(id?: string | null): DeviceProfilePreset {
  return DEVICE_PROFILES.find((profile) => profile.id === id) ?? DEVICE_PROFILES[0]!;
}

export function randomFingerprintSeed() {
  return Math.floor(Math.random() * 90000) + 10000;
}

function normalizeEngine(value?: BrowserEngine | string | null): BrowserEngine {
  return value === "cloakbrowser" ? "cloakbrowser" : "system_chrome";
}

export function applyDeviceProfile(
  current: ProfileCreateData,
  preset: DeviceProfilePreset,
): ProfileCreateData {
  const browserEngine = normalizeEngine(current.browser_engine);
  const isNative = browserEngine === "system_chrome";

  return {
    ...current,
    browser_engine: browserEngine,
    device_profile: preset.id,
    platform: "macos",
    screen_width: preset.screen_width,
    screen_height: preset.screen_height,
    gpu_vendor: isNative ? null : preset.gpu_vendor,
    gpu_renderer: isNative ? null : preset.gpu_renderer,
    hardware_concurrency: isNative ? null : preset.hardware_concurrency,
    user_agent: isNative ? null : preset.user_agent,
    color_scheme: preset.color_scheme ?? null,
    fingerprint_seed: current.fingerprint_seed ?? randomFingerprintSeed(),
  };
}
