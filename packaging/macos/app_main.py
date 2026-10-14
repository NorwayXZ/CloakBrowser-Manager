"""Entry point of the packaged macOS app (CloakBrowser Manager.app).

Double-clicking the app starts the Manager server in-process and opens the
panel in its own window. Clicking the Dock icon reopens the panel; quitting
the app (Cmd+Q or Dock > Quit) stops every running browser and the server.
Profile data stays in ~/Library/Application Support/CloakBrowser Manager,
shared with source-checkout installs.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time

os.environ.setdefault("CLOAKBROWSER_MANAGER_RUNTIME", "native")

from backend.desktop_app import (  # noqa: E402
    log_dir,
    manager_is_running,
    open_panel,
    panel_url,
    port_is_free,
)
from backend.runtime import resolve_runtime, server_port  # noqa: E402

APP_NAME = "CloakBrowser Manager"
READY_TIMEOUT_SECONDS = 60
SHUTDOWN_TIMEOUT_SECONDS = 45

logger = logging.getLogger("cloakbrowser.desktop")


def _configure_logging() -> None:
    """A Finder-launched app has no terminal: send all output to a log file."""
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_file = open(directory / "manager.log", "a", buffering=1, encoding="utf-8")
    # Point fds 1/2 at the log too, so child processes (Xray, Chromium) are captured.
    os.dup2(log_file.fileno(), 1)
    os.dup2(log_file.fileno(), 2)
    sys.stdout = log_file
    sys.stderr = log_file
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=log_file,
    )
    logger.info("---- %s starting (pid %s) ----", APP_NAME, os.getpid())


def _reveal(path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["open", str(path)], check=False)


def _run_cocoa_app(url: str, server, server_thread: threading.Thread) -> None:
    import objc
    from AppKit import (
        NSAlert,
        NSApplication,
        NSApplicationActivationPolicyRegular,
        NSMenu,
        NSMenuItem,
        NSTerminateLater,
        NSTerminateNow,
    )
    from Foundation import NSObject
    from PyObjCTools import AppHelper

    app = NSApplication.sharedApplication()
    state = {"shutdown_done": False, "shutting_down": False}

    def show_alert(title: str, message: str) -> None:
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_("好")
        app.activateIgnoringOtherApps_(True)
        alert.runModal()

    def fail_and_quit(message: str) -> None:
        show_alert(f"{APP_NAME} 启动失败", f"{message}\n\n日志：{log_dir() / 'manager.log'}")
        app.terminate_(None)

    def wait_until_ready() -> None:
        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if not server_thread.is_alive():
                AppHelper.callAfter(fail_and_quit, "管理服务意外退出。")
                return
            if manager_is_running(url):
                logger.info("Manager ready at %s", url)
                open_panel(url)
                return
            time.sleep(0.2)
        AppHelper.callAfter(fail_and_quit, f"管理服务在 {READY_TIMEOUT_SECONDS} 秒内没有就绪。")

    def stop_server() -> None:
        logger.info("Stopping Manager (closing all running browsers)...")
        server.should_exit = True
        server_thread.join(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        if server_thread.is_alive():
            logger.warning("Manager did not stop within %ss", SHUTDOWN_TIMEOUT_SECONDS)
        state["shutdown_done"] = True
        AppHelper.callAfter(app.replyToApplicationShouldTerminate_, True)

    class AppDelegate(NSObject):
        def applicationDidFinishLaunching_(self, _notification):
            threading.Thread(target=wait_until_ready, daemon=True).start()

        def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _flag):
            threading.Thread(target=open_panel, args=(url,), daemon=True).start()
            return True

        def applicationDockMenu_(self, _sender):
            menu = NSMenu.alloc().init()
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "打开管理面板", "openPanel:", ""
            )
            item.setTarget_(self)
            menu.addItem_(item)
            return menu

        def applicationShouldTerminate_(self, _sender):
            if state["shutdown_done"]:
                return NSTerminateNow
            if not state["shutting_down"]:
                state["shutting_down"] = True
                threading.Thread(target=stop_server, daemon=True).start()
            return NSTerminateLater

        @objc.IBAction
        def openPanel_(self, _sender):
            threading.Thread(target=open_panel, args=(url,), daemon=True).start()

        @objc.IBAction
        def openDataDir_(self, _sender):
            _reveal(resolve_runtime().data_dir)

        @objc.IBAction
        def openLogs_(self, _sender):
            _reveal(log_dir())

    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)

    def add_item(menu, title, action, key="", target=delegate):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        if target is not None:
            item.setTarget_(target)
        menu.addItem_(item)

    main_menu = NSMenu.alloc().init()
    app_item = NSMenuItem.alloc().init()
    main_menu.addItem_(app_item)
    app_menu = NSMenu.alloc().init()
    add_item(app_menu, "打开管理面板", "openPanel:", "o")
    add_item(app_menu, "打开画像数据目录", "openDataDir:")
    add_item(app_menu, "打开日志目录", "openLogs:")
    app_menu.addItem_(NSMenuItem.separatorItem())
    add_item(app_menu, f"隐藏 {APP_NAME}", "hide:", "h", target=None)
    add_item(app_menu, f"退出 {APP_NAME}", "terminate:", "q", target=None)
    app_item.setSubmenu_(app_menu)
    app.setMainMenu_(main_menu)

    AppHelper.runEventLoop()


def _alert_and_exit(title: str, message: str) -> int:
    from AppKit import NSAlert, NSApplication

    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(message)
    alert.addButtonWithTitle_("好")
    alert.runModal()
    return 1


def main() -> int:
    _configure_logging()
    url = panel_url()
    port = server_port()

    if manager_is_running(url):
        # A Manager started from the source checkout (./bin/cloak) is already up.
        logger.info("Manager already running at %s; opening panel", url)
        open_panel(url)
        return 0
    if not port_is_free(port):
        return _alert_and_exit(
            f"{APP_NAME} 无法启动",
            f"端口 {port} 已被其他程序占用。请先关闭占用该端口的程序后再打开。",
        )

    import uvicorn

    from backend.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None)
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, name="manager-server", daemon=True)
    server_thread.start()
    logger.info("Starting Manager at %s (data: %s)", url, resolve_runtime().data_dir)

    _run_cocoa_app(url, server, server_thread)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
