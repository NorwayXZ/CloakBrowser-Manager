"""iPhone (iOS) persona: presets, kernel switches, launch rules, reset and the self-check."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from backend import database as db
from backend import ios_persona, main, profile_reset
from backend.browser_manager import BrowserManager
from backend.fingerprint_report import analyze_fingerprint
from backend.runtime import RuntimeConfig

ROOT = Path(__file__).resolve().parents[2]
EDITOR_PRESETS = ROOT / "frontend" / "src" / "next" / "features" / "editor" / "deviceProfiles.ts"


def _manager(tmp_path: Path, host: str = "macos") -> BrowserManager:
    return BrowserManager(RuntimeConfig(host, "native", "native-window", tmp_path))


def _iphone(**extra) -> dict:
    return {"id": "p1", "platform": "ios", "device_profile": "iphone_15", "fingerprint_seed": 4242,
            "browser_engine": "cloakbrowser", **extra}


def test_every_iphone_is_a_real_screen_size():
    for device_id, (name, width, height, ratio) in ios_persona.IPHONES.items():
        assert device_id.startswith("iphone_") and name.startswith("iPhone")
        assert 375 <= width <= 440 and 667 <= height <= 956
        assert ratio in (2, 3)
    assert ios_persona.DEFAULT_IPHONE in ios_persona.IPHONES


def test_user_agent_is_a_real_safari_string():
    ua = ios_persona.USER_AGENT
    assert "iPhone; CPU iPhone OS" in ua and "Mobile/15E148 Safari/604.1" in ua
    assert "Chrome" not in ua and "Macintosh" not in ua


def test_defaults_fill_a_blank_iphone_and_never_follow_the_desktop():
    filled = ios_persona.with_defaults({"platform": "ios", "device_profile": "iphone_16_pro",
                                        "screen_width": 2560, "screen_height": 1440})
    assert (filled["screen_width"], filled["screen_height"]) == (402, 874)
    assert filled["user_agent"] == ios_persona.USER_AGENT
    assert filled["device_memory"] is None  # Safari has no deviceMemory
    assert (filled["gpu_vendor"], filled["gpu_renderer"]) == ("Apple Inc.", "Apple GPU")
    # what the user wrote is kept
    custom = ios_persona.with_defaults({"platform": "ios", "user_agent": "X", "gpu_renderer": "Y",
                                        "screen_width": 390, "screen_height": 844})
    assert custom["user_agent"] == "X" and custom["gpu_renderer"] == "Y"
    assert (custom["screen_width"], custom["screen_height"]) == (390, 844)


def test_pixel_ratio_follows_the_model():
    assert ios_persona.pixel_ratio({"device_profile": "iphone_se3"}) == 2
    assert ios_persona.pixel_ratio({"device_profile": "iphone_15"}) == 3
    assert ios_persona.pixel_ratio({"screen_width": 375, "screen_height": 667}) == 2
    assert ios_persona.pixel_ratio({}) == 3


def test_kernel_gets_the_host_platform_and_the_phone_hardware(tmp_path: Path):
    profile = ios_persona.with_defaults(_iphone())
    args = _manager(tmp_path)._build_fingerprint_args(profile)
    assert "--fingerprint-platform=macos" in args  # the kernel has no iOS; the look is layered on top
    assert "--fingerprint-gpu-vendor=Apple Inc." in args and "--fingerprint-gpu-renderer=Apple GPU" in args
    assert "--fingerprint-max-touch-points=5" in args
    assert "--touch-events=enabled" in args  # ontouchstart exists from a tab's first document
    assert not any(arg.startswith("--blink-settings") for arg in args)  # it fought the emulation
    assert "--fingerprint-taskbar-height=0" in args
    assert "--fingerprint-screen-width=393" in args and "--fingerprint-screen-height=852" in args
    assert "--fingerprint=4242" in args
    assert not any(a.startswith("--fingerprint-device-memory") for a in args)
    # canvas noise follows the profile's fingerprint options, not the persona
    assert "--fingerprint-noise=false" not in args
    assert "--fingerprint-noise=false" in _manager(tmp_path)._build_fingerprint_args(
        ios_persona.with_defaults(_iphone(fingerprint_options={"noise": False}))
    )
    assert not any("ios" in a for a in args)


def test_an_iphone_profile_always_uses_the_kernel_and_keeps_its_own_screen(tmp_path: Path):
    manager = _manager(tmp_path)
    assert manager._browser_engine(_iphone(browser_engine="system_chrome")) == "cloakbrowser"
    profile = _iphone(screen_width=393, screen_height=852)
    assert manager.follow_real_screen(profile) is profile  # desktop-sized "real" screen never applies


def test_preflight_needs_a_mac_and_warns_that_it_is_a_look(tmp_path: Path):
    mac = _manager(tmp_path).preflight(ios_persona.with_defaults(_iphone()))
    codes = {issue["code"]: issue["severity"] for issue in mac["issues"]}
    assert codes.get("ios_look_only") == "warning"
    assert "ios_needs_macos_host" not in codes and "host_platform_mismatch" not in codes
    assert mac["can_launch"] is True

    win = _manager(tmp_path, "windows").preflight(ios_persona.with_defaults(_iphone()))
    assert win["can_launch"] is False
    assert any(issue["code"] == "ios_needs_macos_host" for issue in win["issues"])


def test_preflight_rejects_a_desktop_user_agent_on_an_iphone(tmp_path: Path):
    result = _manager(tmp_path).preflight(
        ios_persona.with_defaults(_iphone(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/156.0.0.0 Safari/537.36"))
    )
    assert any(issue["code"] == "ua_platform_mismatch" for issue in result["issues"])
    assert result["can_launch"] is False


def test_reset_keeps_an_iphone_an_iphone():
    profile = _iphone()
    seen = set()
    for _ in range(40):
        fields = profile_reset.fresh_identity(profile, host_os="macos", native=False)
        assert fields["platform"] == "ios"
        assert fields["device_profile"] in ios_persona.IPHONES and fields["device_profile"] != "iphone_15"
        _, width, height, _ = ios_persona.IPHONES[fields["device_profile"]]
        assert (fields["screen_width"], fields["screen_height"]) == (width, height)
        assert fields["user_agent"] is None and fields["fingerprint_seed"] != 4242
        seen.add(fields["device_profile"])
    assert len(seen) > 1


def test_the_api_accepts_the_ios_platform(app_client: TestClient):
    created = app_client.post("/api/profiles", json={"name": "iPhone", "platform": "ios", "device_profile": "iphone_15"})
    assert created.status_code in (200, 201), created.text
    assert created.json()["platform"] == "ios"
    updated = app_client.put(f"/api/profiles/{created.json()['id']}", json={"platform": "ios", "device_profile": "iphone_16"})
    assert updated.status_code == 200 and updated.json()["device_profile"] == "iphone_16"


def test_init_script_hides_what_only_chrome_has():
    script = ios_persona.init_script({"device_profile": "iphone_se3"})
    for needle in ("userAgentData", "deviceMemory", "window.chrome", "'iPhone'", "Apple Computer, Inc."):
        assert needle in script
    assert "return 2;" in script and "return 3;" not in script  # the SE's ratio, not the default 3
    assert "'connection'" in script and "'getBattery'" in script  # Chrome-only members Safari does not have
    assert "__RATIO__" not in script and "__WORKER_PATCH__" not in script
    assert "WorkerNavigator" in script  # blob workers start with the worker patch


def _raw(*, user_agent: str, platform: str, ua_data=None, device_memory=None, touch=5) -> dict:
    return {"main": {"navigator": {"webdriver": False, "userAgent": user_agent, "platform": platform,
                                   "userAgentData": ua_data, "deviceMemory": device_memory, "maxTouchPoints": touch},
                     "page": {"secureContext": True}, "screen": {}, "graphics": {}, "nativeStrings": {}}}


def _analyze(raw: dict) -> dict:
    return analyze_fingerprint(raw, expected_locale=None, expected_timezone=None, expected_platform="ios",
                               expected_screen_width=None, expected_screen_height=None,
                               expected_hardware_concurrency=None)


def _signals(result: dict) -> set[str]:
    return {issue["signal"] for issue in result["issues"]}


def test_self_check_passes_a_clean_iphone():
    result = _analyze(_raw(user_agent=ios_persona.USER_AGENT, platform="iPhone"))
    assert not {"platform", "ios_chrome_only_api", "navigator.userAgentData"} & _signals(result)


def test_self_check_flags_a_desktop_platform_and_chrome_only_apis():
    result = _analyze(_raw(user_agent=ios_persona.USER_AGENT, platform="MacIntel",
                           ua_data={"platform": "macOS"}, device_memory=16, touch=0))
    signals = _signals(result)
    assert {"platform", "ios_chrome_only_api", "navigator.maxTouchPoints"} <= signals


def test_frontend_presets_match_the_backend_table():
    text = EDITOR_PRESETS.read_text(encoding="utf-8")
    for device_id, (_, width, height, _ratio) in ios_persona.IPHONES.items():
        match = re.search(rf'iphoneProfile\(\s*"{device_id}",\s*"[^"]*",\s*(\d+),\s*(\d+)', text)
        assert match, f"{device_id} is missing from the editor presets"
        assert (int(match.group(1)), int(match.group(2))) == (width, height)
    assert ios_persona.USER_AGENT in text  # the preset writes the same Safari string the backend defaults to


# --- workers: the patch goes in front of the script as the browser fetches it -------------------

def test_worker_patch_is_one_line_so_the_workers_line_numbers_hold():
    assert b"\n" not in ios_persona.WORKER_PATCH
    assert ios_persona.WORKER_PATCH.startswith(b"(() =>") and ios_persona.WORKER_PATCH.rstrip().endswith(b";")


@pytest.mark.parametrize("source, kept_first", [
    (b"postMessage(1)", None),
    (b"'use strict';\npostMessage(1)", b"'use strict';"),
    (b"'use strict'\npostMessage(1)", b"'use strict'"),   # no semicolon: one is added, or the patch would be a call on the string
    (b'// header\n"use strict"; postMessage(1)', b'// header\n"use strict";'),
])
def test_patch_goes_in_front_but_never_before_a_leading_use_strict(source: bytes, kept_first):
    patched = ios_persona.patch_worker_source(source)
    assert ios_persona.WORKER_PATCH in patched and patched.endswith(source[len(kept_first or b""):])
    if kept_first is None:
        assert patched.startswith(ios_persona.WORKER_PATCH)
    else:
        assert patched.startswith(kept_first)
        assert patched.index(kept_first) < patched.index(ios_persona.WORKER_PATCH)
        assert patched[len(kept_first):].lstrip(b";").startswith(ios_persona.WORKER_PATCH)


def test_worker_source_bytes_are_never_decoded():
    source = "const s = '你好';\n".encode() + bytes([0xff, 0xfe])  # not valid UTF-8 as a whole
    assert ios_persona.patch_worker_source(source).endswith(source)


class _Session:
    """A browser-level CDP session that records what the handler sends."""

    def __init__(self, body: bytes = b"postMessage(1)", fail_on: str | None = None) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.handlers: dict = {}
        self.body, self.fail_on = body, fail_on

    def on(self, name, handler):
        self.handlers[name] = handler

    async def send(self, method, params=None):
        self.sent.append((method, params or {}))
        if method == self.fail_on:
            raise RuntimeError("boom")
        if method == "Fetch.getResponseBody":
            import base64
            return {"body": base64.b64encode(self.body).decode(), "base64Encoded": True}
        return {}


async def _install(session: _Session):
    import types
    browser = types.SimpleNamespace(new_browser_cdp_session=lambda: _awaitable(session))
    context = types.SimpleNamespace(_cloak_browser=browser)
    await ios_persona.install_worker_patch(context, {"id": "p1"})
    return context


async def _awaitable(value):
    return value


async def _fire(session: _Session, context, **event):
    import asyncio
    session.handlers["Fetch.requestPaused"]({"requestId": "r1", **event})
    for task in list(context._ios_worker_session[1]):
        await task
    await asyncio.sleep(0)


JS_HEADERS = [{"name": "Content-Type", "value": "text/javascript"}, {"name": "Content-Length", "value": "14"},
              {"name": "Content-Encoding", "value": "gzip"}]


@pytest.mark.asyncio
async def test_only_worker_script_requests_are_intercepted_and_only_the_other_type():
    session = _Session()
    await _install(session)
    method, params = session.sent[0]
    assert method == "Fetch.enable"
    assert params["patterns"] == [{"resourceType": "Other", "requestStage": "Response"}]  # not every request


@pytest.mark.asyncio
async def test_a_javascript_response_is_rewritten_without_stale_length_or_encoding():
    import base64
    session = _Session(body=b"postMessage(1)")
    context = await _install(session)
    await _fire(session, context, responseStatusCode=200, responseHeaders=JS_HEADERS)
    sent = {m: p for m, p in session.sent}
    assert "Fetch.fulfillRequest" in sent and "Fetch.continueResponse" not in sent
    fulfilled = sent["Fetch.fulfillRequest"]
    assert base64.b64decode(fulfilled["body"]) == ios_persona.WORKER_PATCH + b"postMessage(1)"
    names = {h["name"].lower() for h in fulfilled["responseHeaders"]}
    assert "content-type" in names and not {"content-length", "content-encoding"} & names


@pytest.mark.asyncio
@pytest.mark.parametrize("event", [
    {"responseStatusCode": 200, "responseHeaders": [{"name": "Content-Type", "value": "image/x-icon"}]},    # favicon
    {"responseStatusCode": 404, "responseHeaders": JS_HEADERS},
    {"responseStatusCode": 302, "responseHeaders": JS_HEADERS},
    {"responseStatusCode": 200, "responseHeaders": [{"name": "Content-Type", "value": "text/javascript"},
                                                   {"name": "Content-Length", "value": str(10 * 1024 * 1024)}]},
])
async def test_everything_else_is_let_through_untouched(event):
    session = _Session()
    context = await _install(session)
    await _fire(session, context, **event)
    methods = [m for m, _ in session.sent]
    assert methods == ["Fetch.enable", "Fetch.continueResponse"]


@pytest.mark.asyncio
async def test_a_network_error_continues_the_request_instead_of_the_response():
    session = _Session()
    context = await _install(session)
    await _fire(session, context, responseErrorReason="ConnectionRefused")
    assert session.sent[-1][0] == "Fetch.continueRequest"


@pytest.mark.asyncio
async def test_a_failure_while_rewriting_never_leaves_the_request_hanging():
    session = _Session(fail_on="Fetch.fulfillRequest")
    context = await _install(session)
    await _fire(session, context, responseStatusCode=200, responseHeaders=JS_HEADERS)
    assert session.sent[-1][0] == "Fetch.continueResponse"


@pytest.mark.asyncio
async def test_no_browser_session_is_a_warning_not_a_failed_launch():
    import types
    await ios_persona.install_worker_patch(types.SimpleNamespace(), {"id": "p1"})  # returns normally


def test_init_script_covers_blob_and_data_workers():
    script = ios_persona.init_script({"device_profile": "iphone_15"})
    assert "new Proxy(OriginalWorker" in script and "OriginalBlob" in script


def test_preflight_rejects_a_gpu_that_is_not_an_iphones(tmp_path: Path):
    manager = _manager(tmp_path)
    wrong = manager.preflight(ios_persona.with_defaults(_iphone(
        gpu_vendor="Google Inc. (NVIDIA)", gpu_renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 4060)")))
    assert wrong["can_launch"] is False
    assert any(issue["code"] == "gpu_platform_mismatch" for issue in wrong["issues"])
    right = manager.preflight(ios_persona.with_defaults(_iphone()))
    assert not any(issue["code"] == "gpu_platform_mismatch" for issue in right["issues"])


@pytest.mark.asyncio
async def test_a_tab_opened_while_the_existing_ones_are_walked_is_still_emulated():
    import asyncio, types

    created: list = []

    class Context:
        def __init__(self):
            self.handlers = {}
            self.pages = [types.SimpleNamespace(name="restored")]

        def on(self, name, handler):
            self.handlers[name] = handler

        async def new_cdp_session(self, page):
            created.append(page.name)
            if page.name == "restored":                       # a tab opens while this await is pending
                self.handlers["page"](types.SimpleNamespace(name="popup"))
            await asyncio.sleep(0)
            return types.SimpleNamespace(send=lambda *a, **k: _awaitable({}), on=lambda *a, **k: None)

    context = Context()
    await ios_persona.apply_emulation(context, ios_persona.with_defaults({"id": "p", "platform": "ios", "device_profile": "iphone_15"}))
    await asyncio.sleep(0.05)
    assert sorted(created) == ["popup", "restored"]


class _AgentClient:
    """Answers only what the launch tool asks: the mcp mode, the profile and the launch itself."""

    def __init__(self, mode: str, platform: str) -> None:
        self.mode, self.platform, self.launched = mode, platform, False

    async def get(self, path, **_):
        if path == "/api/settings/mcp":
            return 200, {"mode": self.mode}
        return 200, {"id": "p1", "platform": self.platform}

    async def post(self, path, **_):
        self.launched = True
        return 200, {"profile_id": "p1", "status": "running", "launch_mode": "debug"}


@pytest.mark.asyncio
@pytest.mark.parametrize("platform, allowed", [("ios", False), ("macos", True)])
async def test_an_iphone_is_not_launched_below_the_automation_tier_through_the_manual_door(platform, allowed):
    from backend import agent_tools
    client = _AgentClient("full", platform)  # a tier below automation: no CDP for agents
    result = await agent_tools._launch_profile(client, {"profile_id": "p1", "launch_mode": "manual"})
    assert client.launched is allowed
    if not allowed:
        assert result["reason"] == "mode_not_automation"


def test_options_left_over_from_a_mac_never_change_an_iphones_screen_or_hints(tmp_path: Path):
    leftovers = {"taskbar_height": 95, "platform_version": "15.6.0", "brand": "Edge", "brand_version": "130"}
    args = _manager(tmp_path)._build_fingerprint_args(ios_persona.with_defaults(_iphone(fingerprint_options=leftovers)))
    assert "--fingerprint-taskbar-height=0" in args
    assert not any(a.startswith("--fingerprint-taskbar-height=") and a != "--fingerprint-taskbar-height=0" for a in args)
    assert not any(a.startswith("--fingerprint-platform-version") for a in args)
    assert not any(a.startswith("--fingerprint-brand") for a in args)
