"""Helpers for the double-clickable desktop build (macOS .app inside a DMG).

Kept free of AppKit imports so the logic can be unit-tested on any host.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path

from backend.runtime import server_port

CHROME_APP_CANDIDATES = (
    Path("/Applications/Google Chrome.app"),
    Path.home() / "Applications" / "Google Chrome.app",
)
STATUS_KEYS = ("running_count", "profiles_total", "runtime_mode")


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle instead of a source checkout."""
    return bool(getattr(sys, "frozen", False))


def panel_url(environ: Mapping[str, str] | None = None) -> str:
    return f"http://127.0.0.1:{server_port(environ)}"


def log_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "Logs" / "CloakBrowser Manager"


def manager_is_running(url: str, timeout: float = 0.5) -> bool:
    """Return true only when the port is serving this Manager's status API."""
    try:
        with urllib.request.urlopen(f"{url}/api/status", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(payload, dict) and all(key in payload for key in STATUS_KEYS)


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def find_chrome(candidates: tuple[Path, ...] = CHROME_APP_CANDIDATES) -> Path | None:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def open_panel_command(url: str, chrome_app: Path | None) -> list[str]:
    """Open the panel in a standalone Chrome app window, else the default browser.

    `open -n` hands the arguments to an already-running Chrome, which then
    opens a new app window instead of a tab in the user's current window.
    """
    if chrome_app is not None:
        return ["open", "-na", str(chrome_app), "--args", f"--app={url}"]
    return ["open", url]


def open_panel(
    url: str,
    *,
    chrome_app: Path | None = None,
    runner: Callable[[list[str]], object] | None = None,
) -> None:
    run = runner or (lambda command: subprocess.run(command, check=False))
    run(open_panel_command(url, chrome_app if chrome_app is not None else find_chrome()))
