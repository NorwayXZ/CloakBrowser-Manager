from __future__ import annotations

import json
import plistlib
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from backend.desktop_app import (
    app_version,
    asset_keyword,
    check_for_app_update,
    find_chrome,
    is_newer,
    launch_agent_path,
    log_dir,
    login_item_enabled,
    manager_is_running,
    open_panel,
    open_panel_command,
    panel_url,
    port_is_free,
    set_login_item,
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
    assert open_panel_command("http://127.0.0.1:8080", chrome) == [
        "open", "-na", str(chrome), "--args", "--app=http://127.0.0.1:8080",
    ]
    assert open_panel_command("http://127.0.0.1:8080", None) == ["open", "http://127.0.0.1:8080"]

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
