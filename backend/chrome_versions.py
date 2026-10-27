"""The full Chrome version a profile reports, kept at the current stable patch.

The kernel reports its own build (e.g. 155.0.8059.40) in Client Hints'
fullVersionList, while real Chrome on that major has moved on to later
patches (e.g. 155.0.8059.86) within days. Only the patch is aligned: a
newer major would claim web features this engine does not have.

Stable versions come from Google's public version history API, cached in the
settings table so a launch never waits on it for long.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

VERSIONS_URL = "https://versionhistory.googleapis.com/v1/chrome/platforms/{platform}/channels/stable/versions"
PLATFORM_KEYS = {"macos": "mac", "windows": "win64"}
CACHE_KEY = "chrome_stable_versions:{platform}"
CACHE_HOURS = 12
FETCH_SECONDS = 4.0

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)")


def _parts(version: str | None) -> tuple[int, int, int, int] | None:
    match = _VERSION_RE.match(version or "")
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def aligned_patch(kernel_version: str | None, stable_versions: list[str]) -> str | None:
    """The newest stable version on the kernel's major and build, if newer than the kernel's."""
    kernel = _parts(kernel_version)
    if kernel is None:
        return None
    candidates = [
        parts for parts in (_parts(v) for v in stable_versions)
        if parts and parts[0] == kernel[0] and parts[2] == kernel[2] and parts[3] > kernel[3]
    ]
    if not candidates:
        return None
    return ".".join(str(part) for part in max(candidates))


async def _fetch(platform_key: str) -> list[str]:
    async with httpx.AsyncClient(timeout=FETCH_SECONDS) as client:
        response = await client.get(VERSIONS_URL.format(platform=platform_key), params={"pageSize": 200})
        response.raise_for_status()
        return [str(item["version"]) for item in response.json().get("versions", []) if item.get("version")]


async def stable_versions(
    platform: str,
    get_setting: Callable[[str], str | None],
    set_setting: Callable[[str, str], None],
    *,
    fetch: Callable[[str], Any] | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Stable versions for a persona platform; cached, never raises."""
    fetch = fetch or _fetch
    platform_key = PLATFORM_KEYS.get(platform)
    if platform_key is None:
        return []
    now = now or datetime.now(timezone.utc)
    key = CACHE_KEY.format(platform=platform_key)
    cached: dict[str, Any] = {}
    try:
        cached = json.loads(get_setting(key) or "{}")
        fetched_at = datetime.fromisoformat(cached["at"])
        if now - fetched_at < timedelta(hours=CACHE_HOURS):
            return list(cached.get("versions") or [])
    except (ValueError, KeyError, TypeError):
        pass
    try:
        versions = await fetch(platform_key)
    except Exception as exc:  # network down: the last list beats none
        logger.info("Could not fetch Chrome stable versions: %s", exc)
        return list(cached.get("versions") or [])
    set_setting(key, json.dumps({"at": now.isoformat(), "versions": versions}))
    return versions
