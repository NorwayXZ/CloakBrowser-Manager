import type { BrowserEngine, HostOS, ProfileCreateData } from "./api";

export type DeviceProfileId = string;
export type DevicePlatform = "macos" | "windows";

export type DeviceProfileFamily =
  | "原生"
  | "Windows 笔记本"
  | "Windows 台式机"
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
  platform: DevicePlatform;
  screen_width: number;
  screen_height: number;
  hardware_concurrency: number | null;
  device_memory: number | null;
  gpu_vendor: string | null;
  gpu_renderer: string | null;
  user_agent: string | null;
  color_scheme?: "light" | "dark" | "no-preference" | null;
}

const APPLE_GPU_VENDOR = "Google Inc. (Apple)";
const WINDOWS_INTEL_GPU_VENDOR = "Google Inc. (Intel)";
const WINDOWS_NVIDIA_GPU_VENDOR = "Google Inc. (NVIDIA)";
const WINDOWS_AMD_GPU_VENDOR = "Google Inc. (AMD)";

function appleRenderer(chip: string): string {
  return `ANGLE (Apple, ANGLE Metal Renderer: Apple ${chip}, Unspecified Version)`;
}

function windowsRenderer(vendor: "Intel" | "NVIDIA" | "AMD", renderer: string): string {
  return `ANGLE (${vendor}, ${renderer} Direct3D11 vs_5_0 ps_5_0, D3D11)`;
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
    device_memory: 8,
    gpu_vendor: APPLE_GPU_VENDOR,
    gpu_renderer: appleRenderer(chip),
    user_agent: null,
    color_scheme: null,
  };
}

