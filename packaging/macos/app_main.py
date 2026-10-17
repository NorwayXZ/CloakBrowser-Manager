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
    check_for_app_update,
    current_app_path,
    handle_existing_manager,
    log_dir,
    login_item_enabled,
    manager_is_running,
    open_panel,
    panel_url,
    port_is_free,
    set_login_item,
)
from backend.runtime import resolve_runtime, server_port  # noqa: E402

APP_NAME = "CloakBrowser Manager"
READY_TIMEOUT_SECONDS = 60
SHUTDOWN_TIMEOUT_SECONDS = 45
UPDATE_CHECK_DELAY_SECONDS = 15

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


def _run_cocoa_app(url: str, server, server_thread: threading.Thread, *, background: bool) -> None:
    import objc
    from AppKit import (
        NSAlert,
        NSApplication,
        NSApplicationActivationPolicyRegular,
        NSMenu,
        NSMenuItem,
        NSAlertFirstButtonReturn,
        NSControlStateValueOff,
        NSControlStateValueOn,
        NSTerminateLater,
        NSTerminateNow,
    )
    from Foundation import NSObject
    from PyObjCTools import AppHelper

    app = NSApplication.sharedApplication()
    state = {"shutdown_done": False, "shutting_down": False}
    version = app_version()
    app_path = current_app_path()

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
                if not background:
                    open_panel(url)
                return
            time.sleep(0.2)
        AppHelper.callAfter(fail_and_quit, f"管理服务在 {READY_TIMEOUT_SECONDS} 秒内没有就绪。")

    def offer_update(info: dict, *, manual: bool) -> None:
        alert = NSAlert.alloc().init()
        if info.get("newer"):
            alert.setMessageText_(f"发现新版本 {info['latest']}")
            alert.setInformativeText_(
                f"当前版本 {version or '未知'}。下载后打开 DMG，把新 App 拖到「应用程序」覆盖旧版即可，"
                "画像、Cookie 等数据不受影响。"
            )
            alert.addButtonWithTitle_("下载新版本")
            alert.addButtonWithTitle_("以后再说")
        elif not manual:
            return
        elif info.get("error"):
            alert.setMessageText_("暂时无法检查更新")
            alert.setInformativeText_(f"连接 GitHub 失败：{info['error']}")
            alert.addButtonWithTitle_("好")
        else:
            alert.setMessageText_("已是最新版本")
            alert.setInformativeText_(f"当前版本 {version or '未知'}。")
            alert.addButtonWithTitle_("好")
        app.activateIgnoringOtherApps_(True)
        if alert.runModal() == NSAlertFirstButtonReturn and info.get("newer"):
            subprocess.run(["open", info["download_url"]], check=False)

    def check_updates(manual: bool) -> None:
        if not manual:
            time.sleep(UPDATE_CHECK_DELAY_SECONDS)
        try:
            info = check_for_app_update(version)
        except Exception as exc:
            logger.info("Update check failed: %s", exc)
            info = {"error": str(exc)}
        AppHelper.callAfter(offer_update, info, manual=manual)

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
            if version:
                threading.Thread(target=check_updates, args=(False,), daemon=True).start()

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

        @objc.IBAction
        def checkForUpdates_(self, _sender):
            threading.Thread(target=check_updates, args=(True,), daemon=True).start()

        @objc.IBAction
        def toggleLoginItem_(self, sender):
            enabled = not login_item_enabled()
            try:
                set_login_item(enabled, app_path)
            except OSError as exc:
                show_alert("无法修改开机启动", str(exc))
                return
            sender.setState_(NSControlStateValueOn if enabled else NSControlStateValueOff)

    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)

    def add_item(menu, title, action, key="", target=delegate):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        if target is not None:
            item.setTarget_(target)
        menu.addItem_(item)
        return item

    main_menu = NSMenu.alloc().init()
    app_item = NSMenuItem.alloc().init()
    main_menu.addItem_(app_item)
    app_menu = NSMenu.alloc().init()
    version_item = add_item(app_menu, f"版本 {version or '开发版'}", None, target=None)
    version_item.setEnabled_(False)
    add_item(app_menu, "检查更新…", "checkForUpdates:")
    app_menu.addItem_(NSMenuItem.separatorItem())
    add_item(app_menu, "打开管理面板", "openPanel:", "o")
    add_item(app_menu, "打开画像数据目录", "openDataDir:")
    add_item(app_menu, "打开日志目录", "openLogs:")
    login_item = add_item(app_menu, "登录时自动启动（不弹出面板）", "toggleLoginItem:" if app_path else None)
    login_item.setState_(NSControlStateValueOn if login_item_enabled() else NSControlStateValueOff)
    login_item.setEnabled_(app_path is not None)
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
    background = "--background" in sys.argv[1:]
    _configure_logging()
    url = panel_url()
    port = server_port()

    outcome, message = handle_existing_manager(url, port, app_version())
    if outcome == "reuse":
        # The same release, or a Manager started from the source checkout.
        logger.info("Manager already running at %s; opening panel", url)
        if not background:
            open_panel(url)
        return 0
    if outcome in {"busy", "failed"}:
        logger.warning("Another Manager release is running at %s: %s", url, outcome)
        return _alert_and_exit(f"{APP_NAME} 无法启动", message or "")
    if outcome == "replaced":
        logger.info("Stopped an older Manager at %s; starting %s", url, app_version())
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

    _run_cocoa_app(url, server, server_thread, background=background)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
