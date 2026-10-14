"""Helpers for the double-clickable desktop builds (macOS .app/DMG, Windows installer).

Kept free of AppKit/pystray imports so the logic can be unit-tested on any host.
"""

from __future__ import annotations

import json
import os
import platform
import plistlib
import re
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path

from backend.runtime import server_port

GITHUB_REPO = "NorwayXZ/CloakBrowser-Manager"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
APP_BUNDLE_ID = "io.github.norwayxz.cloakbrowser-manager"
VERSION_FILE = "app_version.json"

CHROME_APP_CANDIDATES = (
    Path("/Applications/Google Chrome.app"),
    Path.home() / "Applications" / "Google Chrome.app",
)
STATUS_KEYS = ("running_count", "profiles_total", "runtime_mode")


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle instead of a source checkout."""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path | None:
    """Directory holding bundled data files (PyInstaller's _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def app_version(root: Path | None = None) -> str | None:
    """Version stamped into the packaged app by the build script."""
    base = root or bundle_root()
    if base is None:
        return None
    try:
        data = json.loads((base / VERSION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = data.get("version") if isinstance(data, dict) else None
    return str(version) if version else None


def parse_version(value: str | None) -> tuple[int, ...] | None:
    match = re.match(r"^v?(\d+(?:\.\d+)*)", (value or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest: str | None, current: str | None) -> bool:
    latest_v, current_v = parse_version(latest), parse_version(current)
    if latest_v is None or current_v is None:
        return False
    width = max(len(latest_v), len(current_v))
    pad = lambda v: v + (0,) * (width - len(v))  # noqa: E731
    return pad(latest_v) > pad(current_v)


def asset_keyword(system: str | None = None, machine: str | None = None) -> str:
    """Which release asset fits this computer, e.g. "arm64.dmg"."""
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    if system == "win32":
        return "windows"
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x86_64"
    return f"{arch}.dmg"


def fetch_latest_release(timeout: float = 10) -> dict | None:
    """Latest GitHub release, or None when the repo has not published one."""
    request = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "CloakBrowser-Manager"},
    )
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def check_for_app_update(
    current: str | None,
    *,
    fetch: Callable[[], dict | None] | None = None,
    keyword: str | None = None,
) -> dict:
    """Compare the running app with the latest release and pick a download link."""
    release = (fetch or fetch_latest_release)()
    if not release:
        return {"current": current, "latest": None, "newer": False, "download_url": None, "page_url": RELEASES_PAGE}
    latest = str(release.get("tag_name") or "").lstrip("v") or None
    page = str(release.get("html_url") or RELEASES_PAGE)
    wanted = keyword or asset_keyword()
    download = next(
        (
            str(asset.get("browser_download_url"))
            for asset in release.get("assets") or []
            if wanted in str(asset.get("name", "")).lower()
        ),
        None,
    )
    return {
        "current": current,
        "latest": latest,
        "newer": is_newer(latest, current),
        "download_url": download or page,
        "page_url": page,
    }


def launch_agent_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{APP_BUNDLE_ID}.plist"


def login_item_enabled(home: Path | None = None) -> bool:
    return launch_agent_path(home).is_file()


def set_login_item(enabled: bool, app_path: Path, home: Path | None = None) -> None:
    """Start the app (without opening the panel) when the user logs in."""
    path = launch_agent_path(home)
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": APP_BUNDLE_ID,
        "ProgramArguments": ["/usr/bin/open", "-g", "-a", str(app_path), "--args", "--background"],
        "RunAtLoad": True,
        "ProcessType": "Interactive",
    }
    path.write_bytes(plistlib.dumps(plist))


WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_RUN_VALUE = "CloakBrowser Manager"


def windows_login_command(executable: Path) -> str:
    return f'"{executable}" --background'


def windows_login_item_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
            winreg.QueryValueEx(key, WINDOWS_RUN_VALUE)
    except OSError:
        return False
    return True


def set_windows_login_item(enabled: bool, executable: Path) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, WINDOWS_RUN_VALUE, 0, winreg.REG_SZ, windows_login_command(executable))
        else:
            try:
                winreg.DeleteValue(key, WINDOWS_RUN_VALUE)
            except FileNotFoundError:
                pass


def current_app_path() -> Path | None:
    """The .app bundle this process runs from, if any."""
    executable = Path(sys.executable).resolve()
    for parent in executable.parents:
        if parent.suffix == ".app":
            return parent
    return None


def panel_url(environ: Mapping[str, str] | None = None) -> str:
    return f"http://127.0.0.1:{server_port(environ)}"


def log_dir(home: Path | None = None, system: str | None = None) -> Path:
    if (system or sys.platform) == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local and home is None else (home or Path.home()) / "AppData" / "Local"
        return base / "CloakBrowser Manager" / "Logs"
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


def windows_chrome_candidates(environ: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    env = os.environ if environ is None else environ
    roots = [env.get("PROGRAMFILES"), env.get("PROGRAMFILES(X86)"), env.get("LOCALAPPDATA")]
    return tuple(
        Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe" for root in roots if root
    )


def find_chrome(candidates: tuple[Path, ...] | None = None) -> Path | None:
    if candidates is None:
        candidates = windows_chrome_candidates() if sys.platform == "win32" else CHROME_APP_CANDIDATES
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def open_panel_command(url: str, chrome: Path | None, system: str | None = None) -> list[str] | None:
    """Open the panel in a standalone Chrome app window, else the default browser.

    macOS: `open -n` hands the arguments to an already-running Chrome, which
    then opens a new app window instead of a tab in the user's current window.
    Returns None when the default browser should be used via `webbrowser`.
    """
    system = system or sys.platform
    if system == "win32":
        return [str(chrome), f"--app={url}"] if chrome is not None else None
    if chrome is not None:
        return ["open", "-na", str(chrome), "--args", f"--app={url}"]
    return ["open", url]


def open_panel(
    url: str,
    *,
    chrome_app: Path | None = None,
    runner: Callable[[list[str]], object] | None = None,
) -> None:
    command = open_panel_command(url, chrome_app if chrome_app is not None else find_chrome())
    if command is None:
        import webbrowser

        webbrowser.open(url)
        return
    if runner is not None:
        runner(command)
    elif sys.platform == "win32":
        subprocess.Popen(command, close_fds=True)  # Chrome may keep running
    else:
        subprocess.run(command, check=False)