function windowsProfile(
  id: string,
  family: DeviceProfileFamily,
  name: string,
  cpu: string,
  screenWidth: number,
  screenHeight: number,
  cpuThreads: number,
  gpuVendor: string,
  gpuRenderer: string,
): DeviceProfilePreset {
  return {
    id,
    name,
    family,
    chip: cpu,
    platform: "windows",
    screen_width: screenWidth,
    screen_height: screenHeight,
    hardware_concurrency: cpuThreads,
    device_memory: 8,
    gpu_vendor: gpuVendor,
    gpu_renderer: gpuRenderer,
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
    device_memory: null,
    gpu_vendor: null,
    gpu_renderer: null,
    user_agent: null,
    color_scheme: null,
  },
  {
    id: "native_windows",
    name: "真实 Windows 原生",
    family: "原生",
    chip: "Native",
    platform: "windows",
    screen_width: 1920,
    screen_height: 1080,
    hardware_concurrency: null,
    device_memory: null,
    gpu_vendor: null,
    gpu_renderer: null,
    user_agent: null,
    color_scheme: null,
  },

  windowsProfile(
    "win_laptop_iris_xe_2256",
    "Windows 笔记本",
    "Windows 笔记本 · Intel Iris Xe · 2256×1504",
    "Intel Core i5 / i7 U 系列",
    2256,
    1504,
    8,
    WINDOWS_INTEL_GPU_VENDOR,
    windowsRenderer("Intel", "Intel(R) Iris(R) Xe Graphics"),
  ),
  windowsProfile(
    "win_laptop_iris_xe_1920",
    "Windows 笔记本",
    "Windows 笔记本 · Intel Iris Xe · 1920×1200",
    "Intel Core i5 / i7 P 系列",
    1920,
    1200,
    12,
    WINDOWS_INTEL_GPU_VENDOR,
    windowsRenderer("Intel", "Intel(R) Iris(R) Xe Graphics"),
  ),
  windowsProfile(
    "win_laptop_arc_2880",
    "Windows 笔记本",
    "Windows 笔记本 · Intel Arc · 2880×1800",
    "Intel Core Ultra 5 / 7",
    2880,
    1800,
    16,
    WINDOWS_INTEL_GPU_VENDOR,
    windowsRenderer("Intel", "Intel(R) Arc(TM) Graphics"),
  ),
  windowsProfile(
    "win_laptop_rtx_4060_2560",
    "Windows 笔记本",
    "Windows 游戏本 · RTX 4060 Laptop · 2560×1600",
    "Intel Core i7 / Ryzen 7 H 系列",
    2560,
    1600,
    16,
    WINDOWS_NVIDIA_GPU_VENDOR,
    windowsRenderer("NVIDIA", "NVIDIA GeForce RTX 4060 Laptop GPU"),
  ),
  windowsProfile(
    "win_desktop_uhd_770_1080",
    "Windows 台式机",
    "Windows 台式机 · Intel UHD 770 · 1920×1080",
    "Intel Core i5 / i7 台式机",
    1920,
    1080,
    16,
    WINDOWS_INTEL_GPU_VENDOR,
    windowsRenderer("Intel", "Intel(R) UHD Graphics 770"),
  ),
  windowsProfile(
    "win_desktop_rtx_3060_1440",
    "Windows 台式机",
    "Windows 台式机 · RTX 3060 · 2560×1440",
    "Intel Core i5 / Ryzen 5 台式机",
    2560,
    1440,
    12,
    WINDOWS_NVIDIA_GPU_VENDOR,
    windowsRenderer("NVIDIA", "NVIDIA GeForce RTX 3060"),
  ),
  windowsProfile(
    "win_desktop_rtx_4060_1440",
    "Windows 台式机",
    "Windows 台式机 · RTX 4060 · 2560×1440",
    "Intel Core i7 / Ryzen 7 台式机",
    2560,
    1440,
    16,
    WINDOWS_NVIDIA_GPU_VENDOR,
    windowsRenderer("NVIDIA", "NVIDIA GeForce RTX 4060"),
  ),
  windowsProfile(
    "win_desktop_rx_6600_1440",
    "Windows 台式机",
    "Windows 台式机 · Radeon RX 6600 · 2560×1440",
    "AMD Ryzen 5 / Ryzen 7 台式机",
    2560,
    1440,
    16,
    WINDOWS_AMD_GPU_VENDOR,
    windowsRenderer("AMD", "AMD Radeon RX 6600"),
  ),

  appleProfile("mba_13_m1_2020", "MacBook Air", "MacBook Air 13 M1 (2020)", "M1", 1440, 900, 8),
  appleProfile("mba_13_m2_2022", "MacBook Air", "MacBook Air 13 M2 (2022)", "M2", 1470, 956, 8),
  appleProfile("mba_15_m2_2023", "MacBook Air", "MacBook Air 15 M2 (2023)", "M2", 1710, 1107, 8),
  appleProfile("mba_13_m3_2024", "MacBook Air", "MacBook Air 13 M3 (2024)", "M3", 1470, 956, 8),
  appleProfile("mba_15_m3_2024", "MacBook Air", "MacBook Air 15 M3 (2024)", "M3", 1710, 1107, 8),
  appleProfile("mba_13_m4_2025", "MacBook Air", "MacBook Air 13 M4 (2025)", "M4", 1470, 956, 10),
  appleProfile("mba_15_m4_2025", "MacBook Air", "MacBook Air 15 M4 (2025)", "M4", 1710, 1107, 10),
  appleProfile("mba_13_m5", "MacBook Air", "MacBook Air 13 M5", "M5", 1470, 956, 10),
  appleProfile("mba_15_m5", "MacBook Air", "MacBook Air 15 M5", "M5", 1710, 1107, 10),

  appleProfile("mbp_13_m1_2020", "MacBook Pro", "MacBook Pro 13 M1 (2020)", "M1", 1440, 900, 8),
  appleProfile("mbp_13_m2_2022", "MacBook Pro", "MacBook Pro 13 M2 (2022)", "M2", 1440, 900, 8),
  appleProfile("mbp_14_m1_pro_2021", "MacBook Pro", "MacBook Pro 14 M1 Pro (2021)", "M1 Pro", 1512, 982, 10),
  appleProfile("mbp_14_m1_max_2021", "MacBook Pro", "MacBook Pro 14 M1 Max (2021)", "M1 Max", 1512, 982, 10),
  appleProfile("mbp_16_m1_pro_2021", "MacBook Pro", "MacBook Pro 16 M1 Pro (2021)", "M1 Pro", 1728, 1117, 10),
  appleProfile("mbp_16_m1_max_2021", "MacBook Pro", "MacBook Pro 16 M1 Max (2021)", "M1 Max", 1728, 1117, 10),
  appleProfile("mbp_14_m2_pro_2023", "MacBook Pro", "MacBook Pro 14 M2 Pro (2023)", "M2 Pro", 1512, 982, 12),
  appleProfile("mbp_14_m2_max_2023", "MacBook Pro", "MacBook Pro 14 M2 Max (2023)", "M2 Max", 1512, 982, 12),
  appleProfile("mbp_16_m2_pro_2023", "MacBook Pro", "MacBook Pro 16 M2 Pro (2023)", "M2 Pro", 1728, 1117, 12),
  appleProfile("mbp_16_m2_max_2023", "MacBook Pro", "MacBook Pro 16 M2 Max (2023)", "M2 Max", 1728, 1117, 12),
  appleProfile("mbp_14_m3_2023", "MacBook Pro", "MacBook Pro 14 M3 (2023)", "M3", 1512, 982, 8),
  appleProfile("mbp_14_m3_pro_2023", "MacBook Pro", "MacBook Pro 14 M3 Pro (2023)", "M3 Pro", 1512, 982, 12),
  appleProfile("mbp_14_m3_max_2023", "MacBook Pro", "MacBook Pro 14 M3 Max (2023)", "M3 Max", 1512, 982, 16),
  appleProfile("mbp_16_m3_pro_2023", "MacBook Pro", "MacBook Pro 16 M3 Pro (2023)", "M3 Pro", 1728, 1117, 12),
  appleProfile("mbp_16_m3_max_2023", "MacBook Pro", "MacBook Pro 16 M3 Max (2023)", "M3 Max", 1728, 1117, 16),
  appleProfile("mbp_14_m4_2024", "MacBook Pro", "MacBook Pro 14 M4 (2024)", "M4", 1512, 982, 10),
  appleProfile("mbp_14_m4_pro_2024", "MacBook Pro", "MacBook Pro 14 M4 Pro (2024)", "M4 Pro", 1512, 982, 14),
  appleProfile("mbp_14_m4_max_2024", "MacBook Pro", "MacBook Pro 14 M4 Max (2024)", "M4 Max", 1512, 982, 16),
  appleProfile("mbp_16_m4_pro_2024", "MacBook Pro", "MacBook Pro 16 M4 Pro (2024)", "M4 Pro", 1728, 1117, 14),
  appleProfile("mbp_16_m4_max_2024", "MacBook Pro", "MacBook Pro 16 M4 Max (2024)", "M4 Max", 1728, 1117, 16),
  appleProfile("mbp_14_m5", "MacBook Pro", "MacBook Pro 14 M5", "M5", 1512, 982, 10),
  appleProfile("mbp_14_m5_pro", "MacBook Pro", "MacBook Pro 14 M5 Pro", "M5 Pro", 1512, 982, 14),
  appleProfile("mbp_14_m5_max", "MacBook Pro", "MacBook Pro 14 M5 Max", "M5 Max", 1512, 982, 16),
  appleProfile("mbp_16_m5_pro", "MacBook Pro", "MacBook Pro 16 M5 Pro", "M5 Pro", 1728, 1117, 14),
  appleProfile("mbp_16_m5_max", "MacBook Pro", "MacBook Pro 16 M5 Max", "M5 Max", 1728, 1117, 16),

  appleProfile("imac_24_m1_2021", "iMac", "iMac 24 M1 (2021)", "M1", 2240, 1260, 8),
  appleProfile("imac_24_m3_2023", "iMac", "iMac 24 M3 (2023)", "M3", 2240, 1260, 8),
  appleProfile("imac_24_m4_2024", "iMac", "iMac 24 M4 (2024)", "M4", 2240, 1260, 10),

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
  "Windows 笔记本",
  "Windows 台式机",
  "MacBook Air",
  "MacBook Pro",
  "iMac",
  "Mac mini",
  "Mac Studio",
  "Mac Pro",
];

