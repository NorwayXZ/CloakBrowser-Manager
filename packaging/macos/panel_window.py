"""The Manager panel in the app's own window (WKWebView), instead of a Chrome tab.

One window per app: clicking the Dock icon or "打开管理面板" brings it back
instead of opening another one; closing it only hides it; quitting the app
closes it together with the server and every browser.

WKWebView does nothing for confirm(), file inputs, downloads or new windows
unless the host implements them, so this module does:

* alert()/confirm() become native sheets on the window;
* <input type=file> opens an NSOpenPanel;
* downloads (backup zips, the configuration export blob) ask where to save;
* links to other sites and target=_blank open in the default browser.

The window's own background and appearance follow the panel's theme, so a dark
panel does not flash a white window while the page loads, and the title bar and
sheets match it. The panel reports its theme choice through the "cbmTheme"
script message whenever it changes.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import objc
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSAppearance,
    NSAppearanceNameAqua,
    NSAppearanceNameDarkAqua,
    NSApplication,
    NSBackingStoreBuffered,
    NSColor,
    NSMakeRect,
    NSModalResponseOK,
    NSOpenPanel,
    NSSavePanel,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
    NSWorkspace,
)
from Foundation import NSURL, NSURLRequest, NSObject, NSFileManager, NSHomeDirectory
from WebKit import WKWebView, WKWebViewConfiguration

from backend.desktop_app import panel_look, saved_panel_theme

logger = logging.getLogger("cloakbrowser.desktop.window")

WINDOW_TITLE = "CloakBrowser Manager"
FRAME_AUTOSAVE_NAME = "CloakBrowserManagerPanel"
DEFAULT_SIZE = (1320, 860)
MIN_SIZE = (1024, 680)
THEME_MESSAGE = "cbmTheme"

# WebKit enum values (WKNavigationActionPolicy / WKNavigationResponsePolicy).
POLICY_CANCEL = 0
POLICY_ALLOW = 1
POLICY_DOWNLOAD = 2


def _register_block_signatures() -> None:
    """PyObjC has no signature for these delegate callbacks' blocks; declare them.

    Argument indexes count self and _cmd, so a selector's first argument is 2.
    """
    def block(*arg_types: bytes) -> dict:
        arguments = {0: {"type": b"^v"}}
        arguments.update({i + 1: {"type": t} for i, t in enumerate(arg_types)})
        return {"type": b"@?", "callable": {"retval": {"type": b"v"}, "arguments": arguments}}

    signatures = {
        b"webView:decidePolicyForNavigationAction:decisionHandler:": (4, block(b"q")),
        b"webView:decidePolicyForNavigationResponse:decisionHandler:": (4, block(b"q")),
        b"webView:runJavaScriptAlertPanelWithMessage:initiatedByFrame:completionHandler:": (5, block()),
        b"webView:runJavaScriptConfirmPanelWithMessage:initiatedByFrame:completionHandler:": (5, block(b"Z")),
        b"webView:runOpenPanelWithParameters:initiatedByFrame:completionHandler:": (5, block(b"@")),
        b"download:decideDestinationUsingResponse:suggestedFilename:completionHandler:": (5, block(b"@")),
    }
    for selector, (index, meta) in signatures.items():
        objc.registerMetaDataForSelector(b"NSObject", selector, {"arguments": {index: meta}})


_register_block_signatures()


def is_panel_url(url: str | None, panel_url: str) -> bool:
    """Same scheme, host and port as the panel: stays inside the window."""
    if not url:
        return True
    if url.startswith(("about:", "blob:", "data:")):
        return True
    try:
        target, panel = urlsplit(url), urlsplit(panel_url)
    except ValueError:
        return False
    return (target.scheme, target.hostname, target.port) == (panel.scheme, panel.hostname, panel.port)


# No formal protocols= list: with it PyObjC takes WebKit's protocol encoding,
# which has no block signatures, and calling any decision handler fails.
class PanelWindowController(NSObject):
    def initWithURL_(self, url):
        self = objc.super(PanelWindowController, self).init()
        if self is None:
            return None
        self.url = str(url)
        self.window = None
        self.webview = None
        self.loaded = False
        return self

    # ── Window ───────────────────────────────────────────────────────────

    @objc.python_method
    def _build(self):
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable
        )
        rect = NSMakeRect(0, 0, *DEFAULT_SIZE)
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        window.setTitle_(WINDOW_TITLE)
        # The title bar takes the window's background colour, so it reads as part
        # of the panel (as in Apple's own apps) instead of a separate gray strip.
        window.setTitlebarAppearsTransparent_(True)
        window.setReleasedWhenClosed_(False)  # closing only hides; Dock click brings it back
        window.setContentMinSize_(MIN_SIZE)
        window.center()
        window.setFrameAutosaveName_(FRAME_AUTOSAVE_NAME)
        window.setDelegate_(self)

        config = WKWebViewConfiguration.alloc().init()
        config.userContentController().addScriptMessageHandler_name_(self, THEME_MESSAGE)
        webview = WKWebView.alloc().initWithFrame_configuration_(window.contentView().bounds(), config)
        webview.setAutoresizingMask_(18)  # width + height sizable
        webview.setUIDelegate_(self)
        webview.setNavigationDelegate_(self)
        window.setContentView_(webview)
        self.window = window
        self.webview = webview
        self._apply_look(saved_panel_theme(self.url))

    @objc.python_method
    def _apply_look(self, theme, resolved=None):
        """Window background and appearance matching the panel's theme preference."""
        rgb, appearance = panel_look(theme, resolved)
        if appearance is None:
            self.window.setAppearance_(None)  # follow the system, as the panel does
        else:
            name = NSAppearanceNameDarkAqua if appearance == "dark" else NSAppearanceNameAqua
            self.window.setAppearance_(NSAppearance.appearanceNamed_(name))
        if rgb is None:
            color = NSColor.windowBackgroundColor()
        else:
            color = NSColor.colorWithSRGBRed_green_blue_alpha_(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1.0)
        self.window.setBackgroundColor_(color)
        if hasattr(self.webview, "setUnderPageBackgroundColor_"):  # macOS 12+
            self.webview.setUnderPageBackgroundColor_(color)

    def userContentController_didReceiveScriptMessage_(self, _controller, message):
        body = message.body()
        theme = body.get("theme") if hasattr(body, "get") else None
        resolved = body.get("resolved") if hasattr(body, "get") else None
        if theme is not None:
            self._apply_look(str(theme), str(resolved) if resolved is not None else None)

    @objc.python_method
    def show(self):
        """Bring the single panel window to the front (create and load it once)."""
        if self.window is None:
            self._build()
        if not self.loaded:
            self.loaded = True
            self.webview.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(self.url)))
        self.window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        logger.info("Panel window shown")

    @objc.python_method
    def reload(self):
        if self.webview is not None:
            self.webview.reload_(None)

    # ── JavaScript dialogs ───────────────────────────────────────────────

    @objc.python_method
    def _alert(self, message, buttons):
        alert = NSAlert.alloc().init()
        alert.setMessageText_(WINDOW_TITLE)
        alert.setInformativeText_(str(message or ""))
        for title in buttons:
            alert.addButtonWithTitle_(title)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        return alert.runModal()

    def webView_runJavaScriptAlertPanelWithMessage_initiatedByFrame_completionHandler_(
        self, _webview, message, _frame, handler
    ):
        self._alert(message, ["好"])
        handler()

    def webView_runJavaScriptConfirmPanelWithMessage_initiatedByFrame_completionHandler_(
        self, _webview, message, _frame, handler
    ):
        handler(self._alert(message, ["确定", "取消"]) == NSAlertFirstButtonReturn)

    # ── File inputs ──────────────────────────────────────────────────────

    def webView_runOpenPanelWithParameters_initiatedByFrame_completionHandler_(
        self, _webview, parameters, _frame, handler
    ):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(bool(parameters.allowsMultipleSelection()))
        if panel.runModal() == NSModalResponseOK:
            handler(panel.URLs())
        else:
            handler(None)

    # ── Links and new windows ────────────────────────────────────────────

    @objc.python_method
    def _open_externally(self, nsurl):
        if nsurl is not None:
            NSWorkspace.sharedWorkspace().openURL_(nsurl)

    def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(
        self, _webview, _configuration, action, _features
    ):
        # target=_blank / window.open: hand the link to the default browser.
        self._open_externally(action.request().URL())
        return None

    def webView_decidePolicyForNavigationAction_decisionHandler_(self, _webview, action, handler):
        if action.shouldPerformDownload():
            handler(POLICY_DOWNLOAD)
            return
        url = action.request().URL()
        target = action.targetFrame()
        if target is not None and target.isMainFrame() and not is_panel_url(str(url.absoluteString()), self.url):
            self._open_externally(url)
            handler(POLICY_CANCEL)
            return
        handler(POLICY_ALLOW)

    def webView_decidePolicyForNavigationResponse_decisionHandler_(self, _webview, response, handler):
        handler(POLICY_ALLOW if response.canShowMIMEType() else POLICY_DOWNLOAD)

    def webViewWebContentProcessDidTerminate_(self, webview):
        logger.warning("Panel web content process ended; reloading")
        webview.reload_(None)

    # ── Downloads ────────────────────────────────────────────────────────

    def webView_navigationAction_didBecomeDownload_(self, _webview, _action, download):
        download.setDelegate_(self)

    def webView_navigationResponse_didBecomeDownload_(self, _webview, _response, download):
        download.setDelegate_(self)

    def download_decideDestinationUsingResponse_suggestedFilename_completionHandler_(
        self, _download, _response, filename, handler
    ):
        panel = NSSavePanel.savePanel()
        downloads = f"{NSHomeDirectory()}/Downloads"
        if NSFileManager.defaultManager().fileExistsAtPath_(downloads):
            panel.setDirectoryURL_(NSURL.fileURLWithPath_(downloads))
        panel.setNameFieldStringValue_(str(filename or "download"))
        panel.setCanCreateDirectories_(True)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        if panel.runModal() != NSModalResponseOK:
            handler(None)
            return
        destination = panel.URL()
        # The save panel already asked about replacing; make room for the file.
        NSFileManager.defaultManager().removeItemAtURL_error_(destination, None)
        handler(destination)

    def downloadDidFinish_(self, download):
        logger.info("Panel download finished: %s", download.originalRequest().URL().lastPathComponent())

    def download_didFailWithError_resumeData_(self, _download, error, _resume):
        logger.warning("Panel download failed: %s", error)
        self._alert(f"下载失败：{error.localizedDescription()}", ["好"])

    # ── Diagnostics ──────────────────────────────────────────────────────

    def webView_didFinishNavigation_(self, webview, _navigation):
        logger.info("Panel loaded: %s", webview.URL().absoluteString() if webview.URL() else "?")
