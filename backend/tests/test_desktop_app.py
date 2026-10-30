from __future__ import annotations

import json
import plistlib
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from backend.desktop_app import (
    app_version,
    asset_keyword,
    check_for_app_update,
    existing_manager_action,
    find_chrome,
    handle_existing_manager,
    is_newer,
    launch_agent_path,
    listening_pid,
    log_dir,
    login_item_enabled,
    manager_is_running,
    open_panel,
    open_panel_command,
    panel_look,
    panel_url,
    port_is_free,
    set_login_item,
    saved_panel_theme,
    stop_existing_manager,
    windows_chrome_candidates,
    windows_login_command,
)


def _serve_status(payload: dict) -> tuple[HTTPServer, str]:
    body = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_panel_url_follows_port_env():
    assert panel_url({}) == "http://127.0.0.1:8080"
    assert panel_url({"CLOAKBROWSER_MANAGER_PORT": "18080"}) == "http://127.0.0.1:18080"


def test_log_dir_is_under_user_library(tmp_path: Path):
    assert log_dir(tmp_path, "darwin") == tmp_path / "Library" / "Logs" / "CloakBrowser Manager"


def test_manager_is_running_requires_manager_status_shape():
    server, url = _serve_status({"running_count": 0, "profiles_total": 2, "runtime_mode": "native"})
    try:
        assert manager_is_running(url)
    finally:
        server.shutdown()

    other, other_url = _serve_status({"hello": "world"})
    try:
        assert not manager_is_running(other_url)
    finally:
        other.shutdown()


def test_manager_is_running_false_when_nothing_listens():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert not manager_is_running(f"http://127.0.0.1:{port}", timeout=0.2)


def test_port_is_free_detects_listener():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert not port_is_free(port)
    assert port_is_free(port)


def test_find_chrome_returns_first_existing_app(tmp_path: Path):
    missing = tmp_path / "Missing.app"
    present = tmp_path / "Google Chrome.app"
    present.mkdir()
    assert find_chrome((missing, present)) == present
    assert find_chrome((missing,)) is None


def test_open_panel_prefers_chrome_app_window(tmp_path: Path):
    chrome = tmp_path / "Google Chrome.app"
    assert open_panel_command("http://127.0.0.1:8080", chrome, "darwin") == [
        "open", "-na", str(chrome), "--args", "--app=http://127.0.0.1:8080",
    ]
    assert open_panel_command("http://127.0.0.1:8080", None, "darwin") == ["open", "http://127.0.0.1:8080"]

    calls: list[list[str]] = []
    open_panel("http://127.0.0.1:8080", chrome_app=chrome, runner=calls.append)
    assert calls == [open_panel_command("http://127.0.0.1:8080", chrome)]


def test_app_version_reads_stamped_file(tmp_path: Path):
    assert app_version(tmp_path) is None
    (tmp_path / "app_version.json").write_text('{"version": "0.2.0", "commit": "abc"}')
    assert app_version(tmp_path) == "0.2.0"


def test_is_newer_compares_numerically():
    assert is_newer("0.10.0", "0.9.9")
    assert is_newer("v1.0", "0.9")
    assert not is_newer("0.2.0", "0.2")
    assert not is_newer("0.1.9", "0.2.0")
    assert not is_newer(None, "0.2.0")
    assert not is_newer("0.3.0", None)


def test_asset_keyword_matches_platform():
    assert asset_keyword("darwin", "arm64") == "arm64.dmg"
    assert asset_keyword("darwin", "x86_64") == "x86_64.dmg"
    assert asset_keyword("win32", "AMD64") == "windows"


def test_check_for_app_update_without_releases():
    info = check_for_app_update("0.2.0", fetch=lambda: None)
    assert info["latest"] is None and not info["newer"]


def test_check_for_app_update_falls_back_to_release_page():
    release = {"tag_name": "v0.3.0", "html_url": "https://page", "assets": []}
    info = check_for_app_update("0.2.0", fetch=lambda: release, keyword="arm64.dmg")
    assert info["newer"] and info["download_url"] == "https://page"


