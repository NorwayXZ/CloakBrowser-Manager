"""Window bounds, location permission, Chrome version and the seed device."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import browser_manager as module
from backend import chrome_versions, seed_device
from backend.browser_manager import BrowserManager
from backend.runtime import RuntimeConfig

MAC = RuntimeConfig("macos", "native", "native-window", Path("/tmp/unused"))


# ── Window inside the real visible area ──────────────────────────────────────


def test_screen_following_the_display_takes_the_real_dock_and_menu_bar(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(module, "primary_screen_size", lambda: (2560, 1440))
    monkeypatch.setattr(module, "primary_visible_frame", lambda: (0, 30, 2560, 1309))
    manager = BrowserManager(RuntimeConfig("macos", "native", "native-window", tmp_path))

    followed = manager.follow_real_screen({"browser_engine": "cloakbrowser", "screen_width": 1512, "screen_height": 982})

    assert (followed["screen_width"], followed["screen_height"]) == (2560, 1440)
    assert followed[module.VISIBLE_FRAME_KEY] == (0, 30, 2560, 1309)
    assert followed["fingerprint_options"]["taskbar_height"] == 131


def test_a_chosen_taskbar_height_is_kept(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(module, "primary_screen_size", lambda: (2560, 1440))
    monkeypatch.setattr(module, "primary_visible_frame", lambda: (0, 30, 2560, 1309))
    manager = BrowserManager(RuntimeConfig("macos", "native", "native-window", tmp_path))

    followed = manager.follow_real_screen({
        "browser_engine": "cloakbrowser", "fingerprint_options": {"taskbar_height": 60},
    })

    assert followed["fingerprint_options"] == {"taskbar_height": 60}


@pytest.mark.asyncio
async def test_manual_launch_puts_the_window_in_the_visible_area(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(module, "primary_screen_size", lambda: (2560, 1440))
    monkeypatch.setattr(module, "primary_visible_frame", lambda: (0, 30, 2560, 1309))
    manager = BrowserManager(RuntimeConfig("macos", "native", "native-window", tmp_path))
    launched = MagicMock(return_value=MagicMock(pid=1, poll=MagicMock(return_value=None)))
    monkeypatch.setattr(module, "_launch_cloakbrowser_manual_process", launched)
    monkeypatch.setattr(manager, "_watch_process", AsyncMock())
    monkeypatch.setattr(manager, "_watch_macos_windows", AsyncMock())
    profile = {
        "id": "p1", "name": "w", "browser_engine": "cloakbrowser", "platform": "macos",
        "fingerprint_seed": 1, "user_data_dir": str(tmp_path / "p1"), "screen_width": 1512, "screen_height": 982,
    }

    await manager.launch(profile)

    options = launched.call_args.kwargs
    assert options["viewport"] == {"width": 2560, "height": 1309, "x": 0, "y": 30}
    assert "--fingerprint-taskbar-height=131" in options["args"]
    placement = json.loads((tmp_path / "p1" / "Default" / "Preferences").read_text())["browser"]["window_placement"]
    assert (placement["left"], placement["top"], placement["right"], placement["bottom"]) == (0, 30, 2560, 1339)


# ── Chrome version ────────────────────────────────────────────────────────────

STABLE = ["156.0.8078.48", "155.0.8059.86", "155.0.8059.85", "155.0.8060.3", "154.0.8037.90"]


def test_aligned_patch_stays_on_the_kernel_major_and_build():
    assert chrome_versions.aligned_patch("155.0.8059.39.1", STABLE) == "155.0.8059.86"
    assert chrome_versions.aligned_patch("155.0.8059.90", STABLE) is None  # already newer
    assert chrome_versions.aligned_patch("157.0.8100.1", STABLE) is None   # no stable on that major
    assert chrome_versions.aligned_patch("0.0.0-test", STABLE) is None


@pytest.mark.asyncio
async def test_stable_versions_are_cached_and_survive_an_outage():
    store: dict[str, str] = {}
    calls = []

    async def fetch(platform_key):
        calls.append(platform_key)
        return STABLE

    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    first = await chrome_versions.stable_versions("macos", store.get, store.__setitem__, fetch=fetch, now=now)
    again = await chrome_versions.stable_versions("macos", store.get, store.__setitem__, fetch=fetch, now=now)

    async def down(_key):
        raise OSError("offline")

    later = await chrome_versions.stable_versions(
        "macos", store.get, store.__setitem__, fetch=down, now=now + timedelta(days=2),
    )

    assert first == again == later == STABLE
    assert calls == ["mac"]


@pytest.mark.asyncio
async def test_launch_reports_the_current_stable_patch(monkeypatch, tmp_path: Path):
    manager = BrowserManager(RuntimeConfig("windows", "native", "native-window", tmp_path))
    monkeypatch.setattr(module, "get_effective_chromium_version", lambda: "155.0.8059.39.1")
    monkeypatch.setattr(chrome_versions, "stable_versions", AsyncMock(return_value=STABLE))

    assert await manager._brand_version_args({"platform": "windows"}, []) == [
        "--fingerprint-brand=Chrome", "--fingerprint-brand-version=155.0.8059.86",
    ]
    # A version or another brand chosen by the user wins.
    assert await manager._brand_version_args({"fingerprint_options": {"brand": "Edge"}}, []) == []
    assert await manager._brand_version_args({"fingerprint_options": {"brand_version": "155.0.8059.50"}}, []) == []


# ── Location permission ───────────────────────────────────────────────────────


def test_manual_ip_geolocation_is_explained_before_launch(tmp_path: Path):
    manager = BrowserManager(RuntimeConfig("macos", "native", "native-window", tmp_path))
    base = {"platform": "macos", "browser_engine": "cloakbrowser", "screen_width": 1512, "screen_height": 982}

    codes = {issue["code"] for issue in manager.preflight(base, "manual")["issues"]}
    blocked = {issue["code"] for issue in manager.preflight(
        {**base, "fingerprint_options": {"geolocation": "block"}}, "manual",
    )["issues"]}

    assert "geolocation_asks" in codes
    assert "geolocation_asks" not in blocked


# ── Seed device ────────────────────────────────────────────────────────────────


def _report(renderer: str, cores: int, memory: int) -> dict:
    return {"main": {
        "navigator": {"hardwareConcurrency": cores, "deviceMemory": memory},
        "graphics": {"webgl": {"renderer": renderer}},
    }}


def test_seed_device_reads_the_apple_gpu_cores_and_memory():
    device = seed_device.from_report(_report("ANGLE (Apple, ANGLE Metal Renderer: Apple M4 Pro, Unspecified Version)", 14, 32))

    assert device == {"model": "Apple M4 Pro", "cores": 14, "memory_gb": 32}
    assert seed_device.describe(device) == "Apple M4 Pro · 14 核 · 32 GB"
    assert seed_device.from_report({}) is None


def test_seed_device_round_trips_per_kernel_and_seed():
    store: dict[str, str] = {}
    seed_device.save(store.__setitem__, "155.0.8059.39.1", 97261, {"model": "Apple M4", "cores": 10, "memory_gb": 16})

    assert seed_device.load(store.get, "155.0.8059.39.1", 97261)["model"] == "Apple M4"
    assert seed_device.load(store.get, "156.0.8078.1", 97261) is None


def test_profile_response_shows_the_seed_device_on_a_mac(app_client, monkeypatch):
    from backend import database as db
    from backend import main

    monkeypatch.setattr(main.browser_mgr, "runtime", RuntimeConfig("macos", "native", "native-window", db.DATA_DIR))
    monkeypatch.setattr(main, "get_effective_chromium_version", lambda: "155.0.8059.39.1")
    created = app_client.post("/api/profiles", json={
        "name": "Mac", "platform": "macos", "browser_engine": "cloakbrowser", "fingerprint_seed": 4242,
    }).json()

    pending = app_client.get(f"/api/profiles/{created['id']}").json()["seed_device"]
    seed_device.save(db.set_setting, "155.0.8059.39.1", 4242, {"model": "Apple M4 Pro", "cores": 14, "memory_gb": 32})
    seen = app_client.get(f"/api/profiles/{created['id']}").json()["seed_device"]

    assert pending == {"applies": True, "model": None, "cores": None, "memory_gb": None, "label": None}
    assert seen["label"] == "Apple M4 Pro · 14 核 · 32 GB"
