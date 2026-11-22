"""iPhone (iOS) persona: presets, kernel switches, launch rules, reset and the self-check."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from backend import database as db
from backend import ios_persona, main, profile_reset
from backend.browser_manager import BrowserManager
from backend.fingerprint_report import analyze_fingerprint
from backend.runtime import RuntimeConfig

ROOT = Path(__file__).resolve().parents[2]
EDITOR_PRESETS = ROOT / "frontend" / "src" / "next" / "features" / "editor" / "deviceProfiles.ts"


def _manager(tmp_path: Path, host: str = "macos") -> BrowserManager:
    return BrowserManager(RuntimeConfig(host, "native", "native-window", tmp_path))


def _iphone(**extra) -> dict:
    return {"id": "p1", "platform": "ios", "device_profile": "iphone_15", "fingerprint_seed": 4242,
            "browser_engine": "cloakbrowser", **extra}


def test_every_iphone_is_a_real_screen_size():
    for device_id, (name, width, height, ratio) in ios_persona.IPHONES.items():
        assert device_id.startswith("iphone_") and name.startswith("iPhone")
        assert 375 <= width <= 440 and 667 <= height <= 956
        assert ratio in (2, 3)
    assert ios_persona.DEFAULT_IPHONE in ios_persona.IPHONES


def test_user_agent_is_a_real_safari_string():
    ua = ios_persona.USER_AGENT
    assert "iPhone; CPU iPhone OS" in ua and "Mobile/15E148 Safari/604.1" in ua
    assert "Chrome" not in ua and "Macintosh" not in ua


def test_defaults_fill_a_blank_iphone_and_never_follow_the_desktop():
    filled = ios_persona.with_defaults({"platform": "ios", "device_profile": "iphone_16_pro",
                                        "screen_width": 2560, "screen_height": 1440})
    assert (filled["screen_width"], filled["screen_height"]) == (402, 874)
    assert filled["user_agent"] == ios_persona.USER_AGENT
    assert filled["device_memory"] is None  # Safari has no deviceMemory
    assert (filled["gpu_vendor"], filled["gpu_renderer"]) == ("Apple Inc.", "Apple GPU")
    # what the user wrote is kept
    custom = ios_persona.with_defaults({"platform": "ios", "user_agent": "X", "gpu_renderer": "Y",
                                        "screen_width": 390, "screen_height": 844})
    assert custom["user_agent"] == "X" and custom["gpu_renderer"] == "Y"
    assert (custom["screen_width"], custom["screen_height"]) == (390, 844)


def test_pixel_ratio_follows_the_model():
    assert ios_persona.pixel_ratio({"device_profile": "iphone_se3"}) == 2
    assert ios_persona.pixel_ratio({"device_profile": "iphone_15"}) == 3
    assert ios_persona.pixel_ratio({"screen_width": 375, "screen_height": 667}) == 2
    assert ios_persona.pixel_ratio({}) == 3


def test_kernel_gets_the_host_platform_and_the_phone_hardware(tmp_path: Path):
    profile = ios_persona.with_defaults(_iphone())
    args = _manager(tmp_path)._build_fingerprint_args(profile)
    assert "--fingerprint-platform=macos" in args  # the kernel has no iOS; the look is layered on top
    assert "--fingerprint-gpu-vendor=Apple Inc." in args and "--fingerprint-gpu-renderer=Apple GPU" in args
    assert "--fingerprint-max-touch-points=5" in args
    assert "--fingerprint-taskbar-height=0" in args
    assert "--fingerprint-screen-width=393" in args and "--fingerprint-screen-height=852" in args
    assert "--fingerprint=4242" in args
    assert not any(a.startswith("--fingerprint-device-memory") for a in args)
    assert not any("ios" in a for a in args)


def test_an_iphone_profile_always_uses_the_kernel_and_keeps_its_own_screen(tmp_path: Path):
    manager = _manager(tmp_path)
    assert manager._browser_engine(_iphone(browser_engine="system_chrome")) == "cloakbrowser"
    profile = _iphone(screen_width=393, screen_height=852)
    assert manager.follow_real_screen(profile) is profile  # desktop-sized "real" screen never applies


def test_preflight_needs_a_mac_and_warns_that_it_is_a_look(tmp_path: Path):
    mac = _manager(tmp_path).preflight(ios_persona.with_defaults(_iphone()))
    codes = {issue["code"]: issue["severity"] for issue in mac["issues"]}
    assert codes.get("ios_look_only") == "warning"
    assert "ios_needs_macos_host" not in codes and "host_platform_mismatch" not in codes
    assert mac["can_launch"] is True

    win = _manager(tmp_path, "windows").preflight(ios_persona.with_defaults(_iphone()))
    assert win["can_launch"] is False
    assert any(issue["code"] == "ios_needs_macos_host" for issue in win["issues"])


def test_preflight_rejects_a_desktop_user_agent_on_an_iphone(tmp_path: Path):
    result = _manager(tmp_path).preflight(
        ios_persona.with_defaults(_iphone(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/156.0.0.0 Safari/537.36"))
    )
    assert any(issue["code"] == "ua_platform_mismatch" for issue in result["issues"])
    assert result["can_launch"] is False


def test_reset_keeps_an_iphone_an_iphone():
    profile = _iphone()
    seen = set()
    for _ in range(40):
        fields = profile_reset.fresh_identity(profile, host_os="macos", native=False)
        assert fields["platform"] == "ios"
        assert fields["device_profile"] in ios_persona.IPHONES and fields["device_profile"] != "iphone_15"
        _, width, height, _ = ios_persona.IPHONES[fields["device_profile"]]
        assert (fields["screen_width"], fields["screen_height"]) == (width, height)
        assert fields["user_agent"] is None and fields["fingerprint_seed"] != 4242
        seen.add(fields["device_profile"])
    assert len(seen) > 1


def test_the_api_accepts_the_ios_platform(app_client: TestClient):
    created = app_client.post("/api/profiles", json={"name": "iPhone", "platform": "ios", "device_profile": "iphone_15"})
    assert created.status_code in (200, 201), created.text
    assert created.json()["platform"] == "ios"
    updated = app_client.put(f"/api/profiles/{created.json()['id']}", json={"platform": "ios", "device_profile": "iphone_16"})
    assert updated.status_code == 200 and updated.json()["device_profile"] == "iphone_16"


def test_init_script_hides_what_only_chrome_has():
    script = ios_persona.init_script({"device_profile": "iphone_se3"})
    for needle in ("userAgentData", "deviceMemory", "window.chrome", "'iPhone'", "Apple Computer, Inc."):
        assert needle in script
    assert "get devicePixelRatio" not in script and ", 2)" in script  # the SE's ratio, not the default 3
    assert "__RATIO__" not in script and "__WORKER_PATCH__" not in script
    assert "WorkerNavigator" in script  # blob workers start with the worker patch


def _raw(*, user_agent: str, platform: str, ua_data=None, device_memory=None, touch=5) -> dict:
    return {"main": {"navigator": {"webdriver": False, "userAgent": user_agent, "platform": platform,
                                   "userAgentData": ua_data, "deviceMemory": device_memory, "maxTouchPoints": touch},
                     "page": {"secureContext": True}, "screen": {}, "graphics": {}, "nativeStrings": {}}}


def _analyze(raw: dict) -> dict:
    return analyze_fingerprint(raw, expected_locale=None, expected_timezone=None, expected_platform="ios",
                               expected_screen_width=None, expected_screen_height=None,
                               expected_hardware_concurrency=None)


def _signals(result: dict) -> set[str]:
    return {issue["signal"] for issue in result["issues"]}


def test_self_check_passes_a_clean_iphone():
    result = _analyze(_raw(user_agent=ios_persona.USER_AGENT, platform="iPhone"))
    assert not {"platform", "ios_chrome_only_api", "navigator.userAgentData"} & _signals(result)


def test_self_check_flags_a_desktop_platform_and_chrome_only_apis():
    result = _analyze(_raw(user_agent=ios_persona.USER_AGENT, platform="MacIntel",
                           ua_data={"platform": "macOS"}, device_memory=16, touch=0))
    signals = _signals(result)
    assert {"platform", "ios_chrome_only_api", "navigator.maxTouchPoints"} <= signals


def test_frontend_presets_match_the_backend_table():
    text = EDITOR_PRESETS.read_text(encoding="utf-8")
    for device_id, (_, width, height, _ratio) in ios_persona.IPHONES.items():
        match = re.search(rf'iphoneProfile\(\s*"{device_id}",\s*"[^"]*",\s*(\d+),\s*(\d+)', text)
        assert match, f"{device_id} is missing from the editor presets"
        assert (int(match.group(1)), int(match.group(2))) == (width, height)
    assert ios_persona.USER_AGENT in text  # the preset writes the same Safari string the backend defaults to
