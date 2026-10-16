"""Translate a profile's extra fingerprint options into CloakBrowser switches.

The core persona (seed, platform, screen, GPU, CPU, memory) is built by the
browser manager; this module covers the remaining binary switches documented
by CloakBrowser so they can be set per profile from the panel.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import ValidationError

from .models import FingerprintOptions

logger = logging.getLogger(__name__)

NOISE_OFF_ARG = "--fingerprint-noise=false"

# Oldest Chromium major that understands each switch. Older kernels ignore
# unknown switches, so these only drive preflight warnings.
OPTION_MIN_MAJOR: dict[str, tuple[int, str]] = {
    "windows_font_metrics": (148, "Windows 字体度量"),
    "allow_3p_cookies": (148, "第三方 Cookie"),
    "speech_voices": (150, "Windows 语音列表"),
    "transparent_proxy": (151, "透明代理"),
    "portable_cookies": (151, "跨电脑 Cookie"),
}


def parse_fingerprint_options(profile: dict[str, Any]) -> FingerprintOptions:
    raw = profile.get("fingerprint_options")
    if isinstance(raw, FingerprintOptions):
        return raw
    try:
        return FingerprintOptions.model_validate(raw or {})
    except ValidationError as exc:
        logger.warning("Ignoring invalid fingerprint options for %s: %s", profile.get("id"), exc)
        return FingerprintOptions()


def build_fingerprint_option_args(profile: dict[str, Any]) -> list[str]:
    """Switches for the options that differ from the binary's defaults."""
    options = parse_fingerprint_options(profile)
    is_windows = profile.get("platform") == "windows"
    args: list[str] = []

    if options.brand:
        args.append(f"--fingerprint-brand={options.brand}")
    if options.brand_version:
        args.append(f"--fingerprint-brand-version={options.brand_version}")
    if options.platform_version:
        args.append(f"--fingerprint-platform-version={options.platform_version}")
    if options.noise is False:
        args.append(NOISE_OFF_ARG)
    if is_windows and not options.speech_voices:
        args.append("--fingerprint-sapi-voices=false")
    if options.storage_quota_mb is not None:
        args.append(f"--fingerprint-storage-quota={options.storage_quota_mb}")
    if options.taskbar_height is not None:
        args.append(f"--fingerprint-taskbar-height={options.taskbar_height}")
    if is_windows and options.windows_font_metrics:
        args.append("--fingerprint-windows-font-metrics")
    if options.allow_3p_cookies:
        args.append("--fingerprint-allow-3p-cookies")
    if options.transparent_proxy and profile.get("proxy"):
        args.append("--fingerprint-transparent-proxy")
    if options.portable_cookies:
        args.append("--fingerprint-portable-cookies")
    return args


def apply_noise_preference(args: list[str], profile: dict[str, Any]) -> list[str]:
    """Honour an explicit "noise on" choice over a persona that turned it off."""
    if parse_fingerprint_options(profile).noise is True:
        return [arg for arg in args if arg != NOISE_OFF_ARG]
    return args


def webrtc_ip_arg(profile: dict[str, Any], exit_ip: str | None, *, proxied: bool) -> str | None:
    """WebRTC ICE candidate IP: the fixed one, else the proxy exit IP."""
    options = parse_fingerprint_options(profile)
    ip = options.webrtc_ip or (exit_ip if proxied else None)
    return f"--fingerprint-webrtc-ip={ip}" if ip else None


def _major(version: str | None) -> int | None:
    match = re.match(r"(\d+)", version or "")
    return int(match.group(1)) if match else None


def unsupported_option_labels(profile: dict[str, Any], kernel_version: str | None) -> list[str]:
    """Labels of enabled options the given kernel is too old to apply."""
    major = _major(kernel_version)
    if major is None:
        return []
    options = parse_fingerprint_options(profile)
    is_windows = profile.get("platform") == "windows"
    enabled = {
        "windows_font_metrics": is_windows and options.windows_font_metrics,
        "allow_3p_cookies": options.allow_3p_cookies,
        "speech_voices": is_windows and not options.speech_voices,
        "transparent_proxy": options.transparent_proxy and bool(profile.get("proxy")),
        "portable_cookies": options.portable_cookies,
    }
    return [
        f"{label}（需要内核 {minimum}+）"
        for key, (minimum, label) in OPTION_MIN_MAJOR.items()
        if enabled[key] and major < minimum
    ]
