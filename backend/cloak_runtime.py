"""Authoritative CloakBrowser wrapper and binary version information."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CloakRuntimeInfo:
    wrapper_version: str | None
    configured_version: str
    effective_version: str
    platform: str | None
    binary_path: Path | None = None
    binary_version: str | None = None
    binary_verified: bool = False


def _configured_chromium_version() -> str:
    from cloakbrowser import config

    resolver = getattr(config, "get_chromium_version", None)
    if callable(resolver):
        return str(resolver())
    return str(config.CHROMIUM_VERSION)


def get_effective_chromium_version() -> str:
    """Return the selected update-marker version, not only the bundled default."""
    from cloakbrowser import config

    resolver = getattr(config, "get_effective_version", None)
    if callable(resolver):
        return str(resolver())
    return _configured_chromium_version()


def _cached_binary_version(binary_path: Path) -> str | None:
    for parent in (binary_path, *binary_path.parents):
        if parent.name.startswith("chromium-"):
            return parent.name.removeprefix("chromium-") or None
    return None


def inspect_cloak_runtime(*, ensure_binary: bool = False) -> CloakRuntimeInfo:
    import cloakbrowser
    from cloakbrowser import config

    configured = _configured_chromium_version()
    effective = get_effective_chromium_version()
    platform_resolver = getattr(config, "get_platform_tag", None)
    platform = str(platform_resolver()) if callable(platform_resolver) else None
    wrapper = getattr(cloakbrowser, "__version__", None)
    binary_path: Path | None = None
    binary_version: str | None = None
    binary_verified = False

    if ensure_binary:
        from cloakbrowser.download import ensure_binary as download_binary

        binary_path = Path(download_binary()).resolve()
        binary_version = _cached_binary_version(binary_path)
        file_ready = binary_path.is_file() and binary_path.stat().st_size > 0
        local_override = bool(os.environ.get("CLOAKBROWSER_BINARY_PATH"))
        version_matches = local_override or binary_version == effective
        binary_verified = file_ready and version_matches

    return CloakRuntimeInfo(
        wrapper_version=str(wrapper) if wrapper else None,
        configured_version=configured,
        effective_version=effective,
        platform=platform,
        binary_path=binary_path,
        binary_version=binary_version,
        binary_verified=binary_verified,
    )
