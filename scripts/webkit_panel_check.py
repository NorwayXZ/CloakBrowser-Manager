"""Check the panel inside the macOS app's real window (WKWebView), not Chromium.

The packaged app shows the panel with packaging/macos/panel_window.py. This
script runs that very window controller against a throwaway Manager (own data
directory, example data, no browser profile launched) and checks what only a
real WKWebView can show:

* every main page lays out without overflow or cut-off text, and has no script
  errors, in WebKit's engine (screenshots are written for a human look);
* the window background and title bar follow the panel's theme, before the page
  paints and when the theme is changed in the panel;
* a download starts the native save flow and the saved file is whole;
* <input type=file> reaches the native open flow and the page receives the file;
* links to other sites and window.open go to the default browser, never into
  the panel window;
* alert()/confirm() still map to native dialogs (the old panel uses them).

Native panels (save, open, alert) and "open in browser" are replaced by
recorders, so nothing waits for a click and no real browser opens; everything
between the page and those calls is the real code path.

    build/macos/venv/bin/python scripts/webkit_panel_check.py [output_dir]

Needs the macOS build venv (PyObjC) and a built frontend/dist.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

if sys.platform != "darwin":
    raise SystemExit("webkit_panel_check.py runs on macOS only")

from AppKit import (  # noqa: E402
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColorSpace,
    NSModalResponseOK,
)
from Foundation import NSURL, NSDate, NSRunLoop, NSURLRequest  # noqa: E402
from WebKit import WKUserScript  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "packaging" / "macos"))
sys.path.insert(0, str(HERE.parent))
from capture_baseline_ui import ROOT, call, free_port, seed, start_server  # noqa: E402
from capture_next_ui import LAYOUT_CHECK  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "webkit-check"

PAGES = [
    ("profiles", "/profiles", "tr[data-row]"),
    ("editor", "/profiles/new", "#form-basic"),
    ("proxies", "/proxies", "text=美国 SOCKS5"),
    ("checks", "/checks", "text=检测哪些网站"),
    ("evolution", "/checks/evolution", "text=进化时间线"),
    ("links", "/checks/links", "text=关联分析"),
    ("data", "/data", "text=备份记录"),
    ("trash", "/data/trash", "text=已删除的旧环境"),
    ("settings", "/settings", "text=主题"),
    ("kernel", "/settings/kernel", "text=已下载的内核"),
    ("ai", "/settings/ai", "text=执行强度"),
    ("about", "/settings/about", "text=还没有检查过"),
]

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail and not ok else ''}", flush=True)
    if not ok:
        failures.append(f"{name}: {detail}")


def pump(seconds: float) -> None:
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))


def wait_until(predicate, timeout: float = 20, step: float = 0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        pump(step)
    return None


class Panel:
    def __init__(self, controller):
        self.controller = controller
        self.webview = controller.webview

    def js(self, script: str, timeout: float = 15):
        box: dict = {}

        def done(result, error):
            box["result"], box["error"] = result, error
            box["done"] = True

        self.webview.evaluateJavaScript_completionHandler_(script, done)
        if not wait_until(lambda: box.get("done"), timeout):
            raise TimeoutError(f"JavaScript did not answer: {script[:80]}")
        if box["error"] is not None:
            raise RuntimeError(f"JavaScript failed: {box['error']}")
        return box["result"]

    def has(self, selector: str) -> bool:
        if selector.startswith("text="):
            return bool(self.js(f"document.body && document.body.innerText.includes({json.dumps(selector[5:])})"))
        return bool(self.js(f"!!document.querySelector({json.dumps(selector)})"))

    def open(self, base: str, path: str, ready: str, settle: float = 0.8) -> None:
        self.js("window.__stale = true")
        self.webview.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(base + path)))
        if not wait_until(lambda: self._fresh(), 30):
            raise TimeoutError(f"page did not load: {path}")
        if not wait_until(lambda: self.has(ready), 30):
            raise TimeoutError(f"{path}: never showed {ready!r}")
        pump(settle)

    def _fresh(self) -> bool:
        try:
            return self.js("document.readyState === 'complete' && !window.__stale") is True
        except Exception:
            return False

    def snapshot(self, path: Path) -> bool:
        box: dict = {}

        def done(image, error):
            box["image"], box["error"], box["done"] = image, error, True

        self.webview.takeSnapshotWithConfiguration_completionHandler_(None, done)
        if not wait_until(lambda: box.get("done"), 20) or box["image"] is None:
            return False
        rep = NSBitmapImageRep.alloc().initWithData_(box["image"].TIFFRepresentation())
        png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
        return bool(png.writeToFile_atomically_(str(path), True))


def rgb_of(color) -> tuple[int, int, int]:
    srgb = color.colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
    return tuple(round(c * 255) for c in (srgb.redComponent(), srgb.greenComponent(), srgb.blueComponent()))


def appearance_name(window) -> str:
    return str(window.effectiveAppearance().name())


def main() -> int:
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        print("frontend/dist is missing: run `npm run build` in frontend/ first", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="cbm-webkit-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = start_server(port)
    try:
        seed(base)
        call(base, "PUT", "/api/settings/ui", {"theme": "dark", "sidebar_collapsed": False, "interface": "new"})
        return run(base, work)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except Exception:
            proc.kill()


def run(base: str, work: Path) -> int:
    import panel_window

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # no Dock icon, no focus grab

    # Native pieces replaced by recorders (see the module docstring).
    saves: list[dict] = []
    opens: list[dict] = []
    external: list[str] = []
    alerts: list[tuple[str, list[str]]] = []
    save_to = work / "saved"
    save_to.mkdir()
    pick = work / "picked-by-user.txt"
    pick.write_text("hello from the open panel", encoding="utf-8")

    class FakeSavePanel:
        def __init__(self):
            self.name = None

        @classmethod
        def savePanel(cls):
            return cls()

        def setDirectoryURL_(self, _url): ...
        def setCanCreateDirectories_(self, _flag): ...

        def setNameFieldStringValue_(self, name):
            self.name = str(name)

        def runModal(self):
            saves.append({"name": self.name})
            return NSModalResponseOK

        def URL(self):
            return NSURL.fileURLWithPath_(str(save_to / (self.name or "download")))

    class FakeOpenPanel:
        @classmethod
        def openPanel(cls):
            return cls()

        def setCanChooseFiles_(self, _flag): ...
        def setCanChooseDirectories_(self, _flag): ...

        def setAllowsMultipleSelection_(self, flag):
            opens.append({"multiple": bool(flag)})

        def runModal(self):
            return NSModalResponseOK

        def URLs(self):
            return [NSURL.fileURLWithPath_(str(pick))]

    class FakeWorkspace:
        @classmethod
        def sharedWorkspace(cls):
            return cls()

        def openURL_(self, url):
            external.append(str(url.absoluteString()))

    panel_window.NSSavePanel = FakeSavePanel
    panel_window.NSOpenPanel = FakeOpenPanel
    panel_window.NSWorkspace = FakeWorkspace

    controller = panel_window.PanelWindowController.alloc().initWithURL_(base)
    controller._build()
    window = controller.window

    # ── The window looks right before the page has painted ────────────────
    check("window follows the saved dark theme before loading", appearance_name(window).endswith("DarkAqua"), appearance_name(window))
    check("window background is the dark canvas", rgb_of(window.backgroundColor()) == (14, 17, 24), str(rgb_of(window.backgroundColor())))

    # Behind every other window, without taking focus from whatever the user is doing.
    window.orderBack_(None)
    panel = Panel(controller)
    errors_script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        "window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message)));"
        "window.addEventListener('unhandledrejection', e => window.__errors.push('rejection: ' + String(e.reason)));",
        0,
        True,
    )
    controller.webview.configuration().userContentController().addUserScript_(errors_script)

    # ── Every main page in WebKit ─────────────────────────────────────────
    panel.open(base, "/profiles", "tr[data-row]")
    features = panel.js(
        "JSON.stringify({has: CSS.supports('selector(:has(a))'), mix: CSS.supports('color: color-mix(in srgb, red, blue)'),"
        " dvh: CSS.supports('height: 100dvh'), agent: navigator.userAgent})"
    )
    detail = json.loads(features)
    check("WebKit supports :has() and color-mix()", detail["has"] and detail["mix"], features)
    print(f"      engine: {detail['agent']}")

    for name, path, ready in PAGES:
        try:
            panel.open(base, path, ready)
            faults = json.loads(panel.js(f"JSON.stringify(({LAYOUT_CHECK})())"))
            errors = json.loads(panel.js("JSON.stringify(window.__errors || [])"))
            shot = panel.snapshot(OUT / f"{name}.png")
            check(f"page {name}: layout and script errors", not faults and not errors and shot, "; ".join(faults + errors) or "no snapshot")
        except Exception as exc:  # one page failing must not hide the rest
            check(f"page {name}", False, str(exc))

    # ── The theme chosen in the panel reaches the window ──────────────────
    panel.open(base, "/settings", "text=主题")
    panel.js("document.querySelector('input[name=theme][value=light]').click()")
    ok = wait_until(lambda: appearance_name(window).endswith("Aqua") and not appearance_name(window).endswith("DarkAqua"), 5)
    check("choosing light in the panel turns the window light", bool(ok), appearance_name(window))
    check("window background is the light canvas", rgb_of(window.backgroundColor()) == (246, 247, 250), str(rgb_of(window.backgroundColor())))
    panel.js("document.querySelector('input[name=theme][value=dark]').click()")
    ok = wait_until(lambda: appearance_name(window).endswith("DarkAqua"), 5)
    check("choosing dark turns it dark again", bool(ok), appearance_name(window))
    panel.js("document.querySelector('input[name=theme][value=system]').click()")
    ok = wait_until(lambda: window.appearance() is None, 5)
    check("choosing system hands the window back to the system", bool(ok))

    # ── Downloads ─────────────────────────────────────────────────────────
    panel.open(base, "/data", "text=备份记录")
    panel.js("(() => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob(['whole file'])); a.download = 'probe.txt'; document.body.appendChild(a); a.click(); a.remove(); })()")
    wait_until(lambda: (save_to / "probe.txt").exists() and (save_to / "probe.txt").read_text() == "whole file", 15)
    check("a blob download asks where to save and writes the whole file", saves[:1] == [{"name": "probe.txt"}] and (save_to / "probe.txt").exists() and (save_to / "probe.txt").read_text() == "whole file", f"saves={saves} files={[p.name for p in save_to.iterdir()]}")

    before = len(saves)
    panel.js("(() => { [...document.querySelectorAll('button')].find(b => b.textContent.includes('立即完整备份')).click(); })()")
    wait_until(lambda: len(saves) > before and any(p.suffix == ".zip" and p.stat().st_size > 0 for p in save_to.iterdir()), 120)
    zips = [p for p in save_to.iterdir() if p.suffix == ".zip"]
    check("the real 'full backup' button saves a non-empty zip", bool(zips) and zips[0].stat().st_size > 0, f"saves={saves[before:]}")
    if zips:
        import zipfile

        check("the saved backup is a valid zip", zipfile.is_zipfile(zips[0]))

    # ── File inputs ───────────────────────────────────────────────────────
    panel.js(
        "(() => { window.__picked = null; const input = document.createElement('input'); input.type = 'file'; input.style.display = 'none';"
        " input.addEventListener('change', async () => { window.__picked = input.files.length ? await input.files[0].text() : ''; });"
        " document.body.appendChild(input); window.__input = input; input.click(); })()"
    )
    wait_until(lambda: panel.js("window.__picked") is not None, 10)
    check("a file input opens the native panel and hands the file to the page", panel.js("window.__picked") == "hello from the open panel", str(panel.js("window.__picked")))

    # ── Links to other sites ──────────────────────────────────────────────
    page_url = str(panel.js("location.href"))
    panel.js("window.open('https://example.com/from-window-open')")
    panel.js("(() => { const a = document.createElement('a'); a.href = 'https://example.com/blank'; a.target = '_blank'; document.body.appendChild(a); a.click(); a.remove(); })()")
    panel.js("location.href = 'https://example.com/top-level'")
    wait_until(lambda: len(external) >= 3, 8)
    check("external links go to the default browser", set(external) >= {"https://example.com/from-window-open", "https://example.com/blank", "https://example.com/top-level"}, str(external))
    check("the panel window stays on the panel", str(panel.js("location.href")) == page_url, str(panel.js("location.href")))

    # ── alert / confirm (the previous panel still uses them) ──────────────
    controller._alert = lambda message, buttons: (alerts.append((str(message), list(buttons))) or panel_window.NSAlertFirstButtonReturn)  # type: ignore[method-assign]
    panel.js("window.__confirmed = null; window.__confirmed = confirm('删除这个环境？')")
    check("confirm() shows a native dialog and returns the answer", alerts[:1] == [("删除这个环境？", ["确定", "取消"])] and panel.js("window.__confirmed") is True, str(alerts))

    print(f"\nscreenshots in {OUT}")
    if failures:
        print(f"{len(failures)} check(s) failed", file=sys.stderr)
        return 1
    print("all WKWebView checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