def test_login_item_round_trip(tmp_path: Path):
    app = Path("/Applications/CloakBrowser Manager.app")
    assert not login_item_enabled(tmp_path)
    set_login_item(True, app, tmp_path)
    assert login_item_enabled(tmp_path)
    plist = plistlib.loads(launch_agent_path(tmp_path).read_bytes())
    assert plist["ProgramArguments"] == ["/usr/bin/open", "-g", "-a", str(app), "--args", "--background"]
    assert plist["RunAtLoad"] is True
    set_login_item(False, app, tmp_path)
    assert not login_item_enabled(tmp_path)


def test_open_panel_command_on_windows(tmp_path: Path):
    chrome = tmp_path / "chrome.exe"
    assert open_panel_command("http://127.0.0.1:8080", chrome, "win32") == [
        str(chrome), "--app=http://127.0.0.1:8080",
    ]
    assert open_panel_command("http://127.0.0.1:8080", None, "win32") is None


def test_windows_chrome_candidates_use_env():
    candidates = windows_chrome_candidates({"PROGRAMFILES": "C:/PF", "LOCALAPPDATA": "C:/L"})
    assert [c.as_posix() for c in candidates] == [
        "C:/PF/Google/Chrome/Application/chrome.exe",
        "C:/L/Google/Chrome/Application/chrome.exe",
    ]


def test_log_dir_on_windows(tmp_path: Path):
    assert log_dir(tmp_path, "win32") == tmp_path / "AppData" / "Local" / "CloakBrowser Manager" / "Logs"


def test_windows_login_command_quotes_path():
    exe = Path("C:/Users/me/AppData/Local/Programs/CloakBrowser Manager/CloakBrowser Manager.exe")
    assert windows_login_command(exe) == f'"{exe}" --background'


# ── An older Manager already on the port ─────────────────────────────────────

def _runner(outputs: dict[str, str], calls: list[list[str]] | None = None):
    def run(cmd, **_kwargs):
        if calls is not None:
            calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout=outputs.get(cmd[0], ""), stderr="")
    return run


@pytest.mark.parametrize(("status", "own", "expected"), [
    ({"app_version": "0.4.3", "running_count": 0}, "0.4.3", "reuse"),
    ({"running_count": 0}, None, "reuse"),
    ({"running_count": 0}, "0.4.3", "replace"),
    ({"app_version": "0.4.2", "running_count": 0}, "0.4.3", "replace"),
    ({"app_version": "0.4.2", "running_count": 2}, "0.4.3", "busy"),
])
def test_existing_manager_action(status, own, expected):
    assert existing_manager_action(status, own) == expected


def test_listening_pid_reads_lsof_and_netstat():
    assert listening_pid(8080, system="Darwin", runner=_runner({"lsof": "37195\n"})) == 37195
    assert listening_pid(8080, system="Darwin", runner=_runner({"lsof": ""})) is None
    netstat = (
        "  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1012\n"
        "  TCP    127.0.0.1:18080        0.0.0.0:0              LISTENING       77\n"
        "  TCP    127.0.0.1:8080         0.0.0.0:0              LISTENING       4242\n"
    )
    assert listening_pid(8080, system="Windows", runner=_runner({"netstat": netstat})) == 4242


def test_stop_sends_sigterm_to_the_old_manager_on_macos():
    import signal

    killed = []
    free = iter([False, True])
    stopped = stop_existing_manager(
        8080,
        system="Darwin",
        runner=_runner({"lsof": "37195\n", "ps": "/Applications/CloakBrowser Manager.app/Contents/MacOS/CloakBrowser Manager"}),
        kill=lambda pid, sig: killed.append((pid, sig)),
        port_free=lambda _port: next(free),
        sleep=lambda _s: None,
    )
    assert stopped is True
    assert killed == [(37195, signal.SIGTERM)]


