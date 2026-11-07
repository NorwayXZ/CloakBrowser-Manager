"""One-click profile reset: the same profile, as a brand-new browser.

A sign-up that failed leaves cookies, storage and a fingerprint a site has
already seen. Reset wipes the profile's browser data and rolls a fresh
persona (seed, device, screen, GPU, CPU, memory, user agent) while the
profile itself stays: name, group, notes, tags, proxy binding and its
rotation link are untouched. Timezone and language are cleared so the next
launch matches them to the proxy's exit IP again.

The device presets mirror the panel's editor list
(frontend/src/next/features/editor/deviceProfiles.ts) so a reset profile
opens in the editor on a preset it knows; test_profile_reset checks that the
two lists keep the same ids.
"""

from __future__ import annotations

import logging
import secrets
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# What happens to the profile's mail addresses and vault entries.
BINDING_CHOICES = ("unbind", "keep", "delete")

_APPLE_GPU_VENDOR = "Google Inc. (Apple)"


def _apple(device_id: str, chip: str, width: int, height: int, cores: int) -> dict[str, Any]:
    return {
        "id": device_id,
        "platform": "macos",
        "screen_width": width,
        "screen_height": height,
        "hardware_concurrency": cores,
        "device_memory": 8,
        "gpu_vendor": _APPLE_GPU_VENDOR,
        "gpu_renderer": f"ANGLE (Apple, ANGLE Metal Renderer: Apple {chip}, Unspecified Version)",
    }


def _windows(device_id: str, width: int, height: int, cores: int, vendor: str, model: str, pci_id: str) -> dict[str, Any]:
    return {
        "id": device_id,
        "platform": "windows",
        "screen_width": width,
        "screen_height": height,
        "hardware_concurrency": cores,
        "device_memory": 8,
        "gpu_vendor": f"Google Inc. ({vendor})",
        # Chrome on Windows includes the PCI device id; a renderer without it matches no real machine.
        "gpu_renderer": f"ANGLE ({vendor}, {model} (0x{int(pci_id, 16):08X}) Direct3D11 vs_5_0 ps_5_0, D3D11)",
    }


# The editor's presets minus the two "原生" ones (a reset picks a device, the
# way the editor's 随机设备型号 does).
DEVICE_PRESETS: tuple[dict[str, Any], ...] = (
    _windows("win_laptop_iris_xe_2256", 2256, 1504, 8, "Intel", "Intel(R) Iris(R) Xe Graphics", "9A49"),
    _windows("win_laptop_iris_xe_1920", 1920, 1200, 12, "Intel", "Intel(R) Iris(R) Xe Graphics", "46A6"),
    _windows("win_laptop_arc_2880", 2880, 1800, 16, "Intel", "Intel(R) Arc(TM) Graphics", "7D55"),
    _windows("win_laptop_rtx_4060_2560", 2560, 1600, 16, "NVIDIA", "NVIDIA GeForce RTX 4060 Laptop GPU", "28A0"),
    _windows("win_desktop_uhd_770_1080", 1920, 1080, 16, "Intel", "Intel(R) UHD Graphics 770", "4680"),
    _windows("win_desktop_rtx_3060_1440", 2560, 1440, 12, "NVIDIA", "NVIDIA GeForce RTX 3060", "2503"),
    _windows("win_desktop_rtx_4060_1440", 2560, 1440, 16, "NVIDIA", "NVIDIA GeForce RTX 4060", "2882"),
    _windows("win_desktop_rx_6600_1440", 2560, 1440, 16, "AMD", "AMD Radeon RX 6600", "73FF"),
    _apple("mba_13_m1_2020", "M1", 1440, 900, 8),
    _apple("mba_13_m2_2022", "M2", 1470, 956, 8),
    _apple("mba_15_m2_2023", "M2", 1710, 1107, 8),
    _apple("mba_13_m3_2024", "M3", 1470, 956, 8),
    _apple("mba_15_m3_2024", "M3", 1710, 1107, 8),
    _apple("mba_13_m4_2025", "M4", 1470, 956, 10),
    _apple("mba_15_m4_2025", "M4", 1710, 1107, 10),
    _apple("mba_13_m5", "M5", 1470, 956, 10),
    _apple("mba_15_m5", "M5", 1710, 1107, 10),
    _apple("mbp_13_m1_2020", "M1", 1440, 900, 8),
    _apple("mbp_13_m2_2022", "M2", 1440, 900, 8),
    _apple("mbp_14_m1_pro_2021", "M1 Pro", 1512, 982, 10),
    _apple("mbp_14_m1_max_2021", "M1 Max", 1512, 982, 10),
    _apple("mbp_16_m1_pro_2021", "M1 Pro", 1728, 1117, 10),
    _apple("mbp_16_m1_max_2021", "M1 Max", 1728, 1117, 10),
    _apple("mbp_14_m2_pro_2023", "M2 Pro", 1512, 982, 12),
    _apple("mbp_14_m2_max_2023", "M2 Max", 1512, 982, 12),
    _apple("mbp_16_m2_pro_2023", "M2 Pro", 1728, 1117, 12),
    _apple("mbp_16_m2_max_2023", "M2 Max", 1728, 1117, 12),
    _apple("mbp_14_m3_2023", "M3", 1512, 982, 8),
    _apple("mbp_14_m3_pro_2023", "M3 Pro", 1512, 982, 12),
    _apple("mbp_14_m3_max_2023", "M3 Max", 1512, 982, 16),
    _apple("mbp_16_m3_pro_2023", "M3 Pro", 1728, 1117, 12),
    _apple("mbp_16_m3_max_2023", "M3 Max", 1728, 1117, 16),
    _apple("mbp_14_m4_2024", "M4", 1512, 982, 10),
    _apple("mbp_14_m4_pro_2024", "M4 Pro", 1512, 982, 14),
    _apple("mbp_14_m4_max_2024", "M4 Max", 1512, 982, 16),
    _apple("mbp_16_m4_pro_2024", "M4 Pro", 1728, 1117, 14),
    _apple("mbp_16_m4_max_2024", "M4 Max", 1728, 1117, 16),
    _apple("mbp_14_m5", "M5", 1512, 982, 10),
    _apple("mbp_14_m5_pro", "M5 Pro", 1512, 982, 14),
    _apple("mbp_14_m5_max", "M5 Max", 1512, 982, 16),
    _apple("mbp_16_m5_pro", "M5 Pro", 1728, 1117, 14),
    _apple("mbp_16_m5_max", "M5 Max", 1728, 1117, 16),
    _apple("imac_24_m1_2021", "M1", 2240, 1260, 8),
    _apple("imac_24_m3_2023", "M3", 2240, 1260, 8),
    _apple("imac_24_m4_2024", "M4", 2240, 1260, 10),
    _apple("mac_mini_m1_2020", "M1", 2560, 1440, 8),
    _apple("mac_mini_m2_2023", "M2", 2560, 1440, 8),
    _apple("mac_mini_m2_pro_2023", "M2 Pro", 3840, 2160, 12),
    _apple("mac_mini_m4_2024", "M4", 2560, 1440, 10),
    _apple("mac_mini_m4_pro_2024", "M4 Pro", 3840, 2160, 14),
    _apple("mac_studio_m1_max_2022", "M1 Max", 3840, 2160, 10),
    _apple("mac_studio_m1_ultra_2022", "M1 Ultra", 5120, 2880, 20),
    _apple("mac_studio_m2_max_2023", "M2 Max", 3840, 2160, 12),
    _apple("mac_studio_m2_ultra_2023", "M2 Ultra", 5120, 2880, 24),
    _apple("mac_studio_m4_max_2025", "M4 Max", 3840, 2160, 16),
    _apple("mac_studio_m3_ultra_2025", "M3 Ultra", 5120, 2880, 28),
    _apple("mac_pro_m2_ultra_2023", "M2 Ultra", 5120, 2880, 24),
)


