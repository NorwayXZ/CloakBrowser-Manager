"""macOS: closing a profile's last window closes its browser and keeps its tabs."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import browser_manager as module
from backend.browser_manager import BrowserManager
from backend.runtime import RuntimeConfig
from backend.session_keeper import (
    SESSION_KEEPER_DIRNAME,
    profile_files_open,
    sync_session_keeper_extension,
    window_name_arg,
)

HARNESS = Path(__file__).parent / "js" / "session_keeper_harness.mjs"


def test_extension_is_invisible_to_pages_and_offline(tmp_path: Path):
    ext = sync_session_keeper_extension(tmp_path, port=18080)

    manifest = json.loads((ext / "manifest.json").read_text())
    assert set(manifest["permissions"]) == {"tabs", "storage"}
    for key in ("host_permissions", "content_scripts", "web_accessible_resources"):
        assert key not in manifest
    worker = (ext / "service_worker.js").read_text()
    assert "fetch(" not in worker
    assert '"managerOrigin":"http://127.0.0.1:18080"' in worker


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
    open_files = f"p42\nn/usr/lib/dyld\nn{default}/Cookies\n"

    assert profile_files_open(42, tmp_path, runner=_lsof(open_files)) is True
    assert profile_files_open(42, tmp_path, runner=_lsof("p42\nn/usr/lib/dyld\n")) is False
    # Another folder whose name merely starts the same way does not count.
    assert profile_files_open(42, tmp_path, runner=_lsof(f"n{default}-old/Cookies\n")) is False
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
        stop.assert_awaited_once_with("p1", reason="关闭了浏览器窗口")
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
async def test_windows_launch_is_unchanged(monkeypatch, tmp_path: Path):
    _manager, running, args = await _manual_launch(monkeypatch, tmp_path, "windows")

    assert running.window_watch_task is None
    assert not any(a.startswith(("--window-name", "--load-extension")) for a in args)
