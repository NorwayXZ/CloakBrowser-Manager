"""Tests for browser_manager pure functions — proxy parsing, fingerprint args, profile defaults."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.browser_manager import (
    _accept_language_value,
    _build_locale_timezone_env,
    _build_fingerprint_init_script,
    _build_worker_fingerprint_patch,
    _init_profile_defaults,
    _launch_system_chrome_persistent_context_async,
    _normalize_proxy,
    _playwright_proxy,
    _sync_profile_locale,
    _sync_session_restore,
    _validate_proxy,
    BrowserManager,
    RunningProfile,
)
from backend.runtime import RuntimeConfig

DOCKER_RUNTIME = RuntimeConfig(
    host_os="linux",
    runtime_mode="docker",
    viewer_mode="vnc",
    data_dir=Path("/data"),
)
NATIVE_RUNTIME = RuntimeConfig(
    host_os="windows",
    runtime_mode="native",
    viewer_mode="native-window",
    data_dir=Path("C:/manager-data"),
)


# ── _normalize_proxy ─────────────────────────────────────────────────────────


def test_normalize_already_http():
    assert _normalize_proxy("http://user:pass@host:8080") == "http://user:pass@host:8080"


def test_normalize_already_https():
    assert _normalize_proxy("https://host:443") == "https://host:443"


def test_normalize_already_socks5():
    assert _normalize_proxy("socks5://host:1080") == "socks5://host:1080"


def test_normalize_preserves_xray_share_link():
    link = "vless://11111111-1111-1111-1111-111111111111@example.com:443"
    assert _normalize_proxy(link) == link


def test_normalize_host_port_user_pass():
    assert _normalize_proxy("proxy.com:8080:myuser:mypass") == "http://myuser:mypass@proxy.com:8080"


def test_normalize_host_port_only():
    assert _normalize_proxy("proxy.com:8080") == "http://proxy.com:8080"


def test_normalize_three_parts():
    # 3 parts doesn't match any pattern — returned as-is
    assert _normalize_proxy("a:b:c") == "a:b:c"


def test_normalize_five_parts():
    # 5 parts doesn't match — returned as-is
    assert _normalize_proxy("a:b:c:d:e") == "a:b:c:d:e"


def test_normalize_empty_parts():
    # host:port:user:pass with empty parts
    result = _normalize_proxy(":8080:user:pass")
    assert result == "http://user:pass@:8080"


# ── _validate_proxy ──────────────────────────────────────────────────────────


def test_validate_valid_http():
    _validate_proxy("http://proxy.com:8080")  # should not raise


def test_validate_valid_socks5():
    _validate_proxy("socks5://proxy.com:1080")  # should not raise


def test_validate_valid_with_auth():
    _validate_proxy("http://user:pass@proxy.com:8080")  # should not raise


def test_validate_vless_share_link():
    _validate_proxy("vless://11111111-1111-1111-1111-111111111111@example.com:443")


def test_validate_bad_scheme():
    with pytest.raises(ValueError, match="Invalid proxy scheme 'ftp'"):
        _validate_proxy("ftp://host:80")


def test_validate_no_hostname():
    with pytest.raises(ValueError, match="missing hostname"):
        _validate_proxy("http://:8080")


def test_validate_no_port():
    with pytest.raises(ValueError, match="missing port"):
        _validate_proxy("http://host")


def test_playwright_proxy_bypasses_manager_loopback():
    settings = _playwright_proxy("http://proxy.example:8080")

    assert settings == {
        "server": "http://proxy.example:8080",
        "bypass": "127.0.0.1,localhost,[::1]",
    }


# ── _build_fingerprint_args ──────────────────────────────────────────────────

# Use the BrowserManager instance to call the method
_mgr = BrowserManager(DOCKER_RUNTIME)


def test_build_args_always_includes_base():
    args = _mgr._build_fingerprint_args({})
    assert "--disable-infobars" in args
    assert "--test-type" in args
    assert "--use-angle=swiftshader" in args


def test_build_args_seed():
    args = _mgr._build_fingerprint_args({"fingerprint_seed": 42})
    assert "--fingerprint=42" in args


def test_build_args_no_seed():
    args = _mgr._build_fingerprint_args({"fingerprint_seed": None})
    assert not any(a.startswith("--fingerprint=") for a in args)


def test_build_args_platform():
    args = _mgr._build_fingerprint_args({"platform": "macos"})
    assert "--fingerprint-platform=macos" in args


def test_build_args_gpu():
    args = _mgr._build_fingerprint_args({
        "gpu_vendor": "NVIDIA Corporation",
        "gpu_renderer": "NVIDIA GeForce RTX 3070",
    })
    assert "--fingerprint-gpu-vendor=NVIDIA Corporation" in args
    assert "--fingerprint-gpu-renderer=NVIDIA GeForce RTX 3070" in args


def test_build_args_hardware_concurrency():
    args = _mgr._build_fingerprint_args({"hardware_concurrency": 8})
    assert "--fingerprint-hardware-concurrency=8" in args


def test_build_args_screen():
    args = _mgr._build_fingerprint_args({"screen_width": 2560, "screen_height": 1440})
    assert "--fingerprint-screen-width=2560" in args
    assert "--fingerprint-screen-height=1440" in args


def test_build_args_empty_profile():
    args = _mgr._build_fingerprint_args({})
    # Two shared flags plus Docker's software rendering flag.
    assert len(args) == 3


def test_native_build_args_do_not_force_software_gl():
    args = BrowserManager(NATIVE_RUNTIME)._build_fingerprint_args({})
    assert "--use-angle=swiftshader" not in args


def test_docker_system_chrome_profile_uses_cloakbrowser_runtime():
    manager = BrowserManager(DOCKER_RUNTIME)

    assert manager._browser_engine({"browser_engine": "system_chrome"}) == "cloakbrowser"


# ── launch_args appended to extra_args ────────────────────────────────────────


def test_launch_args_appended_to_fingerprint_args():
    """launch_args from profile should appear in the args list after fingerprint args."""
    profile = {
        "fingerprint_seed": 42,
        "platform": "windows",
        "launch_args": ["--load-extension=/tmp/ext", "--disable-features=Foo"],
    }
    args = _mgr._build_fingerprint_args(profile)
    args += profile.get("launch_args") or []
    assert "--load-extension=/tmp/ext" in args
    assert "--disable-features=Foo" in args
    # Fingerprint args still present
    assert "--fingerprint=42" in args


def test_launch_args_empty_no_effect():
    profile = {"launch_args": []}
    args = _mgr._build_fingerprint_args(profile)
    base_count = len(args)
    args += profile.get("launch_args") or []
    assert len(args) == base_count


def test_launch_args_none_no_effect():
    profile = {"launch_args": None}
    args = _mgr._build_fingerprint_args(profile)
    base_count = len(args)
    args += profile.get("launch_args") or []
    assert len(args) == base_count


# ── runtime-specific launch behavior ─────────────────────────────────────────


def _launch_profile(tmp_path: Path) -> dict:
    return {
        "id": "profile-1",
        "name": "Native",
        "user_data_dir": str(tmp_path / "profile-1"),
        "screen_width": 1920,
        "screen_height": 1080,
        "launch_args": [],
    }


@pytest.mark.asyncio
async def test_native_launch_skips_vnc_and_display(monkeypatch, tmp_path: Path):
    from backend import browser_manager as module

    context = MagicMock()
    context.pages = []
    context.add_init_script = AsyncMock()
    manager = BrowserManager(NATIVE_RUNTIME)
    manager.vnc.allocate = AsyncMock()
    manager.vnc.start_vnc = AsyncMock()
    manager._wait_for_cdp = AsyncMock()
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(module, "launch_persistent_context_async", launch)

    running = await manager.launch(_launch_profile(tmp_path))

    assert running.display is None
    assert running.ws_port is None
    manager.vnc.allocate.assert_not_awaited()
    manager.vnc.start_vnc.assert_not_awaited()
    options = launch.await_args.kwargs
    assert "env" not in options
    assert "viewport" not in options
    assert "--use-angle=swiftshader" not in options["args"]
    assert "--restore-last-session" in options["args"]
    assert "--remote-debugging-address=127.0.0.1" in options["args"]


@pytest.mark.asyncio
async def test_system_chrome_native_window_uses_resizable_viewport(monkeypatch, tmp_path: Path):
    import playwright.async_api

    context = MagicMock()
    context.close = AsyncMock()
    chromium = MagicMock()
    chromium.launch_persistent_context = AsyncMock(return_value=context)
    playwright_runtime = MagicMock(chromium=chromium)
    playwright_runtime.stop = AsyncMock()
    playwright_controller = MagicMock()
    playwright_controller.start = AsyncMock(return_value=playwright_runtime)
    monkeypatch.setattr(
        playwright.async_api,
        "async_playwright",
        MagicMock(return_value=playwright_controller),
    )

    await _launch_system_chrome_persistent_context_async(
        user_data_dir=tmp_path / "profile",
        headless=False,
    )

    options = chromium.launch_persistent_context.await_args.kwargs
    assert options["no_viewport"] is True
    assert "viewport" not in options
    assert options["chromium_sandbox"] is True


@pytest.mark.asyncio
async def test_native_system_chrome_keeps_restored_tabs(monkeypatch, tmp_path: Path):
    from backend import browser_manager as module

    blank_page = MagicMock(url="about:blank")
    blank_page.goto = AsyncMock()
    blank_page.bring_to_front = AsyncMock()
    restored_page = MagicMock(url="https://example.com/")
    context = MagicMock(pages=[blank_page, restored_page])
    context.add_init_script = AsyncMock()
    manager = BrowserManager(RuntimeConfig("macos", "native", "native-window", tmp_path))
    manager._wait_for_cdp = AsyncMock()
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(module, "_launch_system_chrome_persistent_context_async", launch)

    await manager.launch({
        **_launch_profile(tmp_path),
        "browser_engine": "system_chrome",
    })

    assert "--restore-last-session" in launch.await_args.kwargs["args"]
    blank_page.goto.assert_not_awaited()
    blank_page.bring_to_front.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_system_chrome_replaces_blank_start_page(monkeypatch, tmp_path: Path):
    from backend import browser_manager as module

    page = MagicMock(url="about:blank")
    page.goto = AsyncMock()
    page.bring_to_front = AsyncMock()
    context = MagicMock(pages=[page])
    context.add_init_script = AsyncMock()
    manager = BrowserManager(RuntimeConfig("macos", "native", "native-window", tmp_path))
    manager._wait_for_cdp = AsyncMock()
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(module, "_launch_system_chrome_persistent_context_async", launch)

    await manager.launch({
        **_launch_profile(tmp_path),
        "browser_engine": "system_chrome",
    })

    page.goto.assert_awaited_once_with(
        "http://127.0.0.1:8080/profile/profile-1/start",
        wait_until="domcontentloaded",
    )
    page.bring_to_front.assert_awaited_once()


@pytest.mark.asyncio
async def test_native_close_event_releases_session(monkeypatch, tmp_path: Path):
    from backend import browser_manager as module

    context = MagicMock(pages=[])
    context.add_init_script = AsyncMock()
    manager = BrowserManager(NATIVE_RUNTIME)
    manager._wait_for_cdp = AsyncMock()
    monkeypatch.setattr(
        module,
        "launch_persistent_context_async",
        AsyncMock(return_value=context),
    )
    running = await manager.launch(_launch_profile(tmp_path))
    close_callback = context.on.call_args.args[1]

    await close_callback(context)

    assert "profile-1" not in manager.running
    assert running.cdp_port not in manager._cdp_ports


@pytest.mark.asyncio
async def test_launch_rejects_user_debugging_flags(tmp_path: Path):
    manager = BrowserManager(NATIVE_RUNTIME)
    profile = _launch_profile(tmp_path)
    profile["launch_args"] = ["--remote-debugging-address=0.0.0.0"]

    with pytest.raises(ValueError, match="Manager owns remote debugging"):
        await manager.launch(profile)

    assert "profile-1" not in manager._launching
    assert manager._cdp_ports == set()


@pytest.mark.asyncio
async def test_docker_launch_keeps_vnc_display(monkeypatch, tmp_path: Path):
    from backend import browser_manager as module

    context = MagicMock()
    context.pages = []
    context.add_init_script = AsyncMock()
    manager = BrowserManager(DOCKER_RUNTIME)
    manager.vnc.allocate = AsyncMock(return_value=(100, 6100))
    manager.vnc.start_vnc = AsyncMock()
    manager._wait_for_cdp = AsyncMock()
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(module, "launch_persistent_context_async", launch)

    running = await manager.launch(_launch_profile(tmp_path))

    assert running.display == 100
    assert running.ws_port == 6100
    manager.vnc.start_vnc.assert_awaited_once()
    options = launch.await_args.kwargs
    assert options["env"]["DISPLAY"] == ":100"
    assert options["viewport"] == {"width": 1920, "height": 947}
    assert "--use-angle=swiftshader" in options["args"]


@pytest.mark.asyncio
async def test_launch_retries_failed_cdp_and_closes_first_context(
    monkeypatch,
    tmp_path: Path,
):
    from backend import browser_manager as module

    first_context = MagicMock(pages=[])
    first_context.close = AsyncMock()
    second_context = MagicMock(pages=[])
    second_context.add_init_script = AsyncMock()
    second_context.close = AsyncMock()
    manager = BrowserManager(NATIVE_RUNTIME)
    manager._wait_for_cdp = AsyncMock(side_effect=[TimeoutError("busy"), None])
    launch = AsyncMock(side_effect=[first_context, second_context])
    monkeypatch.setattr(module, "launch_persistent_context_async", launch)

    running = await manager.launch(_launch_profile(tmp_path))

    assert launch.await_count == 2
    first_context.close.assert_awaited_once()
    assert running.cdp_port in manager._cdp_ports


@pytest.mark.asyncio
async def test_stop_releases_native_cdp_port():
    manager = BrowserManager(NATIVE_RUNTIME)
    context = MagicMock()
    context.close = AsyncMock()
    port = manager._reserve_cdp_port()
    manager.running["profile-1"] = module_running = RunningProfile(
        "profile-1", context, port
    )

    await manager.stop("profile-1")

    context.close.assert_awaited_once()
    assert module_running.cdp_port not in manager._cdp_ports
    assert "profile-1" not in manager.running


# ── CDP reservation and verification ─────────────────────────────────────────


def test_reserve_cdp_port_tracks_unique_ports():
    manager = BrowserManager(NATIVE_RUNTIME)
    first = manager._reserve_cdp_port()
    second = manager._reserve_cdp_port()
    assert first != second
    assert manager._cdp_ports == {first, second}


def test_release_cdp_port_is_idempotent():
    manager = BrowserManager(NATIVE_RUNTIME)
    port = manager._reserve_cdp_port()
    manager._release_cdp_port(port)
    manager._release_cdp_port(port)
    assert port not in manager._cdp_ports


@pytest.mark.asyncio
async def test_wait_for_cdp_verifies_debugger_port(monkeypatch):
    manager = BrowserManager(NATIVE_RUNTIME)
    fetch = AsyncMock(return_value={
        "webSocketDebuggerUrl": "ws://127.0.0.1:53123/devtools/browser/test",
    })
    monkeypatch.setattr(manager, "_fetch_cdp_version", fetch)
    await manager._wait_for_cdp(53123, timeout=0.1)


@pytest.mark.asyncio
async def test_wait_for_cdp_rejects_wrong_debugger_port(monkeypatch):
    manager = BrowserManager(NATIVE_RUNTIME)
    fetch = AsyncMock(return_value={
        "webSocketDebuggerUrl": "ws://127.0.0.1:53124/devtools/browser/test",
    })
    monkeypatch.setattr(manager, "_fetch_cdp_version", fetch)
    with pytest.raises(TimeoutError, match="was not ready"):
        await manager._wait_for_cdp(53123, timeout=0.01)


# ── _init_profile_defaults ───────────────────────────────────────────────────


def test_init_creates_bookmarks(tmp_path: Path):
    _init_profile_defaults(tmp_path)
    bookmarks_path = tmp_path / "Default" / "Bookmarks"
    assert bookmarks_path.exists()
    data = json.loads(bookmarks_path.read_text())
    children = data["roots"]["bookmark_bar"]["children"]
    assert len(children) == 4  # 4 folders
    folder_names = {f["name"] for f in children}
    assert folder_names == {"Detection Tests", "Fingerprint", "Headers & TLS", "reCAPTCHA"}


def test_init_creates_preferences(tmp_path: Path):
    _init_profile_defaults(tmp_path)
    prefs_path = tmp_path / "Default" / "Preferences"
    assert prefs_path.exists()
    data = json.loads(prefs_path.read_text())
    assert "default_search_provider_data" in data
    assert "DuckDuckGo" in data["default_search_provider_data"]["template_url_data"]["short_name"]


def test_accept_language_value_adds_base_language():
    assert _accept_language_value("en-US") == "en-US,en"
    assert _accept_language_value("zh-HK") == "zh-HK,zh"


def test_sync_profile_locale_updates_chrome_preferences(tmp_path: Path):
    _init_profile_defaults(tmp_path)
    _sync_profile_locale(tmp_path, "en-US")

    prefs = json.loads((tmp_path / "Default" / "Preferences").read_text())
    assert prefs["intl"]["accept_languages"] == "en-US,en"
    assert prefs["intl"]["selected_languages"] == "en-US,en"
    assert prefs["translate"]["enabled"] is False

    local_state = json.loads((tmp_path / "Local State").read_text())
    assert local_state["intl"]["app_locale"] == "en-US"


def test_sync_session_restore_updates_chrome_preferences(tmp_path: Path):
    _init_profile_defaults(tmp_path)
    _sync_session_restore(tmp_path)

    prefs_path = tmp_path / "Default" / "Preferences"
    prefs = json.loads(prefs_path.read_text())
    assert prefs["session"]["restore_on_startup"] == 1


def test_sync_session_restore_preserves_existing_preferences(tmp_path: Path):
    _init_profile_defaults(tmp_path)
    prefs_path = tmp_path / "Default" / "Preferences"
    prefs = json.loads(prefs_path.read_text())
    prefs["session"] = {
        "restore_on_startup": 5,
        "startup_urls": ["https://example.com"],
    }
    prefs_path.write_text(json.dumps(prefs))

    _sync_session_restore(tmp_path)

    updated = json.loads(prefs_path.read_text())
    assert updated["session"] == {
        "restore_on_startup": 1,
        "startup_urls": ["https://example.com"],
    }


def test_build_locale_timezone_env_sets_process_time_and_language():
    env = _build_locale_timezone_env(
        locale="en-US",
        timezone="America/New_York",
        display=None,
    )

    assert env is not None
    assert env["TZ"] == "America/New_York"
    assert env["LANG"] == "en_US.UTF-8"
    assert env["LC_ALL"] == "en_US.UTF-8"
    assert env["LANGUAGE"] == "en_US:en"


@pytest.mark.parametrize("mode", ["init", "worker"])
def test_timezone_patch_keeps_invalid_dates_native(mode: str):
    if mode == "init":
        script = _build_fingerprint_init_script(
            locale=None,
            timezone="America/New_York",
            platform="macos",
        )
    else:
        script = _build_worker_fingerprint_patch({
            "locale": None,
            "languages": [],
            "timezone": "America/New_York",
            "platform": "macos",
        })

    assert script is not None
    node_code = f"""
