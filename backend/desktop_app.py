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


# The panel's page background in each theme (design/tokens.css, --c-canvas).
PANEL_CANVAS = {"light": (245, 245, 247), "dark": (28, 28, 30)}


def panel_look(theme: str | None, resolved: str | None = None) -> tuple[tuple[int, int, int] | None, str | None]:
    """(window background RGB, native appearance) matching the panel's theme.

    An explicit "light" or "dark" fixes both, so the window and its title bar do
    not flash the other colour before the page paints. "system" leaves the
    appearance to the operating system, as the panel does; the background then
    follows `resolved` (the theme the panel is actually showing, which only the
    panel knows) and stays unset until the panel has said.
    """
    appearance = theme if theme in PANEL_CANVAS else None
    shown = appearance or (resolved if resolved in PANEL_CANVAS else None)
    return (PANEL_CANVAS[shown] if shown else None), appearance


def saved_panel_theme(url: str, timeout: float = 0.5) -> str:
    """The theme saved in the panel's preferences; "system" when it cannot be read."""
    try:
        with urllib.request.urlopen(f"{url}/api/settings/ui", timeout=timeout) as response:
            theme = json.loads(response.read().decode("utf-8")).get("theme")
    except (OSError, ValueError, AttributeError):
        return "system"
    return theme if theme in ("light", "dark") else "system"


def log_dir(home: Path | None = None, system: str | None = None) -> Path:
    if (system or sys.platform) == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local and home is None else (home or Path.home()) / "AppData" / "Local"
        return base / "CloakBrowser Manager" / "Logs"
    return (home or Path.home()) / "Library" / "Logs" / "CloakBrowser Manager"


def manager_status(url: str, timeout: float = 0.5) -> dict | None:
    """The status payload when the port is serving this Manager, else None."""
    try:
        with urllib.request.urlopen(f"{url}/api/status", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(payload, dict) and all(key in payload for key in STATUS_KEYS):
        return payload
    return None


def manager_is_running(url: str, timeout: float = 0.5) -> bool:
    """Return true only when the port is serving this Manager's status API."""
    return manager_status(url, timeout) is not None


def existing_manager_action(status: Mapping[str, object], own_version: str | None) -> str:
    """What a freshly opened app does about a Manager already on its port.

    "reuse" when it is the same release (or this is a source build that has no
    version), "replace" when it is another release with no browser open, and
    "busy" when another release still has browsers open. Releases before
    0.4.2 do not report app_version, so they always count as another release.
    """
    if not own_version or status.get("app_version") == own_version:
        return "reuse"
    running = status.get("running_count")
    return "busy" if isinstance(running, int) and running > 0 else "replace"


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def listening_pid(port: int, *, system: str | None = None, runner: Runner = subprocess.run) -> int | None:
    """PID of the process listening on 127.0.0.1:port, if the OS tools can tell."""
    system = system or platform.system()
    try:
        if system == "Windows":
            output = runner(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10).stdout
            for line in output.splitlines():
                parts = line.split()
                if (
                    len(parts) >= 5
                    and parts[3].upper() == "LISTENING"
                    and parts[1].rsplit(":", 1)[-1] == str(port)
                    and parts[1].rsplit(":", 1)[0] in {"127.0.0.1", "0.0.0.0"}
                ):
                    return int(parts[4])
            return None
        output = runner(
            ["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        first = output.split()
        return int(first[0]) if first else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def process_command(pid: int, *, system: str | None = None, runner: Runner = subprocess.run) -> str:
    """Executable name or path of a process, or "" when it cannot be read."""
    system = system or platform.system()
    try:
        if system == "Windows":
            return runner(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        return runner(["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def stop_existing_manager(
    port: int,
    *,
    system: str | None = None,
    runner: Runner = subprocess.run,
    kill: Callable[[int, int], None] = os.kill,
    port_free: Callable[[int], bool] | None = None,
    sleep: Callable[[float], None] | None = None,
    timeout: float = 15.0,
) -> bool:
    """Ask the Manager listening on port to quit; True once the port is free.

    Only a process whose executable is CloakBrowser Manager is touched. On
    macOS it gets SIGTERM; on Windows taskkill without /F first, then a forced
    stop (the caller has already checked that no browser is open).
    """
    import signal
    import time

    system = system or platform.system()
    port_free = port_free or port_is_free
    sleep = sleep or time.sleep
    pid = listening_pid(port, system=system, runner=runner)
    if pid is None or pid == os.getpid():
        return False
    if "CloakBrowser" not in process_command(pid, system=system, runner=runner):
        return False

    def wait_for_port(seconds: float) -> bool:
        waited = 0.0
        while waited < seconds:
            if port_free(port):
                return True
            sleep(0.5)
            waited += 0.5
        return port_free(port)

    try:
        if system == "Windows":
            runner(["taskkill", "/PID", str(pid)], capture_output=True, text=True, timeout=10)
            if wait_for_port(timeout / 3):
                return True
            runner(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True, timeout=10)
        else:
            kill(pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        return False
    return wait_for_port(timeout)


def handle_existing_manager(
    url: str,
    port: int,
    own_version: str | None,
    *,
    status_reader: Callable[[str], dict | None] = manager_status,
    stopper: Callable[[int], bool] = stop_existing_manager,
) -> tuple[str, str | None]:
    """Decide what the launcher does about a Manager already on its port.

    Returns (outcome, message): "none" (nothing running), "reuse" (same
    release, open its panel), "replaced" (another release was stopped, start
    this one), or "busy"/"failed" with a message for the user.
    """
    status = status_reader(url)
    if status is None:
        return "none", None
    action = existing_manager_action(status, own_version)
    if action == "reuse":
        return "reuse", None
    found = status.get("app_version")
    other = f"{found} 版" if found else "旧版"
    if action == "busy":
        return "busy", (
            f"{other} CloakBrowser Manager 还在运行，并且有浏览器开着。"
            f"请先关闭这些浏览器，再从菜单栏/托盘退出旧版，然后重新打开 {own_version}。"
        )
    if stopper(port):
        return "replaced", None
    return "failed", (
        f"{other} CloakBrowser Manager 还在运行，没能自动退出它。"
        f"请从菜单栏/托盘或活动监视器/任务管理器退出旧版，然后重新打开 {own_version}。"
    )


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


# ── Quitting the app on request (one-click update) ───────────────────────────

_exit_hook: Callable[[], None] | None = None


def register_exit_hook(hook: Callable[[], None]) -> None:
    """The launcher's normal quit path (stops browsers, then the server)."""
    global _exit_hook
    _exit_hook = hook


def can_request_exit() -> bool:
    return _exit_hook is not None


def request_app_exit(delay: float = 1.5) -> bool:
    """Quit the app shortly, so the HTTP response that asked for it still goes out."""
    import threading

    hook = _exit_hook
    if hook is None:
        return False
    timer = threading.Timer(delay, hook)
    timer.daemon = True
    timer.start()
    return True


def request_update_from_panel(url: str, timeout: float = 10) -> tuple[bool, str]:
    """Ask the running Manager to start the one-click update (used by the menus)."""
    request = urllib.request.Request(f"{url}/api/app/update", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
        return True, "已开始更新：下载、备份后应用会自动重启。"
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except (ValueError, OSError):
            detail = None
        return False, str(detail or f"更新请求失败（{exc.code}）")
    except OSError as exc:
        return False, f"连接管理服务失败：{exc}"
