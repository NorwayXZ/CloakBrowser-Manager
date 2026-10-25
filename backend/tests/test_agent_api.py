"""Tests for the Manager's agent surface: leases, scoped tokens, page control,
the tool API and the HTTP MCP endpoint."""

from __future__ import annotations

import json
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

    async def evaluate(self, js):
        return self.tag


class FakeValueHandle:
    def __init__(self, value) -> None:
        self.value = value

    async def json_value(self):
        return self.value

    async def get_properties(self):
        return {str(i): el for i, el in enumerate(self.value)}


class FakeSnapshotHandle:
    def __init__(self, lines, elements, frames=0, truncated=False) -> None:
        self.props = {
            "lines": FakeValueHandle(lines),
            "els": FakeValueHandle(elements),
            "frames": FakeValueHandle(frames),
            "truncated": FakeValueHandle(truncated),
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
        return None


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