const patch = {json.dumps(script)};
eval(patch);
const value = new Date(NaN);
console.log(JSON.stringify({{
  toString: value.toString(),
  toDateString: value.toDateString(),
  toTimeString: value.toTimeString(),
  toLocaleString: value.toLocaleString(),
}}));
"""
    result = subprocess.run(
        ["node", "-"],
        input=node_code,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "toString": "Invalid Date",
        "toDateString": "Invalid Date",
        "toTimeString": "Invalid Date",
        "toLocaleString": "Invalid Date",
    }


def test_init_idempotent(tmp_path: Path):
    _init_profile_defaults(tmp_path)
    bookmarks_path = tmp_path / "Default" / "Bookmarks"
    original = bookmarks_path.read_text()

    # Write a sentinel to the file
    bookmarks_path.write_text("SENTINEL")

    # Second call should NOT overwrite (file already exists)
    _init_profile_defaults(tmp_path)
    assert bookmarks_path.read_text() == "SENTINEL"


@pytest.mark.asyncio
async def test_launch_applies_locale_timezone_to_process_and_page(
    monkeypatch,
    tmp_path: Path,
):
    from backend import browser_manager as module

    context = MagicMock()
    context.pages = []
    context.add_init_script = AsyncMock()
    manager = BrowserManager(NATIVE_RUNTIME)
    manager._wait_for_cdp = AsyncMock()
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(module, "launch_persistent_context_async", launch)

    profile = _launch_profile(tmp_path)
    profile["locale"] = "en-US"
    profile["timezone"] = "America/New_York"

    await manager.launch(profile)

    options = launch.await_args.kwargs
    assert options["locale"] == "en-US"
    assert options["timezone"] == "America/New_York"
    assert "--lang=en-US" in options["args"]
    assert "--accept-lang=en-US,en" in options["args"]
    assert options["env"]["TZ"] == "America/New_York"
    assert options["env"]["LANG"] == "en_US.UTF-8"

    init_scripts = [call.args[0] for call in context.add_init_script.await_args_list]
    assert any("Navigator.prototype" in script for script in init_scripts)
    assert any("Date.prototype.getTimezoneOffset" in script for script in init_scripts)