def new_seed(old: Any = None) -> int:
    """A seed in the range new profiles get, never the one being replaced."""
    while True:
        seed = secrets.randbelow(90000) + 10000
        if seed != old:
            return seed


def target_platform(profile: dict[str, Any], host_os: str | None) -> str:
    platform = profile.get("platform")
    if platform in ("windows", "macos"):
        return platform
    return "windows" if host_os == "windows" else "macos"


def fresh_identity(profile: dict[str, Any], *, host_os: str | None, native: bool) -> dict[str, Any]:
    """The fields a reset writes: new seed and a different device of the same platform.

    ``native`` (system Chrome) shows the real machine, so like the editor the
    spoofed GPU/CPU/memory/UA are cleared and only the screen comes from the
    preset. Timezone and locale go back to "follow the exit IP".
    """
    platform = target_platform(profile, host_os)
    presets = [p for p in DEVICE_PRESETS if p["platform"] == platform]
    pool = [p for p in presets if p["id"] != profile.get("device_profile")] or presets
    device = secrets.choice(pool)
    fields: dict[str, Any] = {
        "fingerprint_seed": new_seed(profile.get("fingerprint_seed")),
        "device_profile": device["id"],
        "platform": platform,
        "screen_width": device["screen_width"],
        "screen_height": device["screen_height"],
        "gpu_vendor": None if native else device["gpu_vendor"],
        "gpu_renderer": None if native else device["gpu_renderer"],
        "hardware_concurrency": None if native else device["hardware_concurrency"],
        "device_memory": None if native else device["device_memory"],
        "user_agent": None,
        "color_scheme": None,
        "timezone": None,
        "locale": None,
        # Imported cookies are injected at every launch; a fresh browser has none.
        "cookies_json": None,
    }
    return fields


def owned_data_dir(profile: dict[str, Any], profiles_root: Path) -> Path | None:
    """The profile's user-data-dir, only when it is exactly profiles/<id>."""
    raw = profile.get("user_data_dir")
    if not raw:
        return None
    try:
        resolved = Path(raw).resolve()
        expected = (profiles_root / str(profile["id"])).resolve()
    except (OSError, ValueError):
        return None
    root = profiles_root.resolve()
    if resolved != expected or resolved == root or not resolved.is_relative_to(root):
        return None
    return resolved


def wipe_data_dir(data_dir: Path) -> int:
    """Remove every file of the profile's browser data; returns how many there were.

    The folder is first renamed aside, so even if deleting some file fails
    the next launch starts from an empty folder (a new profile has none yet).
    """
    if not data_dir.exists():
        return 0
    try:
        files = sum(1 for path in data_dir.rglob("*") if path.is_file())
    except OSError:
        files = 0
    aside = data_dir.with_name(f".reset-{data_dir.name}-{secrets.token_hex(4)}")
    data_dir.rename(aside)
    shutil.rmtree(aside, ignore_errors=True)
    if aside.exists():
        logger.warning("Reset left files behind in %s", aside)
    return files
