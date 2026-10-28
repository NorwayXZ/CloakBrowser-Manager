"""Extra CloakBrowser fingerprint switches set per profile."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from backend import browser_manager as module
from backend import database as db
from backend.browser_manager import BrowserManager
from backend.fingerprint_options import (
    build_fingerprint_option_args,
    unsupported_option_labels,
    webrtc_ip_arg,
)
from backend.runtime import RuntimeConfig


def test_default_options_add_no_switches():
    assert build_fingerprint_option_args({"platform": "windows"}) == []
    assert build_fingerprint_option_args({"platform": "windows", "fingerprint_options": {}}) == []


def test_all_options_map_to_documented_switches():
    args = build_fingerprint_option_args({
        "platform": "windows",
        "proxy": "http://proxy.example:8080",
        "fingerprint_options": {
            "brand": "Edge",
            "brand_version": "154.0.3485.54",
            "platform_version": "15.0.0",
            "noise": False,
            "speech_voices": False,
            "storage_quota_mb": 5000,
            "taskbar_height": 40,
            "windows_font_metrics": True,
            "allow_3p_cookies": True,
            "transparent_proxy": True,
            "portable_cookies": True,
        },
    })

    assert args == [
        "--fingerprint-brand=Edge",
        "--fingerprint-brand-version=154.0.3485.54",
        "--fingerprint-platform-version=15.0.0",
        "--fingerprint-noise=false",
        "--fingerprint-sapi-voices=false",
        "--fingerprint-storage-quota=5000",
        "--fingerprint-taskbar-height=40",
        "--fingerprint-windows-font-metrics",
        "--fingerprint-allow-3p-cookies",
        "--fingerprint-transparent-proxy",
        "--fingerprint-portable-cookies",
    ]


def test_windows_only_and_proxy_only_switches_are_skipped_elsewhere():
    args = build_fingerprint_option_args({
        "platform": "macos",
        "proxy": None,
        "fingerprint_options": {
            "speech_voices": False,
            "windows_font_metrics": True,
            "transparent_proxy": True,
        },
    })

    assert args == []


def test_invalid_stored_options_fall_back_to_defaults():
    assert build_fingerprint_option_args({"fingerprint_options": {"storage_quota_mb": -5}}) == []


def test_noise_on_overrides_the_macos_persona_default(tmp_path: Path):
    manager = BrowserManager(RuntimeConfig("macos", "native", "native-window", tmp_path))
    profile = {"fingerprint_seed": 1, "platform": "macos", "screen_width": 1512, "screen_height": 982}

    assert "--fingerprint-noise=false" in manager._build_fingerprint_args(profile)
    profile["fingerprint_options"] = {"noise": True, "brand": "Chrome"}
    args = manager._build_fingerprint_args(profile)
    assert "--fingerprint-noise=false" not in args
    assert args[-1] == "--fingerprint-brand=Chrome"


def test_webrtc_ip_prefers_fixed_ip_then_exit_ip():
    fixed = {"fingerprint_options": {"webrtc_ip": "203.0.113.9"}}
    assert webrtc_ip_arg(fixed, "198.51.100.1") == "--fingerprint-webrtc-ip=203.0.113.9"
    # With or without a proxy: the exit IP is what sites already see.
    assert webrtc_ip_arg({}, "198.51.100.1") == "--fingerprint-webrtc-ip=198.51.100.1"
    assert webrtc_ip_arg({}, None) is None


def test_options_newer_than_the_kernel_are_reported():
    profile = {
        "platform": "windows",
        "proxy": "http://proxy.example:8080",
        "fingerprint_options": {"transparent_proxy": True, "portable_cookies": True, "allow_3p_cookies": True},
    }

    labels = unsupported_option_labels(profile, "146.0.7680.177.5")
    assert labels == [
        "第三方 Cookie（需要内核 148+）",
        "透明代理（需要内核 151+）",
        "跨电脑 Cookie（需要内核 151+）",
    ]
    assert unsupported_option_labels(profile, "154.0.8037.57.1") == []
    assert unsupported_option_labels(profile, None) == []


# ── API round trip ───────────────────────────────────────────────────────────


def test_profile_api_stores_and_updates_options(app_client: TestClient):
    created = app_client.post("/api/profiles", json={
        "name": "Options",
        "fingerprint_options": {"brand": "Edge", "webrtc_ip": " 203.0.113.9 ", "portable_cookies": True},
    })
    assert created.status_code == 201
    options = created.json()["fingerprint_options"]
    assert options["brand"] == "Edge"
    assert options["webrtc_ip"] == "203.0.113.9"
    assert options["portable_cookies"] is True
    assert options["speech_voices"] is True

    profile_id = created.json()["id"]
    renamed = app_client.put(f"/api/profiles/{profile_id}", json={"name": "Renamed"})
    assert renamed.json()["fingerprint_options"]["brand"] == "Edge"

    updated = app_client.put(f"/api/profiles/{profile_id}", json={"fingerprint_options": {"storage_quota_mb": 5000}})
    assert updated.json()["fingerprint_options"]["brand"] is None
    assert updated.json()["fingerprint_options"]["storage_quota_mb"] == 5000


def test_profiles_without_options_report_defaults(app_client: TestClient):
    created = app_client.post("/api/profiles", json={"name": "Plain"})
    assert created.json()["fingerprint_options"]["brand"] is None
    assert created.json()["fingerprint_options"]["speech_voices"] is True


@pytest.mark.parametrize("options", [
    {"webrtc_ip": "not-an-ip"},
    {"brand": "Firefox"},
    {"brand_version": "154;rm"},
    {"taskbar_height": 999},
])
def test_profile_api_rejects_invalid_options(app_client: TestClient, options: dict):
    resp = app_client.post("/api/profiles", json={"name": "Bad", "fingerprint_options": options})
    assert resp.status_code == 422


def test_configuration_export_and_import_keep_options(tmp_db: Path):
    db.create_profile(name="Exported", fingerprint_options={"brand": "Opera"})
    payload = db.export_configuration()
    assert payload["profiles"][0]["fingerprint_options"] == {"brand": "Opera"}

    db.import_configuration(payload)
    brands = sorted(p["fingerprint_options"].get("brand") for p in db.list_profiles())
    assert brands == ["Opera", "Opera"]


# ── Launch ───────────────────────────────────────────────────────────────────


def _profile(tmp_path: Path) -> dict:
    return {
        "id": "p1",
        "name": "WebRTC",
        "browser_engine": "cloakbrowser",
        "platform": "windows",
        "fingerprint_seed": 12345,
        "user_data_dir": str(tmp_path / "profile"),
        "screen_width": 1920,
        "screen_height": 1080,
        "geoip": True,
        "proxy": "http://proxy.example:8080",
    }


@pytest.mark.asyncio
async def test_launch_spoofs_webrtc_with_proxy_exit_ip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    context = MagicMock()
    context.pages = []
    context.add_init_script = AsyncMock()
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(module, "launch_persistent_context_async", launch)
    monkeypatch.setattr(module, "fetch_proxy_geo", AsyncMock(return_value={
        "ip": "198.51.100.7", "timezone": "Europe/Berlin", "suggested_locale": "de-DE", "source": "test",
    }))
    manager = BrowserManager(RuntimeConfig("windows", "native", "native-window", tmp_path))
    manager._wait_for_cdp = AsyncMock()

    profile = _profile(tmp_path)
    profile["fingerprint_options"] = {"brand": "Edge"}
    await manager.launch(profile, launch_mode="debug")

    args = launch.await_args.kwargs["args"]
    assert "--fingerprint-webrtc-ip=198.51.100.7" in args
    assert "--fingerprint-brand=Edge" in args


@pytest.mark.asyncio
async def test_launch_keeps_a_webrtc_ip_given_in_launch_args(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    context = MagicMock()
    context.pages = []
    context.add_init_script = AsyncMock()
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(module, "launch_persistent_context_async", launch)
    monkeypatch.setattr(module, "fetch_proxy_geo", AsyncMock(return_value={"ip": "198.51.100.7"}))
    manager = BrowserManager(RuntimeConfig("windows", "native", "native-window", tmp_path))
    manager._wait_for_cdp = AsyncMock()

    profile = _profile(tmp_path)
    profile["launch_args"] = ["--fingerprint-webrtc-ip=192.0.2.1"]
    await manager.launch(profile, launch_mode="debug")

    webrtc = [a for a in launch.await_args.kwargs["args"] if a.startswith("--fingerprint-webrtc-ip")]
    assert webrtc == ["--fingerprint-webrtc-ip=192.0.2.1"]


def test_preflight_warns_when_kernel_is_too_old(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(module, "get_effective_chromium_version", lambda: "146.0.7680.177.5")
    manager = BrowserManager(RuntimeConfig("windows", "native", "native-window", tmp_path))
    profile = _profile(tmp_path)
    profile["fingerprint_options"] = {"portable_cookies": True}

    report = manager.preflight(profile)

    codes = [issue["code"] for issue in report["issues"]]
    assert "fingerprint_option_needs_newer_kernel" in codes


# ── WebRTC modes and geolocation ─────────────────────────────────────────────


def test_webrtc_has_no_disable_mode(app_client: TestClient):
    # The kernel ignores Chromium's WebRTC policy, so "block" would be a no-op
    # that also dropped the exit-IP replacement.
    resp = app_client.post("/api/profiles", json={"name": "Block", "fingerprint_options": {"webrtc": "block"}})
    assert resp.status_code == 422


def test_legacy_webrtc_ip_still_means_a_fixed_ip():
    profile = {"fingerprint_options": {"webrtc_ip": "203.0.113.9"}}
    assert webrtc_ip_arg(profile, "198.51.100.1") == "--fingerprint-webrtc-ip=203.0.113.9"


def test_custom_webrtc_without_ip_is_rejected(app_client: TestClient):
    resp = app_client.post("/api/profiles", json={"name": "No IP", "fingerprint_options": {"webrtc": "custom"}})
    assert resp.status_code == 422


GEO = {"ip": "198.51.100.7", "latitude": 25.05, "longitude": 121.53}


def test_geolocation_follows_exit_ip_only_when_cdp_can_override():
    from backend.fingerprint_options import geolocation_plan

    assert geolocation_plan({}, GEO, can_override=True) == (
        "override", {"latitude": 25.05, "longitude": 121.53, "accuracy": 1000},
    )
    assert geolocation_plan({}, GEO, can_override=False) == ("ask", None)
    assert geolocation_plan({}, {"ip": "198.51.100.7"}, can_override=True) == ("ask", None)
    assert geolocation_plan({"fingerprint_options": {"geolocation": "block"}}, GEO, can_override=True) == ("block", None)
    assert geolocation_plan({"fingerprint_options": {"geolocation": "real"}}, GEO, can_override=False) == ("real", None)


def test_geolocation_block_is_written_and_lifted_only_by_the_manager(tmp_path: Path):
    import json as _json

    from backend.browser_manager import GEOLOCATION_BLOCK_MARKER, _sync_geolocation_permission

    prefs_path = tmp_path / "Default" / "Preferences"
    _sync_geolocation_permission(tmp_path, block=False)
    assert not prefs_path.exists()

    _sync_geolocation_permission(tmp_path, block=True)
    prefs = _json.loads(prefs_path.read_text())
    assert prefs["profile"]["default_content_setting_values"]["geolocation"] == 2
    assert (tmp_path / GEOLOCATION_BLOCK_MARKER).exists()

    _sync_geolocation_permission(tmp_path, block=False)
    prefs = _json.loads(prefs_path.read_text())
    assert "geolocation" not in prefs["profile"]["default_content_setting_values"]
    assert not (tmp_path / GEOLOCATION_BLOCK_MARKER).exists()

    # A block the user set in Chrome (no marker) is left alone.
    prefs["profile"]["default_content_setting_values"]["geolocation"] = 2
    prefs_path.write_text(_json.dumps(prefs))
    _sync_geolocation_permission(tmp_path, block=False)
    assert _json.loads(prefs_path.read_text())["profile"]["default_content_setting_values"]["geolocation"] == 2


@pytest.mark.asyncio
async def test_debug_launch_reports_exit_ip_coordinates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    context = MagicMock()
    context.pages = []
    context.add_init_script = AsyncMock()
    context.set_geolocation = AsyncMock()
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(module, "launch_persistent_context_async", launch)
    monkeypatch.setattr(module, "fetch_proxy_geo", AsyncMock(return_value=GEO))
    manager = BrowserManager(RuntimeConfig("windows", "native", "native-window", tmp_path))
    manager._wait_for_cdp = AsyncMock()

    await manager.launch(_profile(tmp_path), launch_mode="debug")

    context.set_geolocation.assert_awaited_once_with({"latitude": 25.05, "longitude": 121.53, "accuracy": 1000})
    assert not (tmp_path / "profile" / module.GEOLOCATION_BLOCK_MARKER).exists()


@pytest.mark.asyncio
async def test_manual_launch_leaves_geolocation_at_ask(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # A real fresh Chrome reports "prompt"; a site-wide block reads "denied".
    import json as _json

    manager = BrowserManager(RuntimeConfig("windows", "native", "native-window", tmp_path))
    monkeypatch.setattr(module, "fetch_proxy_geo", AsyncMock(return_value=GEO))
    monkeypatch.setattr(module, "_launch_cloakbrowser_manual_process", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(manager, "_watch_process", AsyncMock())

    await manager.launch(_profile(tmp_path), launch_mode="manual")

    prefs_path = tmp_path / "profile" / "Default" / "Preferences"
    prefs = _json.loads(prefs_path.read_text()) if prefs_path.exists() else {}
    assert "geolocation" not in prefs.get("profile", {}).get("default_content_setting_values", {})


@pytest.mark.asyncio
async def test_manual_launch_still_blocks_when_asked_to(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import json as _json

    manager = BrowserManager(RuntimeConfig("windows", "native", "native-window", tmp_path))
    monkeypatch.setattr(module, "fetch_proxy_geo", AsyncMock(return_value=GEO))
    monkeypatch.setattr(module, "_launch_cloakbrowser_manual_process", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(manager, "_watch_process", AsyncMock())

    await manager.launch({**_profile(tmp_path), "fingerprint_options": {"geolocation": "block"}}, launch_mode="manual")

    prefs = _json.loads((tmp_path / "profile" / "Default" / "Preferences").read_text())
    assert prefs["profile"]["default_content_setting_values"]["geolocation"] == 2


def test_a_stale_stored_option_does_not_break_the_profile_list(app_client: TestClient):
    created = app_client.post("/api/profiles", json={"name": "Stale", "fingerprint_options": {"brand": "Edge"}})
    profile_id = created.json()["id"]
    # Simulate a value an older build stored that the model no longer accepts.
    db.update_profile(profile_id, fingerprint_options={"brand": "Edge", "webrtc": "block", "portable_cookies": True})

    listed = app_client.get("/api/profiles")

    assert listed.status_code == 200
    options = listed.json()[0]["fingerprint_options"]
    assert options["webrtc"] == "proxy"
    assert options["brand"] == "Edge"
    assert options["portable_cookies"] is True
