"""Entry point of the packaged Windows app (CloakBrowser Manager.exe).

Starting the app runs the Manager server in-process, opens the panel in a
Chrome app window and puts an icon in the notification area. The tray menu
reopens the panel, checks for updates, toggles start-at-login and quits;
quitting stops every running browser first. Profile data stays in
%LOCALAPPDATA%\\CloakBrowser Manager, shared with source-checkout installs.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("CLOAKBROWSER_MANAGER_RUNTIME", "native")


def _use_bundled_certificates() -> None:
    """The bundled Python has no system CA store; point OpenSSL at certifi's."""
    try:
        import certifi
    except ImportError:
        return
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())


_use_bundled_certificates()

from backend.desktop_app import (  # noqa: E402
    app_version,
    bundle_root,
    check_for_app_update,
    handle_existing_manager,
    log_dir,
    manager_is_running,
    open_panel,
    panel_url,
    port_is_free,
    set_windows_login_item,
    windows_login_item_enabled,
)
from backend.runtime import resolve_runtime, server_port  # noqa: E402

APP_NAME = "CloakBrowser Manager"
READY_TIMEOUT_SECONDS = 60
SHUTDOWN_TIMEOUT_SECONDS = 45
UPDATE_CHECK_DELAY_SECONDS = 15

MB_OK = 0x0
MB_YESNO = 0x4
MB_ICONINFORMATION = 0x40
MB_ICONWARNING = 0x30
IDYES = 6

logger = logging.getLogger("cloakbrowser.desktop")


def _message_box(text: str, title: str = APP_NAME, flags: int = MB_OK | MB_ICONINFORMATION) -> int:
    import ctypes

    return ctypes.windll.user32.MessageBoxW(None, text, title, flags | 0x10000)  # MB_SETFOREGROUND


def _configure_logging() -> None:
    """A windowed app has no console: send all output to a log file."""
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_file = open(directory / "manager.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=log_file,
    )
    logger.info("---- %s starting (pid %s) ----", APP_NAME, os.getpid())


def _reveal(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(str(path))  # type: ignore[attr-defined]


def _tray_image():
    from PIL import Image

    root = bundle_root()
    icon = root / "app_icon.png" if root else None
    if icon and icon.is_file():
        return Image.open(icon)
    return Image.new("RGBA", (64, 64), (60, 110, 230, 255))


def main() -> int:
    background = "--background" in sys.argv[1:]
    _configure_logging()
    url = panel_url()
    port = server_port()
    version = app_version()

    outcome, message = handle_existing_manager(url, port, version)
    if outcome == "reuse":
        logger.info("Manager already running at %s; opening panel", url)
        if not background:
            open_panel(url)
        return 0
    if outcome in {"busy", "failed"}:
        logger.warning("Another Manager release is running at %s: %s", url, outcome)
        _message_box(message or "", f"{APP_NAME} 无法启动", MB_OK | MB_ICONWARNING)
        return 1
    if outcome == "replaced":
        logger.info("Stopped an older Manager at %s; starting %s", url, version)
    if not port_is_free(port):
        _message_box(
            f"端口 {port} 已被其他程序占用。请先关闭占用该端口的程序后再打开。",
            f"{APP_NAME} 无法启动",
            MB_OK | MB_ICONWARNING,
        )
        return 1

    import pystray
    import uvicorn

    from backend.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None)
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, name="manager-server", daemon=True)
    server_thread.start()
    logger.info("Starting Manager at %s (data: %s)", url, resolve_runtime().data_dir)

    def open_panel_async(*_args) -> None:
        threading.Thread(target=open_panel, args=(url,), daemon=True).start()

    def wait_until_ready(icon) -> None:
        icon.visible = True
        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if not server_thread.is_alive():
                fail(icon, "管理服务意外退出。")
                return
            if manager_is_running(url):
                logger.info("Manager ready at %s", url)
                if not background:
                    open_panel(url)
                if version:
                    threading.Thread(target=check_updates, args=(False,), daemon=True).start()
                return
            time.sleep(0.2)
        fail(icon, f"管理服务在 {READY_TIMEOUT_SECONDS} 秒内没有就绪。")

    def fail(icon, message: str) -> None:
        _message_box(f"{message}\n\n日志：{log_dir() / 'manager.log'}", f"{APP_NAME} 启动失败", MB_OK | MB_ICONWARNING)
        quit_app(icon)

    def check_updates(manual: bool) -> None:
        if not manual:
            time.sleep(UPDATE_CHECK_DELAY_SECONDS)
        try:
            info = check_for_app_update(version)
        except Exception as exc:
            logger.info("Update check failed: %s", exc)
            if manual:
                _message_box(f"连接 GitHub 失败：{exc}", "暂时无法检查更新", MB_OK | MB_ICONWARNING)
            return
        if info["newer"]:
            answer = _message_box(
                f"发现新版本 {info['latest']}（当前 {version}）。\n\n"
                "下载后运行新的安装程序即可覆盖升级，画像、Cookie 等数据不受影响。\n\n现在下载吗？",
                "发现新版本",
                MB_YESNO | MB_ICONINFORMATION,
            )
            if answer == IDYES:
                os.startfile(info["download_url"])  # type: ignore[attr-defined]
        elif manual:
            _message_box(f"当前版本 {version or '未知'} 已是最新。", "检查更新")

    def toggle_login_item(_icon, _item) -> None:
        try:
            set_windows_login_item(not windows_login_item_enabled(), Path(sys.executable))
        except OSError as exc:
            _message_box(str(exc), "无法修改开机启动", MB_OK | MB_ICONWARNING)

    def quit_app(icon, *_args) -> None:
        logger.info("Stopping Manager (closing all running browsers)...")
        server.should_exit = True
        server_thread.join(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("打开管理面板", open_panel_async, default=True),
        pystray.MenuItem(f"版本 {version or '开发版'}", None, enabled=False),
        pystray.MenuItem("检查更新…", lambda *_: threading.Thread(target=check_updates, args=(True,), daemon=True).start()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("打开画像数据目录", lambda *_: _reveal(resolve_runtime().data_dir)),
        pystray.MenuItem("打开日志目录", lambda *_: _reveal(log_dir())),
        pystray.MenuItem(
            "开机自动启动（不弹出面板）",
            toggle_login_item,
            checked=lambda _item: windows_login_item_enabled(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出（关闭所有浏览器）", quit_app),
    )
    icon = pystray.Icon("cloakbrowser-manager", _tray_image(), APP_NAME, menu)
    icon.run(setup=wait_until_ready)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
