from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from backend.desktop_app import (
    find_chrome,
    log_dir,
    manager_is_running,
    open_panel,
    open_panel_command,
    panel_url,
    port_is_free,
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
    assert log_dir(tmp_path) == tmp_path / "Library" / "Logs" / "CloakBrowser Manager"


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