export const DEFAULT_DEVICE_PROFILE_ID: DeviceProfileId = "native_macos";
export const DEFAULT_DEVICE_PROFILE_IDS: Record<DevicePlatform, DeviceProfileId> = {
  macos: "native_macos",
  windows: "native_windows",
};

export function getDevicePlatformForHost(hostOS?: HostOS | null): DevicePlatform {
  return hostOS === "windows" ? "windows" : "macos";
}

export function getDefaultDeviceProfileId(hostOS?: HostOS | DevicePlatform | null): DeviceProfileId {
  return hostOS === "windows" ? DEFAULT_DEVICE_PROFILE_IDS.windows : DEFAULT_DEVICE_PROFILE_IDS.macos;
}

export function getDeviceProfile(id?: string | null): DeviceProfilePreset {
  return DEVICE_PROFILES.find((profile) => profile.id === id) ?? DEVICE_PROFILES[0]!;
}

export function getDeviceProfilesForPlatform(platform: DevicePlatform): DeviceProfilePreset[] {
  return DEVICE_PROFILES.filter((profile) => profile.platform === platform);
}

export function getDeviceProfileFamiliesForPlatform(platform: DevicePlatform): DeviceProfileFamily[] {
  return DEVICE_PROFILE_FAMILIES.filter((family) => (
    DEVICE_PROFILES.some((profile) => profile.platform === platform && profile.family === family)
  ));
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
    platform: preset.platform,
    screen_width: preset.screen_width,
    screen_height: preset.screen_height,
    gpu_vendor: isNative ? null : preset.gpu_vendor,
    gpu_renderer: isNative ? null : preset.gpu_renderer,
    hardware_concurrency: isNative ? null : preset.hardware_concurrency,
    device_memory: isNative ? null : preset.device_memory,
    user_agent: isNative ? null : preset.user_agent,
    color_scheme: preset.color_scheme ?? null,
    fingerprint_seed: current.fingerprint_seed ?? randomFingerprintSeed(),
  };
}
