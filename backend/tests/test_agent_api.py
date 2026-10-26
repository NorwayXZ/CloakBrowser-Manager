"""Tests for the Manager's agent surface: leases, scoped tokens, page control,
the tool API and the HTTP MCP endpoint."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from backend import agent_auth, agent_lease
from backend.page_control import PageControlError, PageController


# ── LeaseRegistry ────────────────────────────────────────────────────────────


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_lease_same_holder_renews_other_holder_is_refused():
    clock = Clock()
    leases = agent_lease.LeaseRegistry(clock)
    ok, first = leases.acquire("p1", "codex#1", ttl=60)
    assert ok
    clock.now += 30
    ok, renewed = leases.acquire("p1", "codex#1", ttl=60)
    assert ok and renewed.acquired_at == first.acquired_at and renewed.expires_at > first.expires_at
    ok, current = leases.acquire("p1", "deepseek#2")
    assert not ok and current.holder == "codex#1"


def test_lease_expires_and_can_be_taken_by_someone_else():
    clock = Clock()
    leases = agent_lease.LeaseRegistry(clock)
    leases.acquire("p1", "a", ttl=60)
    clock.now += 61
    assert leases.get("p1") is None
    ok, lease = leases.acquire("p1", "b")
    assert ok and lease.holder == "b"


def test_human_takeover_locks_agents_out_until_handed_back():
    clock = Clock()
    leases = agent_lease.LeaseRegistry(clock)
    leases.acquire("p1", "codex#1")
    taken = leases.takeover("p1")
    assert taken.holder == agent_lease.HUMAN and taken.kind == "human"
    ok, current = leases.acquire("p1", "codex#1")
    assert not ok and current.kind == "human"
    assert leases.release("p1") is True  # the person hands it back
    ok, _ = leases.acquire("p1", "codex#1")
    assert ok


def test_release_by_wrong_holder_does_nothing():
    leases = agent_lease.LeaseRegistry(Clock())
    leases.acquire("p1", "a")
    assert leases.release("p1", "b") is False
    assert leases.release("p1", "a") is True
    assert leases.describe("p1") is None


def test_lease_ttl_is_clamped():
    clock = Clock()
    leases = agent_lease.LeaseRegistry(clock)
    _, lease = leases.acquire("p1", "a", ttl=10**9)
    assert lease.expires_at - clock.now == agent_lease.MAX_TTL_S


# ── agent_auth ───────────────────────────────────────────────────────────────


def test_clamp_mode():
    assert agent_auth.clamp_mode("automation", None) == "automation"
    assert agent_auth.clamp_mode("automation", "read") == "read-only"
    assert agent_auth.clamp_mode("automation", "control") == "full"
    assert agent_auth.clamp_mode("automation", "cdp") == "automation"
    assert agent_auth.clamp_mode("read-only", "cdp") == "read-only"  # never raises the mode
    assert agent_auth.clamp_mode("off", "cdp") == "off"
    assert agent_auth.clamp_mode("full", "bogus") == "off"  # unknown scope gets nothing


@pytest.mark.parametrize(
    "scope,method,path,allowed",
    [
        ("read", "GET", "/api/agent/tools", True),
        ("read", "POST", "/api/agent/tools/list_profiles", True),
        ("read", "GET", "/api/agent/guide", True),
        ("read", "POST", "/api/agent/mcp", True),
        ("read", "GET", "/api/profiles", False),  # raw profile data (cookies, proxy creds)
        ("read", "GET", "/api/profiles/p1/cookies/export", False),
        ("read", "POST", "/api/profiles/p1/launch", False),
        ("read", "GET", "/api/agent/tokens", False),
        ("read", "POST", "/api/agent/tokens", False),
        ("read", "WS", "/api/profiles/p1/cdp", False),
        ("control", "WS", "/api/profiles/p1/cdp", False),
        ("cdp", "WS", "/api/profiles/p1/cdp", True),
        ("cdp", "GET", "/api/profiles/p1/cdp/json/version", True),
        ("cdp", "WS", "/api/profiles/p1/cdp/devtools/page/ABC", True),
        ("cdp", "GET", "/api/profiles/p1/cookies/export", False),
        ("cdp", "GET", "/api/backups", False),
        ("cdp", "DELETE", "/api/agent/tokens/abc", False),
    ],
)
def test_agent_token_raw_rest_allowlist(scope, method, path, allowed):
    assert agent_auth.path_allowed(scope, method, path) is allowed


def test_token_store_create_verify_revoke():
    data: dict[str, str] = {}
    store = agent_auth.TokenStore(data.get, data.__setitem__)
    record, token = store.create("codex laptop", "control")
    assert token.startswith("cbm_control_")
    assert record["scope"] == "control"
    assert token not in json.dumps(data)  # only a digest is stored
    assert store.verify(token)["name"] == "codex laptop"
    assert store.verify(token + "x") is None
    assert store.verify("not-a-token") is None
    assert [t["id"] for t in store.list()] == [record["id"]]
    assert "sha256" not in store.list()[0]
    assert store.revoke(record["id"]) is True
    assert store.verify(token) is None
    assert store.revoke(record["id"]) is False


def test_token_store_validation():
    store = agent_auth.TokenStore({}.get, {}.__setitem__)
    with pytest.raises(ValueError):
        store.create("x", "admin")
    with pytest.raises(ValueError):
        store.create("  ", "read")


# ── PageController (against fake Playwright objects) ─────────────────────────


class FakeElement:
    def __init__(self, tag: str = "button") -> None:
        self.tag = tag
        self.clicked = False
        self.filled: str | None = None
        self.selected: str | None = None
        self.pressed: list[str] = []
        self.fail_with: Exception | None = None

    def as_element(self):
        return self

    async def scroll_into_view_if_needed(self, **kw):
        if self.fail_with:
            raise self.fail_with

    async def click(self, **kw):
        if self.fail_with:
            raise self.fail_with
        self.clicked = True

    async def fill(self, text, **kw):
        self.filled = text

    async def select_option(self, label=None, **kw):
        self.selected = label

    async def press(self, key, **kw):
        self.pressed.append(key)

    is_file = False
    uploaded: list | None = None

    async def evaluate(self, js):
        if "type === 'file'" in js:
            return self.is_file
        return self.tag

    async def set_input_files(self, files, **kw):
        self.uploaded = list(files)

    async def inner_text(self):  # strict like Playwright's ElementHandle.inner_text(): no timeout argument
        return self.text

    text = "element text"


class FakeValueHandle:
    def __init__(self, value) -> None:
        self.value = value

    async def json_value(self):
        return self.value

    async def get_properties(self):
        return {str(i): el for i, el in enumerate(self.value)}


class FakeSnapshotHandle:
    def __init__(self, lines, elements, frames=0, truncated=False, frame_elements=()) -> None:
        # Real snapshot lines for controls always start with their ref.
        if len(lines) == len(elements):
            lines = [l if l.startswith("[e") else f'[e{i}] button "{l}"' for i, l in enumerate(lines)]
        self.props = {
            "lines": FakeValueHandle(lines),
            "els": FakeValueHandle(elements),
            "frames": FakeValueHandle(frames),
            "truncated": FakeValueHandle(truncated),
            "frameEls": FakeValueHandle(list(frame_elements)),
        }
        self.disposed = False

    async def get_properties(self):
        return self.props

    async def dispose(self):
        self.disposed = True


class FakePage:
    def __init__(self, url="about:blank", title="") -> None:
        self.url = url
        self._title = title
        self._closed = False
        self.keyboard = MagicMock()
        self.keyboard.press = AsyncMock()
        self.mouse = MagicMock()
        self.mouse.wheel = AsyncMock()
        self.snapshot_handle = FakeSnapshotHandle([], [])
        self.goto_calls: list[str] = []
        self.handlers: dict[str, list] = {}
        self.main_frame = object()
        self.snapshot_args: list = []
        self.snapshot_errors: list[Exception] = []  # raised by evaluate_handle, one per call
        self.body_text = "body text"

    def on(self, event, callback):
        self.handlers.setdefault(event, []).append(callback)

    def emit(self, event, *args):
        for callback in self.handlers.get(event, []):
            callback(*args)

    async def evaluate(self, js, arg=None):
        self.text_args = getattr(self, "text_args", []) + [arg]
        return self.body_text

    def is_closed(self):
        return self._closed

    async def close(self):
        self._closed = True

    async def title(self):
        return self._title

    async def goto(self, url, **kw):
        self.goto_calls.append(url)
        self.url = url
        return MagicMock(status=200)

    async def evaluate_handle(self, js, arg=None):
        self.snapshot_args.append(arg)
        if self.snapshot_errors:
            raise self.snapshot_errors.pop(0)
        return self.snapshot_handle

    async def wait_for_load_state(self, *a, **kw):
        return None

    async def bring_to_front(self):
        return None

    async def screenshot(self, **kw):
        return b"\xff\xd8fakejpeg"

    async def go_back(self, **kw):
        self.url = "https://example.com/back"

    async def wait_for_timeout(self, ms):
        self.waited_ms = ms

    def expect_file_chooser(self, timeout=None):
        page = self

        class Chooser:
            async def set_files(self, files):
                page.chooser_files = list(files)

        class Manager:
            async def __aenter__(self_inner):
                async def value():
                    return Chooser()

                class Info:
                    pass

                info = Info()
                info.value = value()
                return info

            async def __aexit__(self_inner, *exc):
                return False

        return Manager()

    async def wait_for_url(self, pattern, timeout=None, wait_until=None):
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        if not pattern.search(self.url):
            raise PlaywrightTimeout(f"Timeout {timeout}ms exceeded waiting for {pattern.pattern}")


class FakeContext:
    def __init__(self) -> None:
        self.pages: list[FakePage] = []

    async def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page


def run_controller():
    return PageController(), FakeContext()


async def test_navigate_only_allows_http_and_about_blank():
    pages, ctx = run_controller()
    result = await pages.navigate(ctx, "p1", "https://example.com/x")
    assert result["url"] == "https://example.com/x" and result["status"] == 200
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "chrome://settings", "data:text/html,hi", "example.com", ""):
        with pytest.raises(PageControlError) as err:
            await pages.navigate(ctx, "p1", bad)
        assert err.value.reason == "invalid_argument", bad


async def test_snapshot_hands_out_refs_and_click_uses_them():
    pages, ctx = run_controller()
    page = await ctx.new_page()
    button = FakeElement()
    page.snapshot_handle = FakeSnapshotHandle(['[e0] button "Go"'], [button])
    snap = await pages.snapshot(ctx, "p1")
    assert snap["elements"] == 1 and '[e0] button "Go"' in snap["snapshot"]
    result = await pages.click(ctx, "p1", "e0")
    assert button.clicked and result["new_tab"] is False


async def test_refs_are_invalid_before_a_snapshot_and_after_the_next_one():
    pages, ctx = run_controller()
    page = await ctx.new_page()
    with pytest.raises(PageControlError) as err:
        await pages.click(ctx, "p1", "e0")
    assert err.value.reason == "unknown_ref"
    page.snapshot_handle = FakeSnapshotHandle(["x"], [FakeElement()])
    first_handle = page.snapshot_handle
    await pages.snapshot(ctx, "p1")
    page.snapshot_handle = FakeSnapshotHandle([], [])
    await pages.snapshot(ctx, "p1")
    assert first_handle.disposed is True
    with pytest.raises(PageControlError) as err:
        await pages.click(ctx, "p1", "e0")
    assert err.value.reason == "unknown_ref"


async def test_detached_element_maps_to_stale_ref():
    from playwright.async_api import Error as PlaywrightError

    pages, ctx = run_controller()
    page = await ctx.new_page()
    element = FakeElement()
    element.fail_with = PlaywrightError("Element is not attached to the DOM")
    page.snapshot_handle = FakeSnapshotHandle(["x"], [element])
    await pages.snapshot(ctx, "p1")
    with pytest.raises(PageControlError) as err:
        await pages.click(ctx, "p1", "e0")
    assert err.value.reason == "stale_ref"


async def test_click_that_opens_a_tab_switches_to_it():
    pages, ctx = run_controller()
    page = await ctx.new_page()
    link = FakeElement()
    page.snapshot_handle = FakeSnapshotHandle(["x"], [link])
    await pages.snapshot(ctx, "p1")

    async def click_opens_tab(**kw):
        ctx.pages.append(FakePage("https://example.com/new", "New"))

    link.click = click_opens_tab
    result = await pages.click(ctx, "p1", "e0")
    assert result["new_tab"] is True and result["url"] == "https://example.com/new"


async def test_type_fills_inputs_and_selects_options():
    pages, ctx = run_controller()
    page = await ctx.new_page()
    box, dropdown = FakeElement("input"), FakeElement("select")
    page.snapshot_handle = FakeSnapshotHandle(["a", "b"], [box, dropdown])
    await pages.snapshot(ctx, "p1")
    await pages.type_text(ctx, "p1", "e0", "hello", submit=True)
    assert box.filled == "hello" and box.pressed == ["Enter"]
    await pages.type_text(ctx, "p1", "e1", "Canada")
    assert dropdown.selected == "Canada" and dropdown.filled is None


async def test_screenshot_returns_base64_and_scroll_validates():
    pages, ctx = run_controller()
    page = await ctx.new_page()
    shot = await pages.screenshot(ctx, "p1")
    assert shot["image"]["mime"] == "image/jpeg" and shot["image"]["bytes"] == len(b"\xff\xd8fakejpeg")
    await pages.scroll(ctx, "p1", "down", 300)
    page.mouse.wheel.assert_awaited_with(0, 300)
    with pytest.raises(PageControlError):
        await pages.scroll(ctx, "p1", "sideways")
    with pytest.raises(PageControlError):
        await pages.screenshot(ctx, "p1", fmt="gif")


async def test_tabs_list_new_select_close():
    pages, ctx = run_controller()
    first = await ctx.new_page()
    first.url, first._title = "https://a.example/", "A"
    opened = await pages.tabs(ctx, "p1", "new", url="https://b.example/")
    assert opened["tab"] == 1
    listing = await pages.tabs(ctx, "p1", "list")
    assert [t["current"] for t in listing["tabs"]] == [False, True]
    await pages.tabs(ctx, "p1", "select", index=0)
    assert (await pages.tabs(ctx, "p1", "list"))["tabs"][0]["current"] is True
    closed = await pages.tabs(ctx, "p1", "close", index=1)
    assert closed["remaining"] == 1
    with pytest.raises(PageControlError):
        await pages.tabs(ctx, "p1", "select", index=9)
    with pytest.raises(PageControlError):
        await pages.tabs(ctx, "p1", "explode")


async def test_wait_for_needs_text_or_ms():
    pages, ctx = run_controller()
    await ctx.new_page()
    with pytest.raises(PageControlError) as err:
        await pages.wait_for(ctx, "p1")
    assert err.value.reason == "invalid_argument"
    await pages.wait_for(ctx, "p1", ms=10)


async def test_press_key_requires_a_key():
    pages, ctx = run_controller()
    await ctx.new_page()
    with pytest.raises(PageControlError):
        await pages.press_key(ctx, "p1", "  ")


# ── HTTP: leases, page endpoint, tool API, tokens, HTTP MCP ──────────────────


@pytest.fixture()
def profile(app_client):
    resp = app_client.post("/api/profiles", json={"name": "Agent Test"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def set_mode(client: TestClient, mode: str, **kw) -> None:
    assert client.put("/api/settings/mcp", json={"mode": mode}, **kw).status_code == 200


def test_lease_endpoints_and_takeover(app_client, profile):
    assert app_client.get(f"/api/profiles/{profile}/lease").json() == {"lease": None}
    resp = app_client.post(f"/api/profiles/{profile}/lease", json={"holder": "codex#1"})
    assert resp.status_code == 200 and resp.json()["lease"]["holder"] == "codex#1"
    clash = app_client.post(f"/api/profiles/{profile}/lease", json={"holder": "other#2"})
    assert clash.status_code == 409
    assert "[profile_leased]" in clash.json()["detail"] and clash.json()["lease"]["holder"] == "codex#1"

    taken = app_client.post(f"/api/profiles/{profile}/lease/takeover", json={"ttl_seconds": 120})
    assert taken.status_code == 200
    assert taken.json()["lease"]["kind"] == "human"
    assert app_client.post(f"/api/profiles/{profile}/lease", json={"holder": "codex#1"}).status_code == 409

    assert app_client.delete(f"/api/profiles/{profile}/lease").json() == {"released": True}
    assert app_client.post(f"/api/profiles/{profile}/lease", json={"holder": "codex#1"}).status_code == 200
    assert app_client.get("/api/profiles/missing/lease").status_code == 404


def test_takeover_closes_live_cdp_connections(app_client, profile):
    from backend import main

    class FakeSocket:
        closed_with = None

        async def close(self, code, reason):
            self.closed_with = (code, reason)

    socket = FakeSocket()
    main.agent_cdp.add(profile, socket)
    try:
        body = app_client.post(f"/api/profiles/{profile}/lease/takeover").json()
        assert body["cdp_connections_closed"] == 1
        assert socket.closed_with[0] == 4010
    finally:
        main.agent_cdp.remove(profile, socket)


def test_status_and_profile_list_show_the_lease_only_while_running(app_client, profile, monkeypatch):
    from backend import main

    app_client.post(f"/api/profiles/{profile}/lease", json={"holder": "codex#1"})
    assert app_client.get(f"/api/profiles/{profile}/status").json()["agent_lease"] is None  # not running
    running = MagicMock(cdp_port=9222, context=MagicMock(), ws_port=None, display=None, browser_engine="cloak",
                        launch_mode="debug", proxy_geo=None)
    monkeypatch.setitem(main.browser_mgr.running, profile, running)
    assert app_client.get(f"/api/profiles/{profile}/status").json()["agent_lease"]["holder"] == "codex#1"
    listed = {p["id"]: p for p in app_client.get("/api/profiles").json()}
    assert listed[profile]["agent_lease"]["holder"] == "codex#1"


def test_stopping_a_profile_drops_its_lease(app_client, profile, monkeypatch):
    from backend import main

    monkeypatch.setitem(main.browser_mgr.running, profile, MagicMock())
    monkeypatch.setattr(main.browser_mgr, "stop", AsyncMock())
    app_client.post(f"/api/profiles/{profile}/lease", json={"holder": "codex#1"})
    assert app_client.post(f"/api/profiles/{profile}/stop").status_code == 200
    assert app_client.get(f"/api/profiles/{profile}/lease").json() == {"lease": None}


def test_page_endpoint_error_states(app_client, profile, monkeypatch):
    from backend import main

    resp = app_client.post(f"/api/profiles/{profile}/page/snapshot")
    assert resp.status_code == 404 and resp.json()["reason"] == "not_running"
    manual = MagicMock(cdp_port=None, context=None)
    monkeypatch.setitem(main.browser_mgr.running, profile, manual)
    resp = app_client.post(f"/api/profiles/{profile}/page/snapshot")
    assert resp.status_code == 409 and resp.json()["reason"] == "cdp_unavailable"
    debug = MagicMock(cdp_port=9222, context=FakeContext())
    monkeypatch.setitem(main.browser_mgr.running, profile, debug)
    resp = app_client.post(f"/api/profiles/{profile}/page/navigate", json={"url": "file:///etc/passwd"})
    assert resp.status_code == 400 and resp.json()["reason"] == "invalid_argument"
    assert app_client.post(f"/api/profiles/{profile}/page/nonsense").status_code == 404


def test_page_endpoint_drives_the_context(app_client, profile, monkeypatch):
    from backend import main

    ctx = FakeContext()
    monkeypatch.setitem(main.browser_mgr.running, profile, MagicMock(cdp_port=9222, context=ctx))
    resp = app_client.post(f"/api/profiles/{profile}/page/navigate", json={"url": "https://example.com/"})
    assert resp.status_code == 200 and resp.json()["url"] == "https://example.com/"
    tabs = app_client.post(f"/api/profiles/{profile}/page/tabs", json={"action": "list"}).json()
    assert tabs["tabs"][0]["url"] == "https://example.com/"


def test_tool_api_lists_and_runs_tools_under_the_configured_mode(app_client, profile):
    listing = app_client.get("/api/agent/tools").json()
    assert listing["mode"] == "read-only"
    names = [t["name"] for t in listing["tools"]]
    assert "list_profiles" in names and "launch_profile" not in names
    openai = app_client.get("/api/agent/tools?format=openai").json()["tools"]
    assert openai[0]["type"] == "function"
    assert app_client.get("/api/agent/tools?format=xml").status_code == 422

    result = app_client.post("/api/agent/tools/list_profiles", json={}).json()
    assert result["ok"] is True and any(p["id"] == profile for p in result["profiles"])
    denied = app_client.post("/api/agent/tools/launch_profile", json={"arguments": {"profile_id": profile}}).json()
    assert denied["reason"] == "mode_read_only"
    unknown = app_client.post("/api/agent/tools/delete_everything", json={})
    assert unknown.status_code == 404 and unknown.json()["reason"] == "unknown_tool"

    set_mode(app_client, "automation")
    names = [t["name"] for t in app_client.get("/api/agent/tools").json()["tools"]]
    assert "open_browser" in names and "browser_click" in names


def test_tool_api_applies_the_field_policy(app_client, monkeypatch):
    from backend import database as db

    created = db.create_profile(name="Secret", fingerprint_seed=1, proxy="socks5://user:hunter2@10.0.0.9:1080", notes="NOTE_SECRET")
    body = app_client.post("/api/agent/tools/get_profile", json={"arguments": {"profile_id": created["id"]}}).text
    assert "hunter2" not in body and "NOTE_SECRET" not in body
    assert "10.0.0.9:1080" in body


def test_tool_api_is_audited_with_the_client_name(app_client, profile):
    app_client.post(
        "/api/agent/tools/manager_status",
        json={"arguments": {}, "client": {"name": "deepseek-harness", "version": "0.3"}},
    )
    audits = app_client.get("/api/mcp/audit").json()
    assert any(a["tool"] == "manager_status" and a["client_name"] == "deepseek-harness" for a in audits)


def test_agent_guide_is_served(app_client):
    text = app_client.get("/api/agent/guide").text
    assert "CloakBrowser" in text and "open_browser" in text


@pytest.fixture()
def auth_client(tmp_db, monkeypatch):
    from backend import main

    monkeypatch.setattr(main, "AUTH_TOKEN", "admin-secret")
    monkeypatch.setattr(main.browser_mgr.vnc, "validate_available", MagicMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
    monkeypatch.setattr(main.browser_mgr.vnc, "cleanup_stale", AsyncMock())
    with TestClient(main.app, base_url="http://127.0.0.1:8080") as client:
        yield client


ADMIN = {"Authorization": "Bearer admin-secret"}


def mint(client: TestClient, scope: str, name: str = "t") -> dict:
    resp = client.post("/api/agent/tokens", json={"name": name, "scope": scope}, headers=ADMIN)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_token_management_is_admin_only(auth_client):
    assert auth_client.get("/api/agent/tokens").status_code == 401
    made = mint(auth_client, "read", "laptop")
    assert made["token"].startswith("cbm_read_") and made["enforced"] is True
    listing = auth_client.get("/api/agent/tokens", headers=ADMIN).json()
    assert [t["name"] for t in listing["tokens"]] == ["laptop"]
    assert made["token"] not in json.dumps(listing)
    agent = {"Authorization": f"Bearer {made['token']}"}
    assert auth_client.get("/api/agent/tokens", headers=agent).status_code == 403
    assert auth_client.post("/api/agent/tokens", json={"name": "x", "scope": "cdp"}, headers=agent).status_code == 403
    assert auth_client.post("/api/agent/tokens", json={"name": "x", "scope": "root"}, headers=ADMIN).status_code == 400


def test_read_token_sees_only_the_shaped_tool_api(auth_client):
    token = mint(auth_client, "read")["token"]
    agent = {"Authorization": f"Bearer {token}"}
    assert auth_client.get("/api/agent/tools", headers=agent).status_code == 200
    ok = auth_client.post("/api/agent/tools/list_profiles", json={}, headers=agent)
    assert ok.status_code == 200 and ok.json()["ok"] is True
    # Raw REST (where cookies and proxy credentials live) is closed to it.
    for path in ("/api/profiles", "/api/backups", "/api/settings/llm"):
        assert auth_client.get(path, headers=agent).status_code == 403, path
    assert auth_client.post("/api/profiles/x/launch", headers=agent).status_code == 403
    # Without any token the same endpoints are 401, not 403.
    assert auth_client.get("/api/profiles").status_code == 401


def test_token_scope_caps_the_tools_even_when_the_manager_mode_is_automation(auth_client):
    set_mode(auth_client, "automation", headers=ADMIN)
    read = {"Authorization": f"Bearer {mint(auth_client, 'read')['token']}"}
    control = {"Authorization": f"Bearer {mint(auth_client, 'control')['token']}"}
    cdp = {"Authorization": f"Bearer {mint(auth_client, 'cdp')['token']}"}

    def tools(headers):
        return {t["name"] for t in auth_client.get("/api/agent/tools", headers=headers).json()["tools"]}

    assert "launch_profile" not in tools(read)
    assert "launch_profile" in tools(control) and "open_browser" not in tools(control)
    assert "open_browser" in tools(cdp)
    denied = auth_client.post("/api/agent/tools/launch_profile", json={"arguments": {"profile_id": "x"}}, headers=read)
    assert denied.json()["reason"] == "scope_denied"
    denied = auth_client.post("/api/agent/tools/open_browser", json={"arguments": {"profile": "x"}}, headers=control)
    assert denied.json()["reason"] == "scope_denied"


def test_revoked_token_stops_working(auth_client):
    made = mint(auth_client, "control")
    agent = {"Authorization": f"Bearer {made['token']}"}
    assert auth_client.get("/api/agent/tools", headers=agent).status_code == 200
    assert auth_client.delete(f"/api/agent/tokens/{made['record']['id']}", headers=ADMIN).status_code == 200
    assert auth_client.get("/api/agent/tools", headers=agent).status_code == 401
    assert auth_client.delete("/api/agent/tokens/nope", headers=ADMIN).status_code == 404


def test_only_cdp_scope_may_use_the_cdp_proxy_http_routes(auth_client):
    from backend import database as db

    pid = db.create_profile(name="C", fingerprint_seed=1)["id"]
    read = {"Authorization": f"Bearer {mint(auth_client, 'read')['token']}"}
    control = {"Authorization": f"Bearer {mint(auth_client, 'control')['token']}"}
    cdp = {"Authorization": f"Bearer {mint(auth_client, 'cdp')['token']}"}
    path = f"/api/profiles/{pid}/cdp/json/version"
    assert auth_client.get(path, headers=read).status_code == 403
    assert auth_client.get(path, headers=control).status_code == 403
    # cdp scope gets past auth; the profile simply is not running.
    assert auth_client.get(path, headers=cdp).status_code == 404


def test_agent_tool_calls_work_with_password_only_auth(tmp_db, monkeypatch):
    """The in-process runner must not depend on AUTH_TOKEN being set."""
    from backend import database as db
    from backend import main

    monkeypatch.setattr(main, "AUTH_TOKEN", None)
    db.set_setting("auth.username", "admin")
    db.set_setting("auth.password_hash", main._hash_password("correct-password"))
    monkeypatch.setattr(main.browser_mgr.vnc, "validate_available", MagicMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
    monkeypatch.setattr(main.browser_mgr.vnc, "cleanup_stale", AsyncMock())
    with TestClient(main.app, base_url="http://127.0.0.1:8080") as client:
        login = client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})
        assert login.status_code == 200
        record = client.post("/api/agent/tokens", json={"name": "a", "scope": "read"}).json()
        # AUTH_TOKEN is unset, yet the agent token authenticates and the tool runs.
        fresh = TestClient(main.app, base_url="http://127.0.0.1:8080")
        resp = fresh.post(
            "/api/agent/tools/manager_status", json={}, headers={"Authorization": f"Bearer {record['token']}"}
        )
        assert resp.status_code == 200 and resp.json()["ok"] is True, resp.text


MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def mcp_rpc(client: TestClient, method: str, params: dict | None = None, *, rpc_id: int = 1, headers=None):
    payload = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}}
    return client.post("/api/agent/mcp", json=payload, headers={**MCP_HEADERS, **(headers or {})})


def test_http_mcp_endpoint_lists_and_calls_tools(app_client, profile):
    init = mcp_rpc(
        app_client,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "codex", "version": "1"}},
    )
    assert init.status_code == 200, init.text
    result = init.json()["result"]
    assert result["serverInfo"]["name"] == "cloakbrowser-manager"
    assert "open_browser" in result["instructions"]

    listed = mcp_rpc(app_client, "tools/list", rpc_id=2).json()["result"]["tools"]
    assert "list_profiles" in [t["name"] for t in listed]
    assert "launch_profile" not in [t["name"] for t in listed]  # read-only by default

    call = mcp_rpc(app_client, "tools/call", {"name": "list_profiles", "arguments": {}}, rpc_id=3).json()
    payload = json.loads(call["result"]["content"][0]["text"])
    assert payload["ok"] is True and any(p["id"] == profile for p in payload["profiles"])


def test_http_mcp_respects_the_token_scope(auth_client):
    set_mode(auth_client, "automation", headers=ADMIN)
    read = {"Authorization": f"Bearer {mint(auth_client, 'read')['token']}"}
    cdp = {"Authorization": f"Bearer {mint(auth_client, 'cdp')['token']}"}
    assert mcp_rpc(auth_client, "tools/list").status_code == 401
    narrow = mcp_rpc(auth_client, "tools/list", headers=read).json()["result"]["tools"]
    wide = mcp_rpc(auth_client, "tools/list", headers=cdp).json()["result"]["tools"]
    assert "open_browser" not in [t["name"] for t in narrow]
    assert "open_browser" in [t["name"] for t in wide]
    blocked = mcp_rpc(
        auth_client, "tools/call", {"name": "launch_profile", "arguments": {"profile_id": "x"}}, headers=read
    ).json()
    assert json.loads(blocked["result"]["content"][0]["text"])["reason"] == "scope_denied"


def test_http_mcp_serves_the_guide_resource_and_task_prompts(app_client):
    listed = mcp_rpc(app_client, "resources/list").json()["result"]["resources"]
    assert [r["uri"] for r in listed] == ["cloakbrowser://guide"]
    read = mcp_rpc(app_client, "resources/read", {"uri": "cloakbrowser://guide"}, rpc_id=2).json()
    assert "open_browser" in read["result"]["contents"][0]["text"]

    prompts = mcp_rpc(app_client, "prompts/list", rpc_id=3).json()["result"]["prompts"]
    assert {p["name"] for p in prompts} == {"operate_profile", "check_fingerprint"}
    got = mcp_rpc(
        app_client, "prompts/get",
        {"name": "operate_profile", "arguments": {"profile": "店铺A", "task": "查看订单"}}, rpc_id=4,
    ).json()["result"]
    text = got["messages"][0]["content"]["text"]
    assert "店铺A" in text and "查看订单" in text and "open_browser" in text
    missing = mcp_rpc(app_client, "prompts/get", {"name": "operate_profile", "arguments": {}}, rpc_id=5).json()
    assert "error" in missing


def _ws_close_code(client: TestClient, path: str, headers: dict | None = None) -> int:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as err:
        # The request guard only accepts loopback Host names (TestClient's default is "testserver").
        with client.websocket_connect(path, headers={"Host": "127.0.0.1:8080", **(headers or {})}):
            pass
    return err.value.code


def test_cdp_websocket_auth_per_token_scope(auth_client):
    """No token -> 4401, read/control token -> 4403, cdp token reaches the route
    (which then says the profile is not running, 4004), admin does too."""
    from backend import database as db

    pid = db.create_profile(name="WS", fingerprint_seed=2)["id"]
    read = {"Authorization": f"Bearer {mint(auth_client, 'read')['token']}"}
    control = {"Authorization": f"Bearer {mint(auth_client, 'control')['token']}"}
    cdp = {"Authorization": f"Bearer {mint(auth_client, 'cdp')['token']}"}
    for path in (f"/api/profiles/{pid}/cdp", f"/api/profiles/{pid}/cdp/devtools/page/ABC"):
        assert _ws_close_code(auth_client, path) == 4401, path
        assert _ws_close_code(auth_client, path, read) == 4403, path
        assert _ws_close_code(auth_client, path, control) == 4403, path
        assert _ws_close_code(auth_client, path, cdp) == 4004, path
        assert _ws_close_code(auth_client, path, ADMIN) == 4004, path


def test_revoked_cdp_token_is_refused_on_the_websocket(auth_client):
    from backend import database as db

    pid = db.create_profile(name="WS2", fingerprint_seed=3)["id"]
    made = mint(auth_client, "cdp")
    headers = {"Authorization": f"Bearer {made['token']}"}
    assert _ws_close_code(auth_client, f"/api/profiles/{pid}/cdp", headers) == 4004
    auth_client.delete(f"/api/agent/tokens/{made['record']['id']}", headers=ADMIN)
    assert _ws_close_code(auth_client, f"/api/profiles/{pid}/cdp", headers) == 4401


# ── navigation settling, snapshot retry/clipping, get_text ───────────────────


class FakeNavRequest:
    def __init__(self, page: "FakePage", navigation: bool = True) -> None:
        self.frame = page.main_frame
        self._navigation = navigation

    def is_navigation_request(self) -> bool:
        return self._navigation


async def test_click_waits_for_the_navigation_it_started():
    pages, ctx = run_controller()
    page = await ctx.new_page()
    link = FakeElement()
    page.snapshot_handle = FakeSnapshotHandle(["x"], [link])
    await pages.snapshot(ctx, "p1")

    async def click_starts_navigation(**kw):
        page.emit("request", FakeNavRequest(page))  # the click begins a page load...

        async def finish_later():
            await asyncio.sleep(0.6)
            page.url, page._title = "https://example.com/next", "Next"
            page.emit("domcontentloaded")  # ...which finishes after the 0.3 s grace period

        asyncio.create_task(finish_later())

    link.click = click_starts_navigation
    result = await pages.click(ctx, "p1", "e0")
    assert result["url"] == "https://example.com/next" and result["title"] == "Next"


async def test_non_navigation_requests_do_not_hold_up_actions():
    pages, ctx = run_controller()
    page = await ctx.new_page()
    box = FakeElement("input")
    page.snapshot_handle = FakeSnapshotHandle(["x"], [box])
    await pages.snapshot(ctx, "p1")
    page.emit("request", FakeNavRequest(page, navigation=False))
    await pages.type_text(ctx, "p1", "e0", "hi")
    assert pages._state("p1").nav_pending is False


async def test_snapshot_waits_for_a_pending_navigation_and_retries_a_destroyed_context():
    from playwright.async_api import Error as PlaywrightError

    pages, ctx = run_controller()
    page = await ctx.new_page()
    page.snapshot_handle = FakeSnapshotHandle(['[e0] button "Go"'], [FakeElement()])
    page.snapshot_errors = [PlaywrightError("Page.evaluate_handle: Execution context was destroyed, most likely because of a navigation")]
    snap = await pages.snapshot(ctx, "p1")
    assert snap["elements"] == 1 and len(page.snapshot_args) == 2  # failed once, retried

    page.emit("request", FakeNavRequest(page))

    async def loaded():
        await asyncio.sleep(0.3)
        page.emit("domcontentloaded")

    asyncio.create_task(loaded())
    started = asyncio.get_running_loop().time()
    await pages.snapshot(ctx, "p1")
    assert asyncio.get_running_loop().time() - started >= 0.25  # it waited for the load


async def test_a_page_that_keeps_navigating_reports_page_navigating_not_stale_ref():
    from playwright.async_api import Error as PlaywrightError

    pages, ctx = run_controller()
    page = await ctx.new_page()
    page.snapshot_errors = [PlaywrightError("Execution context was destroyed, most likely because of a navigation")] * 3
    with pytest.raises(PageControlError) as err:
        await pages.snapshot(ctx, "p1")
    assert err.value.reason == "page_navigating"


async def test_snapshot_clips_on_a_line_boundary_and_says_what_is_missing():
    from backend import page_control

    pages, ctx = run_controller()
    page = await ctx.new_page()
    lines = [f'[e{i}] link "item {i}" href=/p/{i}' + "x" * 200 for i in range(200)]
    page.snapshot_handle = FakeSnapshotHandle(lines, [FakeElement() for _ in range(200)])
    snap = await pages.snapshot(ctx, "p1")
    body = snap["snapshot"].split("\n")
    assert snap["truncated"] is True
    assert body[-1].startswith("…") and "viewport_only" in body[-1] and "browser_get_text" in body[-1]
    shown = body[:-1]
    assert all(line.startswith("[e") and line.endswith("x") for line in shown)  # no cut-off lines
    assert len("\n".join(shown)) <= page_control.MAX_TEXT_LEN
    # Only the refs that were actually shown can be clicked.
    assert snap["elements"] == len(shown) and f"e{len(shown)}" not in pages._state("p1").refs


async def test_snapshot_viewport_only_is_passed_to_the_page():
    pages, ctx = run_controller()
    page = await ctx.new_page()
    await pages.snapshot(ctx, "p1", viewport_only=True)
    assert page.snapshot_args[-1][2] is True
    snap = await pages.snapshot(ctx, "p1")
    assert page.snapshot_args[-1][2] is False and snap["viewport_only"] is False


async def test_get_text_pages_through_long_text_and_reads_elements():
    pages, ctx = run_controller()
    page = await ctx.new_page()
    page.body_text = "abcdefghij" * 300  # 3000 chars
    first = await pages.get_text(ctx, "p1", max_chars=1000)
    assert first["total_chars"] == 3000 and len(first["text"]) == 1000 and first["next_offset"] == 1000
    last = await pages.get_text(ctx, "p1", offset=2000, max_chars=5000)
    assert len(last["text"]) == 1000 and last["next_offset"] is None
    page.snapshot_handle = FakeSnapshotHandle(["x"], [FakeElement()])
    await pages.snapshot(ctx, "p1")
    assert (await pages.get_text(ctx, "p1", ref="e0"))["text"] == "element text"
    with pytest.raises(PageControlError):
        await pages.get_text(ctx, "p1", ref="e9")


async def test_get_text_reads_main_content_unless_the_whole_page_is_asked_for():
    pages, ctx = run_controller()
    page = await ctx.new_page()
    await pages.get_text(ctx, "p1")
    await pages.get_text(ctx, "p1", whole_page=True)
    assert page.text_args == [False, True]


class FakeFrame:
    def __init__(self, handle, url="https://auth.example.net/login") -> None:
        self._handle = handle
        self.url = url
        self.args: list = []

    async def evaluate_handle(self, js, arg=None):
        self.args.append(arg)
        return self._handle


class FakeFrameElement(FakeElement):
    def __init__(self, frame: FakeFrame | None) -> None:
        super().__init__("iframe")
        self.frame = frame

    async def content_frame(self):
        return self.frame


async def test_snapshot_reads_visible_iframes_and_numbers_refs_across_frames():
    pages, ctx = run_controller()
    page = await ctx.new_page()
    outer_button = FakeElement()
    inner_box, inner_button = FakeElement("input"), FakeElement()
    frame = FakeFrame(
        FakeSnapshotHandle(['[e1] textbox "Email"', '[e2] button "Sign in"'], [inner_box, inner_button])
    )
    page.snapshot_handle = FakeSnapshotHandle(
        ['[e0] button "Open"', 'iframe "login" src=https://auth.example.net/login (内容见下方 iframe 段)'],
        [outer_button],
        frame_elements=[FakeFrameElement(frame)],
    )
    snap = await pages.snapshot(ctx, "p1")
    assert "--- iframe https://auth.example.net/login ---" in snap["snapshot"]
    assert '[e2] button "Sign in"' in snap["snapshot"] and snap["elements"] == 3
    assert frame.args == [[400 - 1, 250, False, 1]]  # the frame continues numbering at e1
    await pages.type_text(ctx, "p1", "e1", "me@example.com")
    assert inner_box.filled == "me@example.com"
    await pages.click(ctx, "p1", "e2")
    assert inner_button.clicked


async def test_an_iframe_that_cannot_be_read_is_reported_not_fatal():
    from playwright.async_api import Error as PlaywrightError

    pages, ctx = run_controller()
    page = await ctx.new_page()

    class BrokenFrameElement(FakeFrameElement):
        async def content_frame(self):
            raise PlaywrightError("frame detached")

    page.snapshot_handle = FakeSnapshotHandle(
        ['[e0] button "Open"'], [FakeElement()], frame_elements=[BrokenFrameElement(None)]
    )
    snap = await pages.snapshot(ctx, "p1")
    assert snap["ok"] if "ok" in snap else True
    assert "iframe 内容读取失败" in snap["snapshot"] and snap["elements"] == 1


async def test_refs_go_stale_the_moment_a_new_document_loads():
    """No 10 s click timeout on an element of the previous page: it fails fast and says why."""
    pages, ctx = run_controller()
    page = await ctx.new_page()
    page.snapshot_handle = FakeSnapshotHandle(["x"], [FakeElement()])
    await pages.snapshot(ctx, "p1")
    page.emit("domcontentloaded")  # the page navigated to a new document
    with pytest.raises(PageControlError) as err:
        await pages.click(ctx, "p1", "e0")
    assert err.value.reason == "stale_ref" and "上一个页面" in err.value.detail
    await pages.snapshot(ctx, "p1")  # a fresh snapshot makes refs usable again
    await pages.click(ctx, "p1", "e0")


# ── semantic selectors ───────────────────────────────────────────────────────


class FakeLocator:
    def __init__(self, matches: list, label: str = "") -> None:
        self.matches = matches
        self.label = label

    def filter(self, **kw):
        self.filtered = kw
        return self

    async def wait_for(self, state="visible", timeout=None):
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        self.waited = (state, timeout)
        if (state == "visible" and not self.matches) or (state == "hidden" and self.matches):
            raise PlaywrightTimeout(f"Timeout {timeout}ms exceeded")

    async def count(self):
        return len(self.matches)

    async def element_handle(self, **kw):
        return self.matches[0]

    @property
    def first(self):
        return self


class SelectorPage(FakePage):
    """A page whose locators answer from a table: {"text:Sign in": [element], ...}."""

    def __init__(self) -> None:
        super().__init__()
        self.table: dict[str, list] = {}
        self.calls: list[tuple] = []

    def _loc(self, kind, value, **kw):
        self.calls.append((kind, value, kw))
        return FakeLocator(self.table.get(f"{kind}:{value}", []))

    def get_by_text(self, value, exact=False):
        return self._loc("text", value, exact=exact)

    def get_by_role(self, role, name=None):
        return self._loc("role", f"{role}|{name}")

    def get_by_label(self, value):
        return self._loc("label", value)

    def get_by_placeholder(self, value):
        return self._loc("placeholder", value)

    def locator(self, css):
        return self._loc("css", css)


async def selector_controller():
    pages = PageController()
    ctx = FakeContext()
    page = SelectorPage()
    ctx.pages.append(page)
    return pages, ctx, page


async def test_semantic_selectors_resolve_to_one_visible_element():
    pages, ctx, page = await selector_controller()
    button, box = FakeElement(), FakeElement("input")
    page.table = {
        "text:Sign in": [button],
        "role:button|Sign in": [button],
        "label:Email": [box],
        "placeholder:you@example.com": [box],
        "css:#go": [button],
    }
    for selector in ("text=Sign in", 'role=button[name="Sign in"]', "role=button[name='Sign in']", "css=#go"):
        button.clicked = False
        await pages.click(ctx, "p1", selector)
        assert button.clicked, selector
    await pages.type_text(ctx, "p1", "label=Email", "a@b.com")
    await pages.type_text(ctx, "p1", "placeholder=you@example.com", "c@d.com")
    assert box.filled == "c@d.com"
    # quoted text is an exact match
    page.table["text:Sign in"] = [button]
    await pages.click(ctx, "p1", 'text="Sign in"')
    assert ("text", "Sign in", {"exact": True}) in page.calls


async def test_selector_that_matches_nothing_or_many_fails_loudly():
    pages, ctx, page = await selector_controller()
    page.table = {"text:Buy": [FakeElement(), FakeElement(), FakeElement()]}
    with pytest.raises(PageControlError) as err:
        await pages.click(ctx, "p1", "text=Missing")
    assert err.value.reason == "selector_not_found"
    with pytest.raises(PageControlError) as err:
        await pages.click(ctx, "p1", "text=Buy")
    assert err.value.reason == "ambiguous_selector" and "3" in err.value.detail


async def test_malformed_selectors_are_invalid_arguments():
    pages, ctx, page = await selector_controller()
    for bad in ("Sign in", "xpath=//a", "text=", "role=", "role=bu tton[name=x]"):
        with pytest.raises(PageControlError) as err:
            await pages.click(ctx, "p1", bad)
        assert err.value.reason in ("invalid_argument", "unknown_ref"), bad


async def test_selectors_survive_a_navigation_that_kills_refs():
    pages, ctx, page = await selector_controller()
    button = FakeElement()
    page.table = {"role:button|Next": [button]}
    page.snapshot_handle = FakeSnapshotHandle(["x"], [FakeElement()])
    await pages.snapshot(ctx, "p1")
    page.emit("domcontentloaded")  # new document: e0 is dead...
    with pytest.raises(PageControlError) as err:
        await pages.click(ctx, "p1", "e0")
    assert err.value.reason == "stale_ref"
    await pages.click(ctx, "p1", 'role=button[name="Next"]')  # ...but a selector still works
    assert button.clicked


async def test_get_text_accepts_a_selector():
    pages, ctx, page = await selector_controller()
    el = FakeElement()
    el.text = "price: 10"
    page.table = {"css:.price": [el]}
    assert (await pages.get_text(ctx, "p1", ref="css=.price"))["text"] == "price: 10"


# ── condition waits ──────────────────────────────────────────────────────────


async def test_wait_for_each_condition_kind():
    pages, ctx, page = await selector_controller()
    page.url = "https://shop.example.com/checkout/done"
    page.table = {"text:Thanks": [FakeElement()], "role:button|Continue": [FakeElement()]}
    info = await pages.wait_for(
        ctx, "p1", text="Thanks", text_gone="Loading…", url="/checkout/done",
        selector='role=button[name="Continue"]', ms=5, timeout_ms=2000,
    )
    assert info["url"].endswith("/done") and page.waited_ms == 5


async def test_wait_for_times_out_naming_the_condition():
    pages, ctx, page = await selector_controller()
    page.url = "https://shop.example.com/cart"
    page.table = {"text:Spinner": [FakeElement()]}
    for kwargs, needle in (
        ({"text": "Never"}, "Never"),
        ({"text_gone": "Spinner"}, "Spinner"),
        ({"url": "/checkout"}, "/checkout"),
        ({"selector": "css=#missing"}, "#missing"),
    ):
        with pytest.raises(PageControlError) as err:
            await pages.wait_for(ctx, "p1", timeout_ms=150, **kwargs)
        assert err.value.reason == "timeout" and needle in err.value.detail, kwargs


async def test_wait_for_validates_its_arguments():
    pages, ctx, page = await selector_controller()
    with pytest.raises(PageControlError) as err:
        await pages.wait_for(ctx, "p1")
    assert err.value.reason == "invalid_argument"
    with pytest.raises(PageControlError) as err:
        await pages.wait_for(ctx, "p1", selector="e3")  # snapshot refs are not waitable
    assert err.value.reason == "invalid_argument"


# ── JS dialogs ───────────────────────────────────────────────────────────────


class FakeDialog:
    def __init__(self, kind="confirm", message="Delete everything?", default="") -> None:
        self.type, self.message, self.default_value = kind, message, default
        self.handled: asyncio.Event = asyncio.Event()
        self.result: tuple | None = None

    async def accept(self, text=None):
        self.result = ("accept", text)
        self.handled.set()

    async def dismiss(self):
        self.result = ("dismiss", None)
        self.handled.set()


def dialog_click(page, dialog):
    """A click handler that raises a dialog and blocks (like a real frozen page) until it is handled."""

    async def click(**kw):
        page.emit("dialog", dialog)
        await dialog.handled.wait()

    return click


async def test_a_click_that_opens_a_dialog_returns_the_dialog_instead_of_hanging():
    pages, ctx, page = await selector_controller()
    button, dialog = FakeElement(), FakeDialog()
    button.click = dialog_click(page, dialog)
    page.table = {"role:button|Delete": [button]}
    started = asyncio.get_running_loop().time()
    result = await pages.click(ctx, "p1", 'role=button[name="Delete"]')
    assert asyncio.get_running_loop().time() - started < 2
    assert result["dialog"] == {"type": "confirm", "message": "Delete everything?", "default_value": None}
    assert "browser_dialog" in result["dialog_hint"] and result["title"] == ""
    # The page is frozen: everything else refuses until the dialog is handled.
    for call in (pages.snapshot(ctx, "p1"), pages.get_text(ctx, "p1"), pages.screenshot(ctx, "p1"),
                 pages.navigate(ctx, "p1", "https://example.com/"), pages.press_key(ctx, "p1", "Enter")):
        with pytest.raises(PageControlError) as err:
            await call
        assert err.value.reason == "dialog_open"
    handled = await pages.dialog(ctx, "p1", "accept")
    assert dialog.result == ("accept", None)
    assert handled["handled"] == "accept" and handled["handled_dialog"]["message"] == "Delete everything?"
    assert "dialog" not in handled
    await pages.snapshot(ctx, "p1")  # unfrozen
    assert not pages._background  # the click that raised it has finished


async def test_dismissing_and_answering_a_prompt():
    pages, ctx, page = await selector_controller()
    await pages._current_page(ctx, "p1")  # hooks the page
    dialog = FakeDialog("prompt", "Your name?", "anon")
    page.emit("dialog", dialog)
    result = await pages.dialog(ctx, "p1", "accept", "Ada")
    assert dialog.result == ("accept", "Ada") and result["handled_dialog"]["default_value"] == "anon"
    second = FakeDialog("alert", "Done")
    page.emit("dialog", second)
    await pages.dialog(ctx, "p1", "dismiss")
    assert second.result == ("dismiss", None)


async def test_dialog_tool_errors():
    pages, ctx, page = await selector_controller()
    with pytest.raises(PageControlError) as err:
        await pages.dialog(ctx, "p1", "accept")
    assert err.value.reason == "no_dialog"
    with pytest.raises(PageControlError) as err:
        await pages.dialog(ctx, "p1", "maybe")
    assert err.value.reason == "invalid_argument"


async def test_an_unhandled_dialog_is_dismissed_after_a_while(monkeypatch):
    from backend import page_control

    monkeypatch.setattr(page_control, "DIALOG_AUTO_DISMISS_S", 0.1)
    pages, ctx, page = await selector_controller()
    await pages._current_page(ctx, "p1")
    dialog = FakeDialog("alert", "Hi")
    page.emit("dialog", dialog)
    await asyncio.wait_for(dialog.handled.wait(), 2)
    assert dialog.result == ("dismiss", None) and page not in pages._dialogs


# ── batch ────────────────────────────────────────────────────────────────────


async def batch_setup():
    pages, ctx, page = await selector_controller()
    box, button = FakeElement("input"), FakeElement()
    page.table = {
        "label:Email": [box],
        "role:button|Log in": [button],
        "text:Welcome": [FakeElement()],
    }
    page.snapshot_handle = FakeSnapshotHandle(['[e0] button "Log in"'], [FakeElement()])
    return pages, ctx, page, box, button


async def test_batch_runs_steps_in_order_and_appends_a_snapshot():
    pages, ctx, page, box, button = await batch_setup()
    result = await pages.batch(ctx, "p1", [
        {"do": "navigate", "url": "https://example.com/login"},
        {"do": "type", "ref": "label=Email", "text": "me@example.com"},
        {"do": "click", "ref": 'role=button[name="Log in"]'},
        {"do": "wait_for", "text": "Welcome", "timeout_ms": 500},
        {"do": "get_text", "max_chars": 100},
    ])
    assert box.filled == "me@example.com" and button.clicked
    assert result["completed"] == 5 and result["total"] == 5 and result["stopped"] is None
    assert [r["do"] for r in result["steps"]] == ["navigate", "type", "click", "wait_for", "get_text"]
    assert result["steps"][-1]["text"] == "body text"
    assert result["url"] == "https://example.com/login" and '[e0] button "Log in"' in result["snapshot"]


async def test_batch_stops_at_the_first_error_and_still_snapshots():
    pages, ctx, page, box, button = await batch_setup()
    result = await pages.batch(ctx, "p1", [
        {"do": "type", "ref": "label=Email", "text": "x"},
        {"do": "click", "ref": "text=Nope"},
        {"do": "click", "ref": 'role=button[name="Log in"]'},
    ])
    assert result["stopped"] == "error" and result["stopped_at"] == 1 and result["completed"] == 1
    assert result["steps"][1]["reason"] == "selector_not_found" and len(result["steps"]) == 2
    assert button.clicked is False and "snapshot" in result
    carry_on = await pages.batch(ctx, "p1", [
        {"do": "click", "ref": "text=Nope"},
        {"do": "click", "ref": 'role=button[name="Log in"]'},
    ], stop_on_error=False)
    assert carry_on["completed"] == 1 and carry_on["stopped"] is None and button.clicked


async def test_batch_can_answer_the_dialog_a_step_raised():
    pages, ctx, page, box, button = await batch_setup()
    dialog = FakeDialog()
    button.click = dialog_click(page, dialog)
    result = await pages.batch(ctx, "p1", [
        {"do": "click", "ref": 'role=button[name="Log in"]'},
        {"do": "dialog", "answer": "accept"},
        {"do": "wait_for", "ms": 1},
    ])
    assert result["completed"] == 3 and result["stopped"] is None and dialog.result == ("accept", None)
    assert result["steps"][0]["dialog"]["type"] == "confirm"


async def test_batch_stops_on_a_dialog_nobody_handles():
    pages, ctx, page, box, button = await batch_setup()
    dialog = FakeDialog()
    button.click = dialog_click(page, dialog)
    result = await pages.batch(ctx, "p1", [
        {"do": "click", "ref": 'role=button[name="Log in"]'},
        {"do": "type", "ref": "label=Email", "text": "x"},
    ])
    assert result["stopped"] == "dialog" and result["stopped_at"] == 0
    assert result["dialog"]["message"] == "Delete everything?" and "snapshot" not in result
    await pages.dialog(ctx, "p1", "dismiss")


async def test_batch_without_a_snapshot_and_validation():
    pages, ctx, page, box, button = await batch_setup()
    result = await pages.batch(ctx, "p1", [{"do": "back"}], snapshot_after=False)
    assert "snapshot" not in result and "url" in result
    for bad in (None, [], "click", [{"do": "explode"}], [{"ref": "e1"}], ["click"], [{"do": "back"}] * 21):
        with pytest.raises(PageControlError) as err:
            await pages.batch(ctx, "p1", bad)
        assert err.value.reason == "invalid_argument", bad


# ── files: downloads and confined uploads ────────────────────────────────────


class FakeDownload:
    def __init__(self, name="report.csv", url="https://shop.example.com/export?token=secret", data=b"a,b\n1,2\n", fail=False, delay=0.0):
        self.suggested_filename, self.url = name, url
        self._data, self._fail, self._delay = data, fail, delay

    async def save_as(self, path):
        await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError("disk full")
        Path(path).write_bytes(self._data)


def files_controller(tmp_path):
    files_dir = tmp_path / "agent-files"
    files_dir.mkdir()
    ctx = FakeContext()
    page = SelectorPage()
    ctx.pages.append(page)
    return PageController(files_dir=files_dir), ctx, page, files_dir


async def test_downloads_are_saved_into_the_agent_folder_and_listed(tmp_path):
    pages, ctx, page, files_dir = files_controller(tmp_path)
    await pages._current_page(ctx, "p1")
    page.emit("download", FakeDownload("../../etc/evil.sh", delay=0.2))
    page.emit("download", FakeDownload("bad.bin", fail=True))
    listing = await pages.downloads(ctx, "p1")  # waits for the slow save
    ok = next(d for d in listing["downloads"] if d["status"] == "done")
    assert ok["filename"] == "evil.sh" and ok["bytes"] == len(b"a,b\n1,2\n")
    assert Path(ok["path"]).resolve().is_relative_to((files_dir / "downloads" / "p1").resolve())
    assert Path(ok["path"]).read_bytes() == b"a,b\n1,2\n"
    assert "token=secret" not in ok["url"]  # query strings can carry secrets
    failed = next(d for d in listing["downloads"] if d["status"] == "failed")
    assert "disk full" in failed["error"]
    assert listing["files_dir"] == str(files_dir)


async def test_upload_accepts_only_files_inside_the_agent_folder(tmp_path):
    pages, ctx, page, files_dir = files_controller(tmp_path)
    page.table = {"label:Resume": [], }
    box = FakeElement("input")
    box.is_file = True
    page.table = {"label:Resume": [box]}
    good = files_dir / "cv.pdf"
    good.write_bytes(b"%PDF")
    result = await pages.upload(ctx, "p1", "label=Resume", [str(good)])
    assert box.uploaded == [str(good.resolve())] and result["uploaded"] == ["cv.pdf"]

    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    (files_dir / "link.txt").symlink_to(secret)  # a symlink must not smuggle a file out
    for bad, reason in (
        (str(secret), "path_not_allowed"),
        (str(files_dir / "link.txt"), "path_not_allowed"),
        (str(files_dir / ".." / "secret.txt"), "path_not_allowed"),
        (str(files_dir / "missing.pdf"), "invalid_argument"),
    ):
        with pytest.raises(PageControlError) as err:
            await pages.upload(ctx, "p1", "label=Resume", [bad])
        assert err.value.reason == reason, bad
    for bad_list in ([], "cv.pdf", [str(good)] * 11, [""]):
        with pytest.raises(PageControlError) as err:
            await pages.upload(ctx, "p1", "label=Resume", bad_list)
        assert err.value.reason == "invalid_argument"


async def test_upload_through_a_button_that_opens_a_file_chooser(tmp_path):
    pages, ctx, page, files_dir = files_controller(tmp_path)
    button = FakeElement()  # not a file input
    page.table = {"role:button|Attach": [button]}
    doc = files_dir / "note.txt"
    doc.write_text("hi")
    await pages.upload(ctx, "p1", 'role=button[name="Attach"]', [str(doc)])
    assert button.clicked and page.chooser_files == [str(doc.resolve())]


async def test_file_tools_are_off_without_a_folder():
    pages, ctx, page = await selector_controller()
    for call in (pages.downloads(ctx, "p1"), pages.upload(ctx, "p1", "css=input", ["/x"])):
        with pytest.raises(PageControlError) as err:
            await call
        assert err.value.reason == "files_disabled"


async def test_upload_size_limit(tmp_path, monkeypatch):
    from backend import page_control

    pages, ctx, page, files_dir = files_controller(tmp_path)
    box = FakeElement("input")
    box.is_file = True
    page.table = {"label:File": [box]}
    big = files_dir / "big.bin"
    big.write_bytes(b"x" * 20)
    monkeypatch.setattr(page_control, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(PageControlError) as err:
        await pages.upload(ctx, "p1", "label=File", [str(big)])
    assert err.value.reason == "invalid_argument" and "MB" in err.value.detail


async def test_batch_can_upload(tmp_path):
    pages, ctx, page, files_dir = files_controller(tmp_path)
    box = FakeElement("input")
    box.is_file = True
    page.table = {"label:File": [box]}
    page.snapshot_handle = FakeSnapshotHandle([], [])
    doc = files_dir / "a.txt"
    doc.write_text("a")
    result = await pages.batch(ctx, "p1", [{"do": "upload", "ref": "label=File", "paths": [str(doc)]}])
    assert result["completed"] == 1 and box.uploaded == [str(doc.resolve())]


async def test_upload_finds_hidden_file_inputs_but_clicks_need_visible_elements(tmp_path):
    pages, ctx, page, files_dir = files_controller(tmp_path)
    box = FakeElement("input")
    box.is_file = True
    page.table = {"css:#f": [box]}
    doc = files_dir / "a.txt"
    doc.write_text("a")
    locators: list[FakeLocator] = []
    original = page._loc

    def spy(kind, value, **kw):
        loc = original(kind, value, **kw)
        locators.append(loc)
        return loc

    page._loc = spy
    await pages.upload(ctx, "p1", "css=#f", [str(doc)])
    assert not hasattr(locators[-1], "filtered")  # no visibility filter for upload
    await pages.click(ctx, "p1", "css=#f")
    assert locators[-1].filtered == {"visible": True}