def test_stop_leaves_other_programs_alone():
    killed = []
    stopped = stop_existing_manager(
        8080,
        system="Darwin",
        runner=_runner({"lsof": "500\n", "ps": "/usr/local/bin/nginx"}),
        kill=lambda pid, sig: killed.append(pid),
        port_free=lambda _port: False,
        sleep=lambda _s: None,
    )
    assert stopped is False
    assert killed == []


def test_stop_asks_windows_politely_before_forcing():
    calls: list[list[str]] = []
    # Busy through the polite wait (4 polls + final check), free soon after /F.
    free = iter([False] * 6 + [True])
    stopped = stop_existing_manager(
        8080,
        system="Windows",
        runner=_runner({
            "netstat": "  TCP    127.0.0.1:8080   0.0.0.0:0   LISTENING   4242\n",
            "tasklist": '"CloakBrowser Manager.exe","4242","Console","1","80,000 K"',
        }, calls),
        port_free=lambda _port: next(free),
        sleep=lambda _s: None,
        timeout=6,
    )
    taskkills = [c for c in calls if c[0] == "taskkill"]
    assert stopped is True
    assert taskkills == [["taskkill", "/PID", "4242"], ["taskkill", "/PID", "4242", "/F"]]


def test_handle_existing_manager_outcomes():
    url = "http://127.0.0.1:8080"
    none = handle_existing_manager(url, 8080, "0.4.3", status_reader=lambda _u: None)
    assert none == ("none", None)

    same = {"app_version": "0.4.3", "running_count": 1, "profiles_total": 5, "runtime_mode": "native"}
    assert handle_existing_manager(url, 8080, "0.4.3", status_reader=lambda _u: same)[0] == "reuse"

    old = {"running_count": 0, "profiles_total": 5, "runtime_mode": "native"}
    stops = []
    outcome = handle_existing_manager(url, 8080, "0.4.3", status_reader=lambda _u: old,
                                      stopper=lambda port: stops.append(port) or True)
    assert outcome == ("replaced", None)
    assert stops == [8080]

    failed, message = handle_existing_manager(url, 8080, "0.4.3", status_reader=lambda _u: old,
                                              stopper=lambda _p: False)
    assert failed == "failed" and "没能自动退出" in message

    busy_status = {**old, "app_version": "0.4.2", "running_count": 2}
    busy, message = handle_existing_manager(url, 8080, "0.4.3", status_reader=lambda _u: busy_status,
                                            stopper=lambda _p: pytest.fail("must not stop a Manager with open browsers"))
    assert busy == "busy" and "0.4.2" in message and "关闭这些浏览器" in message


def test_panel_look_fixes_the_window_to_an_explicit_theme_and_follows_the_system_otherwise():
    assert panel_look("dark") == ((28, 28, 30), "dark")
    assert panel_look("light") == ((245, 245, 247), "light")
    # An explicit choice wins over what the panel reports it is showing.
    assert panel_look("dark", "light") == ((28, 28, 30), "dark")
    assert panel_look("system") == (None, None)
    # "system" follows the system's appearance but takes the background from what the panel shows.
    assert panel_look("system", "dark") == ((28, 28, 30), None)
    assert panel_look("system", "light") == ((245, 245, 247), None)
    assert panel_look("system", "sepia") == (None, None)
    assert panel_look(None) == (None, None)
    assert panel_look("sepia") == (None, None)


def test_saved_panel_theme_reads_the_preference_from_the_running_manager():
    server, url = _serve_status({"theme": "dark", "sidebar_collapsed": False, "interface": "new"})
    try:
        assert saved_panel_theme(url) == "dark"
    finally:
        server.shutdown()


def test_saved_panel_theme_is_system_when_unreadable_or_unknown():
    server, url = _serve_status({"theme": "sepia"})
    try:
        assert saved_panel_theme(url) == "system"
    finally:
        server.shutdown()
    unused = socket.socket()
    unused.bind(("127.0.0.1", 0))
    port = unused.getsockname()[1]
    unused.close()
    assert saved_panel_theme(f"http://127.0.0.1:{port}", timeout=0.2) == "system"
