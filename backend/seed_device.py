"""The Apple device a macOS profile really presents, learned from its reports.

On a Mac the kernel derives one whole Apple Silicon identity (GPU, cores,
memory) from the profile's seed and ignores the device template picked in the
panel, so a profile labelled "Mac Pro M2 Ultra" showed sites an M4 Pro. The
Manager cannot compute that mapping, so it records what a profile's own
fingerprint report saw and shows that instead. The identity is fixed for a
kernel version and seed, which is the cache key.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

KEY = "seed_device:{kernel}:{seed}"
_APPLE_GPU_RE = re.compile(r"Apple (M\d+(?: (?:Pro|Max|Ultra))?)")


def applies(*, host_os: str, platform: str | None, engine: str) -> bool:
    """Whether the kernel derives this profile's device from its seed."""
    return host_os == "macos" and platform == "macos" and engine == "cloakbrowser"


def from_report(raw: dict[str, Any]) -> dict[str, Any] | None:
    """GPU model, cores and memory a fingerprint report saw, if it saw them."""
    main = raw.get("main") if isinstance(raw.get("main"), dict) else {}
    navigator = main.get("navigator") if isinstance(main.get("navigator"), dict) else {}
    graphics = main.get("graphics") if isinstance(main.get("graphics"), dict) else {}
    webgl = graphics.get("webgl") if isinstance(graphics.get("webgl"), dict) else {}
    renderer = str(webgl.get("renderer") or "")
    match = _APPLE_GPU_RE.search(renderer)
    cores = navigator.get("hardwareConcurrency")
    memory = navigator.get("deviceMemory")
    if not match and not isinstance(cores, int):
        return None
    return {
        "model": f"Apple {match.group(1)}" if match else None,
        "cores": cores if isinstance(cores, int) else None,
        "memory_gb": memory if isinstance(memory, (int, float)) else None,
    }


def save(set_setting: Callable[[str, str], None], kernel: str | None, seed: Any, device: dict[str, Any]) -> None:
    if kernel and seed is not None:
        set_setting(KEY.format(kernel=kernel, seed=seed), json.dumps(device))


def load(get_setting: Callable[[str], str | None], kernel: str | None, seed: Any) -> dict[str, Any] | None:
    if not kernel or seed is None:
        return None
    try:
        data = json.loads(get_setting(KEY.format(kernel=kernel, seed=seed)) or "null")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def describe(device: dict[str, Any] | None) -> str | None:
    """"Apple M4 Pro · 14 核 · 32 GB" for display."""
    if not device:
        return None
    parts = [device.get("model") or "Apple 芯片"]
    if device.get("cores"):
        parts.append(f"{device['cores']} 核")
    if device.get("memory_gb"):
        memory = device["memory_gb"]
        parts.append(f"{int(memory) if float(memory).is_integer() else memory} GB")
    return " · ".join(parts)
