"""macOS: closing a profile's last window closes its browser and keeps its tabs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import browser_manager as module
from backend.browser_manager import BrowserManager
from backend.runtime import RuntimeConfig
from backend.session_keeper import (
    SESSION_KEEPER_DIRNAME,
    profile_files_open,
    request_app_quit,
    sync_session_keeper_extension,
    window_name_arg,
)

HARNESS = Path(__file__).parent / "js" / "session_keeper_harness.mjs"


def test_extension_is_invisible_to_pages_and_offline(tmp_path: Path):
    ext = sync_session_keeper_extension(tmp_path, port=18080)

    manifest = json.loads((ext / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["permissions"]) == {"tabs", "storage"}
    for key in ("host_permissions", "content_scripts", "web_accessible_resources"):
        assert key not in manifest
    worker = (ext / "service_worker.js").read_text(encoding="utf-8")
    assert "fetch(" not in worker
    assert '"managerOrigin":"http://127.0.0.1:18080"' in worker


def test_extension_makes_google_the_default_search(tmp_path: Path):
    ext = sync_session_keeper_extension(tmp_path, port=18080)

    provider = json.loads((ext / "manifest.json").read_text(encoding="utf-8"))["chrome_settings_overrides"]["search_provider"]
    assert provider["is_default"] is True
    assert provider["search_url"].startswith("https://www.google.com/search?q={searchTerms}")


def test_window_name_is_one_tidy_line():
    assert window_name_arg("  awsdee@eeaa.xyz \n 日本 ") == "--window-name=awsdee@eeaa.xyz 日本"
    assert window_name_arg("") is None
    assert len(window_name_arg("x" * 200)) == len("--window-name=") + 60


# ── The extension's own logic, run in Node ───────────────────────────────────

node = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")


def _run_worker(tmp_path: Path, scenario: str) -> dict:
    ext = sync_session_keeper_extension(tmp_path, port=18080)
    out = subprocess.run(
        ["node", str(HARNESS), str(ext / "service_worker.js"), scenario],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(out.stdout)


@node
def test_closing_the_last_window_keeps_the_tab_snapshot(tmp_path: Path):
    state = _run_worker(tmp_path, "snapshot")

    snapshot = state["storage"]["managerSessionSnapshot"]["windows"]
    assert [t["url"] for t in snapshot[0]["tabs"]] == ["https://mail.example.com/", "https://shop.example.com/a"]
    assert snapshot[0]["tabs"][1]["pinned"] is True


@node
def test_closing_one_of_two_windows_updates_the_snapshot(tmp_path: Path):
    state = _run_worker(tmp_path, "one-of-two")

    assert [w["tabs"][0]["url"] for w in state["storage"]["managerSessionSnapshot"]["windows"]] == ["https://a.example.com/"]


@node
def test_startup_reopens_the_snapshot_once_when_nothing_was_restored(tmp_path: Path):
    state = _run_worker(tmp_path, "restore")

    assert [(c["windowId"], c["url"], c["active"]) for c in state["created"]] == [
        (7, "https://mail.example.com/", True),
        (7, "https://shop.example.com/a", False),
    ]
    assert state["created"][1]["pinned"] is True
    assert [w["url"] for w in state["createdWindows"]] == [["https://docs.example.com/"]]


@node
def test_startup_leaves_a_session_chromium_restored_itself(tmp_path: Path):
    state = _run_worker(tmp_path, "already-restored")
    assert state["created"] == [] and state["createdWindows"] == []


# ── Telling a closed profile from an open one ────────────────────────────────


def _lsof(stdout: str, code: int = 0):
    return lambda *_a, **_k: subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


def test_profile_files_open_reads_lsof(tmp_path: Path):
    default = (tmp_path / "Default").resolve()
    open_files = f"p42\nn/usr/lib/dyld\nn{default}{os.sep}Cookies\n"

    assert profile_files_open(42, tmp_path, runner=_lsof(open_files)) is True
    assert profile_files_open(42, tmp_path, runner=_lsof("p42\nn/usr/lib/dyld\n")) is False
    # Another folder whose name merely starts the same way does not count.
    assert profile_files_open(42, tmp_path, runner=_lsof(f"n{default}-old{os.sep}Cookies\n")) is False
    assert profile_files_open(42, tmp_path, runner=_lsof("", code=2)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("readings", "stopped"), [
    ([True, False, False], True),            # closed: two empty checks in a row
    ([True, False, True, True], False),      # one blip, then open again
    ([None, None, None], False),             # lsof unavailable: never guess
])
async def test_window_watch_stops_only_after_two_empty_checks(monkeypatch, tmp_path: Path, readings, stopped):
    manager = BrowserManager(RuntimeConfig("macos", "native", "native-window", tmp_path))
    monkeypatch.setattr(module, "MAC_WINDOW_WATCH_START_SECONDS", 0)
    monkeypatch.setattr(module, "MAC_WINDOW_WATCH_INTERVAL_SECONDS", 0)
    remaining = list(readings)
    process = MagicMock(pid=42)
    process.poll.side_effect = lambda: None if remaining else 0
    monkeypatch.setattr(module, "profile_files_open", lambda *_a: remaining.pop(0))
    stop = AsyncMock()
    monkeypatch.setattr(manager, "stop", stop)

    await manager._watch_macos_windows("p1", process, tmp_path)

    if stopped:
        stop.assert_awaited_once_with("p1", reason="关闭了浏览器窗口", profile_closed=True)
    else:
        stop.assert_not_awaited()


# ── Launch wiring ────────────────────────────────────────────────────────────


def _profile(tmp_path: Path, engine: str, platform: str) -> dict:
    return {
        "id": "p1", "name": "awsdee@eeaa.xyz", "browser_engine": engine, "platform": platform,
        "fingerprint_seed": 1, "user_data_dir": str(tmp_path / "profile"),
        "screen_width": 1512, "screen_height": 982, "geoip": False,
    }


async def _manual_launch(monkeypatch, tmp_path: Path, host: str, engine: str = "cloakbrowser"):
    manager = BrowserManager(RuntimeConfig(host, "native", "native-window", tmp_path))
    launched = MagicMock(return_value=MagicMock(pid=4242, poll=MagicMock(return_value=None)))
    monkeypatch.setattr(module, "_launch_cloakbrowser_manual_process", launched)
    monkeypatch.setattr(module, "_launch_system_chrome_manual_process", launched)
    monkeypatch.setattr(manager, "_watch_process", AsyncMock())
    monkeypatch.setattr(manager, "_watch_macos_windows", AsyncMock())
    running = await manager.launch(_profile(tmp_path, engine, host), launch_mode="manual")
    return manager, running, launched.call_args.kwargs["args"]


@pytest.mark.asyncio
async def test_macos_launch_keeps_tabs_names_the_window_and_watches_it(monkeypatch, tmp_path: Path):
    manager, running, args = await _manual_launch(monkeypatch, tmp_path, "macos")

    keeper = tmp_path / "profile" / SESSION_KEEPER_DIRNAME
    assert any(a.startswith("--load-extension=") and str(keeper) in a for a in args)
    assert "--window-name=awsdee@eeaa.xyz" in args
    assert running.window_watch_task is not None
    await running.window_watch_task
    manager._watch_macos_windows.assert_awaited_once()


@pytest.mark.asyncio
async def test_system_chrome_on_macos_is_watched_but_gets_no_extension(monkeypatch, tmp_path: Path):
    _manager, running, args = await _manual_launch(monkeypatch, tmp_path, "macos", engine="system_chrome")

    assert "--window-name=awsdee@eeaa.xyz" in args
    assert running.window_watch_task is not None
    assert not (tmp_path / "profile" / SESSION_KEEPER_DIRNAME).exists()


@pytest.mark.asyncio
async def test_windows_launch_has_no_session_keeper(monkeypatch, tmp_path: Path):
    _manager, running, args = await _manual_launch(monkeypatch, tmp_path, "windows")

    assert running.window_watch_task is None
    assert not any(a.startswith("--window-name") for a in args)
    assert not (tmp_path / "profile" / SESSION_KEEPER_DIRNAME).exists()
    # The one extension a Windows manual launch does carry is the cookie
    # importer/pull-back extension, which is platform-independent.
    cookie_extension = tmp_path / "profile" / "manager-cookie-importer"
    assert any(
        a.startswith("--load-extension=") and str(cookie_extension) in a for a in args
    )


async def _debug_launch(monkeypatch, tmp_path: Path, *, headless: bool):
    manager = BrowserManager(RuntimeConfig("macos", "native", "native-window", tmp_path))
    manager._wait_for_cdp = AsyncMock()
    context = MagicMock(pages=[], _cloak_browser_process=MagicMock(pid=4242, poll=MagicMock(return_value=None)))
    context.add_init_script = AsyncMock()
    monkeypatch.setattr(module, "_launch_cloakbrowser_persistent_context_async", AsyncMock(return_value=context))
    monkeypatch.setattr(manager, "_watch_macos_windows", AsyncMock())
    running = await manager.launch(_profile(tmp_path, "cloakbrowser", "macos"), launch_mode="debug", headless=headless)
    return manager, running


@pytest.mark.asyncio
async def test_macos_debug_launch_is_watched_too(monkeypatch, tmp_path: Path):
    # Debug mode had no watch: its window closed, the browser stayed running.
    manager, running = await _debug_launch(monkeypatch, tmp_path, headless=False)

    assert running.window_watch_task is not None
    await running.window_watch_task
    manager._watch_macos_windows.assert_awaited_once()


@pytest.mark.asyncio
async def test_headless_debug_launch_has_no_window_to_watch(monkeypatch, tmp_path: Path):
    _manager, running = await _debug_launch(monkeypatch, tmp_path, headless=True)

    assert running.window_watch_task is None


# ── Ending a browser ─────────────────────────────────────────────────────────


class _Browser:
    """A running browser process that exits when asked to quit, unless stubborn."""

    def __init__(self, *, quits: bool):
        self.pid = 4242
        self.quits = quits
        self.quit_asked = False
        self.signals: list[str] = []
        self.returncode: int | None = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None and not (self.quit_asked and self.quits) and not self.signals:
            raise subprocess.TimeoutExpired("chromium", timeout)
        self.returncode = 0
        return 0

    def terminate(self):
        self.signals.append("TERM")

    def kill(self):
        self.signals.append("KILL")


@pytest.mark.asyncio
async def test_ending_a_browser_asks_that_app_to_quit_first(monkeypatch):
    browser = _Browser(quits=True)
    asked: list[int] = []

    def quit_app(pid):
        asked.append(pid)
        browser.quit_asked = True
        return True

    monkeypatch.setattr(module, "request_app_quit", quit_app)
    await module._terminate_process_async(browser)

    assert asked == [4242]
    assert browser.signals == []


@pytest.mark.asyncio
async def test_a_browser_that_does_not_quit_still_gets_sigterm(monkeypatch):
    browser = _Browser(quits=False)
    monkeypatch.setattr(module, "MAC_GRACEFUL_QUIT_SECONDS", 0)
    monkeypatch.setattr(module, "request_app_quit", lambda _pid: True)
    await module._terminate_process_async(browser)

    assert browser.signals == ["TERM"]


@pytest.mark.asyncio
async def test_without_an_app_to_ask_sigterm_is_sent_at_once(monkeypatch):
    browser = _Browser(quits=True)
    monkeypatch.setattr(module, "request_app_quit", lambda _pid: False)
    await module._terminate_process_async(browser)

    assert browser.signals == ["TERM"]


def test_request_app_quit_is_macos_only(monkeypatch):
    monkeypatch.setattr("backend.session_keeper.sys.platform", "win32")
    assert request_app_quit(os.getpid()) is False


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_request_app_quit_ignores_a_pid_that_is_no_app():
    # This test process is not an app, so there is nothing to ask (and nothing quits).
    assert request_app_quit(os.getpid()) is False


@pytest.mark.asyncio
async def test_a_browser_whose_window_closed_gets_sigterm_not_a_quit_request(monkeypatch):
    # Its profile is saved already; a quit request now would leave the
    # kernel's license seat taken for minutes.
    browser = _Browser(quits=True)
    asked: list[int] = []
    monkeypatch.setattr(module, "request_app_quit", lambda pid: asked.append(pid) or True)
    await module._terminate_process_async(browser, ask_to_quit=False)

    assert asked == []
    assert browser.signals == ["TERM"]


@pytest.mark.asyncio
async def test_stopping_after_the_last_window_closed_sigterms_before_the_context_closes(monkeypatch, tmp_path: Path):
    manager = BrowserManager(RuntimeConfig("macos", "native", "native-window", tmp_path))
    order: list[str] = []
    process = MagicMock(pid=4242)

    async def terminate(proc, *, ask_to_quit=True):
        order.append(f"terminate ask_to_quit={ask_to_quit}")

    async def close_context(*_a):
        order.append("close context")

    monkeypatch.setattr(module, "_terminate_process_async", terminate)
    monkeypatch.setattr(manager, "_close_context", close_context)
    manager.running["p1"] = module.RunningProfile(profile_id="p1", context=MagicMock(), cdp_port=None, browser_process=process)
    monkeypatch.setattr("backend.database.mark_profile_exit", lambda *_a: None)

    await manager.stop("p1", reason="关闭了浏览器窗口", profile_closed=True)

    assert order == ["terminate ask_to_quit=False", "close context", "terminate ask_to_quit=True"]
