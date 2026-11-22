"""Tests for the real Apple WebKit (JavaScriptCore / Safari) iOS engine."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading

import pytest

from backend import ios_persona, webkit_ios
from backend.browser_manager import BrowserManager
from backend.fingerprint_report import run_fingerprint_probe
from backend.runtime import RuntimeConfig


def _manager(tmp_path: Path, host: str = "macos") -> BrowserManager:
    return BrowserManager(RuntimeConfig(host, "native", "native-window", tmp_path))


def _webkit_iphone(**extra) -> dict:
    base = {
        "id": "wk-1",
        "name": "iPhone WebKit",
        "platform": "ios",
        "browser_engine": "webkit",
        "device_profile": "iphone_15",
        "fingerprint_seed": 12345,
        "user_data_dir": "",
    }
    base.update(extra)
    return ios_persona.with_defaults(base)


def test_ios_defaults_to_webkit_while_preserving_cloakbrowser_choice(tmp_path: Path):
    mgr = _manager(tmp_path)
    assert mgr._browser_engine(_webkit_iphone(browser_engine="webkit")) == "webkit"
    assert mgr._browser_engine(_webkit_iphone(browser_engine="auto")) == "webkit"
    assert mgr._browser_engine(_webkit_iphone(browser_engine="cloakbrowser")) == "cloakbrowser"


def test_preflight_passes_webkit_ios_on_mac_without_look_only_warning(tmp_path: Path):
    mgr = _manager(tmp_path, "macos")
    report = mgr.preflight(_webkit_iphone())
    codes = {issue["code"] for issue in report["issues"]}
    assert report["can_launch"] is True
    assert report["browser_engine"] == "webkit"
    assert "ios_look_only" not in codes
    assert report["capabilities"]["native_webkit"] is True
    assert report["capabilities"]["external_cdp"] is False


def test_preflight_rejects_webkit_on_windows_or_desktop_personas(tmp_path: Path):
    win_report = _manager(tmp_path, "windows").preflight(_webkit_iphone())
    assert win_report["can_launch"] is False
    assert any(i["code"] == "ios_needs_macos_host" for i in win_report["issues"])

    desktop_report = _manager(tmp_path, "macos").preflight({
        "id": "m1",
        "platform": "macos",
        "browser_engine": "webkit",
        "screen_width": 1440,
        "screen_height": 900,
    })
    assert desktop_report["can_launch"] is False
    assert any(i["code"] == "webkit_ios_only" for i in desktop_report["issues"])


def test_jsc_worker_patch_preserves_strict_mode_and_four_space_native_code():
    profile = _webkit_iphone(hardware_concurrency=6)
    patched = webkit_ios.patch_webkit_worker_source(b"'use strict';\nself.ok = 1;\n", profile)
    assert patched.startswith(b"'use strict';")
    assert b"\\x20\\x20\\x20\\x20[native code]" in patched


def test_activate_playwright_browsers_path_overrides_pyinstaller_zero_hook(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "0")
    cache = webkit_ios.activate_playwright_browsers_path()
    assert cache.name == "ms-playwright"
    assert webkit_ios.os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(cache)

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/Applications/CloakBrowser Manager.app/Contents/Resources/.local-browsers")
    cache2 = webkit_ios.activate_playwright_browsers_path()
    assert webkit_ios.os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(cache2)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS AppKit titlebar tab bar only")
def test_macos_tabs_dylib_and_headed_launcher(tmp_path: Path):
    dylib = webkit_ios.ensure_macos_tabs_dylib()
    assert dylib is not None and dylib.is_file()
    fake_bin = tmp_path / "wk"
    pw_exec = fake_bin / "Playwright.app" / "Contents" / "MacOS" / "Playwright"
    pw_exec.parent.mkdir(parents=True)
    pw_exec.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher = webkit_ios._write_macos_headed_launcher(
        webkit_dir=tmp_path,
        webkit_bin_dir=fake_bin,
        dylib_path=dylib,
        profile_name="A 'iPhone' $1",
        start_url="http://127.0.0.1:8080/profile/p1/start",
        base_width=393,
        base_height=852,
    )
    assert launcher is not None and launcher.is_file()
    body = launcher.read_text(encoding="utf-8")
    assert "DYLD_INSERT_LIBRARIES=" in body
    assert "CLOAK_PROFILE_NAME=" in body
    assert "CLOAK_START_URL=" in body
    assert "CLOAK_TABS_FILE=" in body
    assert "CLOAK_BASE_WIDTH=393" in body
    assert "CLOAK_BASE_HEIGHT=852" in body


def test_session_tabs_persistence_and_start_page_port_remap(tmp_path: Path):
    class FakePage:
        def __init__(self, url: str):
            self.url = url

    class FakeContext:
        def __init__(self, pages: list[FakePage]):
            self.pages = pages

    start_8080 = "http://127.0.0.1:8080/profile/p1/start"
    start_9090 = "http://127.0.0.1:9090/profile/p1/start"

    # Only start page open -> does not create external session restore payload.
    webkit_ios.save_session_tabs_from_context(FakeContext([FakePage(start_8080)]), tmp_path, start_8080)
    assert webkit_ios.load_saved_session_tabs(tmp_path, start_8080) == ([], 0)

    # Start page + 2 external tabs -> persists all 3 and remaps start page to new port on next launch.
    ctx = FakeContext([
        FakePage(start_8080),
        FakePage("https://example.com/a"),
        FakePage("https://example.org/b"),
    ])
    webkit_ios.save_session_tabs_from_context(ctx, tmp_path, start_8080)
    # Simulate native AppKit having marked index 2 as active.
    saved = (tmp_path / webkit_ios.SESSION_TABS_FILENAME).read_text(encoding="utf-8")
    (tmp_path / webkit_ios.SESSION_TABS_FILENAME).write_text(
        saved.replace('"active_index": 0', '"active_index": 2'),
        encoding="utf-8",
    )
    # Empty context during teardown must NOT wipe previously saved tabs!
    webkit_ios.save_session_tabs_from_context(FakeContext([]), tmp_path, start_8080)

    urls, active_idx = webkit_ios.load_saved_session_tabs(tmp_path, start_9090)
    assert urls == [start_9090, "https://example.com/a", "https://example.org/b"]
    assert active_idx == 2


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin" or not webkit_ios.is_webkit_installed(), reason="requires installed macOS WebKit")
async def test_live_webkit_ios_passes_full_self_check_and_jsc_stealth(tmp_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.endswith(".js"):
                body = (
                    b"'use strict';\n"
                    b"postMessage({platform: navigator.platform, hc: navigator.hardwareConcurrency, "
                    b"fnStr: String(Object.getOwnPropertyDescriptor(WorkerNavigator.prototype, 'platform').get)});"
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = b"<!doctype html><html><body>ok</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        mgr = _manager(tmp_path, "macos")
        p1 = _webkit_iphone(
            id="wk-s1",
            user_data_dir=str(tmp_path / "p1"),
            fingerprint_seed=10101,
            locale="en-US",
            timezone="America/New_York",
            geoip=False,
        )
        p2 = _webkit_iphone(
            id="wk-s2",
            user_data_dir=str(tmp_path / "p2"),
            fingerprint_seed=20202,
            locale="en-US",
            timezone="America/New_York",
            geoip=False,
        )
        running1 = await mgr.launch(p1, headless=True)
        try:
            assert running1.browser_engine == "webkit"
            assert running1.context is not None
            page = running1.context.pages[0] if running1.context.pages else await running1.context.new_page()
            await page.goto(f"http://127.0.0.1:{port}/")
            probe = await page.evaluate(
                """async () => {
                  const getDesc = (o, k) => Object.getOwnPropertyDescriptor(o, k);
                  let receiverErr = '';
                  try { getDesc(Navigator.prototype, 'webdriver').get.call({}); } catch (e) { receiverErr = e.message; }
                  const f = document.createElement('iframe');
                  document.body.appendChild(f);
                  const wdGet = getDesc(Navigator.prototype, 'webdriver').get;
                  const syncIframe = {
                    wd: f.contentWindow.navigator.webdriver,
                    pf: f.contentWindow.navigator.platform,
                    safari: 'safari' in f.contentWindow,
                    crossWdStr: f.contentWindow.Function.prototype.toString.call(wdGet),
                    crossToStr: f.contentWindow.Function.prototype.toString.call(Function.prototype.toString),
                  };
                  f.remove();
                  const oac = new (window.OfflineAudioContext || window.webkitOfflineAudioContext)(1, 256, 44100);
                  const osc = oac.createOscillator();
                  osc.connect(oac.destination);
                  osc.start(0);
                  const audioBuf = await oac.startRendering();
                  const copyArr = new Float32Array(256);
                  audioBuf.copyFromChannel(copyArr, 0);
                  const audioMatches = String([...audioBuf.getChannelData(0)].slice(0, 32)) === String([...copyArr].slice(0, 32));
                  const worker = await new Promise((resolve, reject) => {
                    const w = new Worker('/w.js');
                    w.onmessage = e => { w.terminate(); resolve(e.data); };
                    w.onerror = e => reject(e.message);
                  });
                  let devtoolsGetterFired = false;
                  const trap = {};
                  Object.defineProperty(trap, 'id', { get() { devtoolsGetterFired = true; return 'x'; } });
                  console.debug(trap);
                  console.log(trap);
                  console.dir(trap);
                  return {
                    evalLen: eval.toString().length,
                    hasChrome: 'chrome' in window,
                    hasSafari: 'safari' in window,
                    wd: navigator.webdriver,
                    wdOwn: Object.prototype.hasOwnProperty.call(navigator, 'webdriver'),
                    wdStr: String(wdGet),
                    wdHasProto: Object.prototype.hasOwnProperty.call(wdGet, 'prototype'),
                    receiverErr,
                    devtoolsGetterFired,
                    consoleDebugStr: String(console.debug),
                    pf: navigator.platform,
                    mtp: navigator.maxTouchPoints,
                    hc: navigator.hardwareConcurrency,
                    pdf: navigator.pdfViewerEnabled,
                    plugins: navigator.plugins.length,
                    pluginKeys: Object.getOwnPropertyNames(navigator.plugins),
                    pluginSpread: [...navigator.plugins].length,
                    mimes: navigator.mimeTypes.length,
                    audioMatches,
                    syncIframe,
                    worker,
                  };
                }"""
            )
            assert probe["evalLen"] == 37  # genuine JavaScriptCore, not V8 (33)
            assert probe["hasChrome"] is False
            assert probe["hasSafari"] is False
            assert probe["wd"] is False and probe["wdOwn"] is False
            assert probe["wdStr"] == "function webdriver() {\n    [native code]\n}"
            assert probe["wdHasProto"] is False
            assert probe["receiverErr"] == "The Navigator.webdriver getter can only be used on instances of Navigator"
            assert probe["devtoolsGetterFired"] is False
            assert probe["consoleDebugStr"] == "function debug() {\n    [native code]\n}"
            assert probe["pf"] == "iPhone"
            assert probe["mtp"] == 5
            assert probe["hc"] == 6
            assert probe["pdf"] is False
            assert probe["plugins"] == 0 and probe["mimes"] == 0
            assert probe["pluginKeys"] == [] and probe["pluginSpread"] == 0
            assert probe["audioMatches"] is True
            assert probe["syncIframe"] == {
                "wd": False,
                "pf": "iPhone",
                "safari": False,
                "crossWdStr": "function webdriver() {\n    [native code]\n}",
                "crossToStr": "function toString() {\n    [native code]\n}",
            }
            assert probe["worker"] == {
                "platform": "iPhone",
                "hc": 6,
                "fnStr": "function platform() {\n    [native code]\n}",
            }

            report1 = await mgr.fingerprint_report(p1)
            assert report1["analysis"]["status"] == "pass"
            assert report1["analysis"]["error_count"] == 0
            assert report1["analysis"]["warning_count"] == 0
        finally:
            await mgr.stop("wk-s1")

        running2 = await mgr.launch(p2, headless=True)
        try:
            raw2 = await run_fingerprint_probe(running2.context)
            assert report1["raw"]["main"]["graphics"]["canvasHashA"] != raw2["main"]["graphics"]["canvasHashA"]
            assert report1["raw"]["main"]["graphics"]["audioHashA"] != raw2["main"]["graphics"]["audioHashA"]
        finally:
            await mgr.stop("wk-s2")
    finally:
        srv.shutdown()
