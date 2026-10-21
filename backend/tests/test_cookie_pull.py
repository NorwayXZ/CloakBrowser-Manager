"""Pulling a running browser's cookies back, and exporting them.

Debug-mode launches are read through the Playwright context the Manager
holds (faked here); manual launches are read through the profile's local
extension, which polls the Manager and posts its cookies back (the post-back
is faked here, and once driven over real HTTP). Cookie values and channel
tokens must never appear in logs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from backend import browser_manager as browser_manager_module
from backend import main
from backend.browser_manager import (
    BrowserManager,
    CookiePullError,
    RunningProfile,
)
from backend.cookie_formats import parse_cookie_text
from backend.cookie_pull import (
    CookiePullChannel,
    CookiePullTimeout,
    CookiePullUnavailable,
)
from backend.runtime import RuntimeConfig

SECRET_VALUE = "s3cr3t-cookie-value"

LIVE_COOKIES = [
    {
        "name": "sid", "value": SECRET_VALUE, "domain": ".example.com", "path": "/",
        "expires": 1893456000.0, "httpOnly": True, "secure": True, "sameSite": "Lax",
    },
    {
        "name": "pref", "value": "zh", "domain": "example.com", "path": "/",
        "expires": -1, "httpOnly": False, "secure": False, "sameSite": "None",
    },
]

PULLED = [
    {
        "name": "sid", "value": SECRET_VALUE, "domain": ".example.com", "path": "/",
        "secure": True, "httpOnly": True, "hostOnly": False,
        "sameSite": "lax", "expirationDate": 1893456000,
    },
    {
        "name": "pref", "value": "zh", "domain": "example.com", "path": "/",
        "secure": False, "httpOnly": False, "hostOnly": True,
        "sameSite": "none", "session": True,
    },
]


def _manager_with_context(tmp_path, context) -> BrowserManager:
    manager = BrowserManager(RuntimeConfig("linux", "docker", "vnc", tmp_path))
    manager.running["p1"] = RunningProfile(profile_id="p1", context=context, cdp_port=9222)
    return manager


@pytest.mark.asyncio
async def test_pull_reads_cookies_through_the_running_context(tmp_path, caplog):
    context = MagicMock()
    context.cookies = AsyncMock(return_value=LIVE_COOKIES)
    manager = _manager_with_context(tmp_path, context)

    with caplog.at_level(logging.INFO, logger="backend.browser_manager"):
        cookies = await manager.pull_profile_cookies("p1")

    assert cookies == PULLED
    assert SECRET_VALUE not in caplog.text


@pytest.mark.asyncio
async def test_pull_requires_a_running_browser(tmp_path):
    manager = BrowserManager(RuntimeConfig("linux", "docker", "vnc", tmp_path))

    with pytest.raises(CookiePullError, match="没有在运行"):
        await manager.pull_profile_cookies("missing")


@pytest.mark.asyncio
async def test_pull_explains_manual_launch_without_the_pull_channel(tmp_path):
    # Running (context is None) but launched before the extension channel
    # existed, so no token was registered for it.
    manager = _manager_with_context(tmp_path, None)

    with pytest.raises(CookiePullError, match="导回通道"):
        await manager.pull_profile_cookies("p1")


@pytest.mark.asyncio
async def test_pull_wraps_context_failures(tmp_path):
    context = MagicMock()
    context.cookies = AsyncMock(side_effect=RuntimeError("CDP session closed"))
    manager = _manager_with_context(tmp_path, context)

    with pytest.raises(CookiePullError, match="读取 Cookie 失败"):
        await manager.pull_profile_cookies("p1")


def _patch_pull(monkeypatch: pytest.MonkeyPatch, result=PULLED, error: Exception | None = None):
    if error is not None:
        monkeypatch.setattr(main.browser_mgr, "pull_profile_cookies", AsyncMock(side_effect=error))
    else:
        monkeypatch.setattr(main.browser_mgr, "pull_profile_cookies", AsyncMock(return_value=result))


def test_pull_endpoint_returns_cookies_and_serialized_json(app_client: TestClient, sample_profile, monkeypatch):
    _patch_pull(monkeypatch)

    resp = app_client.post(f"/api/profiles/{sample_profile['id']}/cookies/pull")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["cookies"] == PULLED
    assert json.loads(body["cookies_json"]) == PULLED


def test_pull_endpoint_does_not_save_to_the_profile(app_client: TestClient, sample_profile, monkeypatch):
    _patch_pull(monkeypatch)

    app_client.post(f"/api/profiles/{sample_profile['id']}/cookies/pull")

    resp = app_client.get(f"/api/profiles/{sample_profile['id']}")
    assert resp.json()["cookies_json"] is None


def test_pull_endpoint_surfaces_the_readable_error(app_client: TestClient, sample_profile, monkeypatch):
    _patch_pull(monkeypatch, error=CookiePullError("浏览器没有在运行：请先用「调试模式」启动"))

    resp = app_client.post(f"/api/profiles/{sample_profile['id']}/cookies/pull")

    assert resp.status_code == 409
    assert "调试模式" in resp.json()["detail"]


def test_pull_endpoint_profile_not_found(app_client: TestClient):
    resp = app_client.post("/api/profiles/nope/cookies/pull")
    assert resp.status_code == 404


def test_export_endpoint_json_is_cookie_editor_format(app_client: TestClient, sample_profile, monkeypatch):
    _patch_pull(monkeypatch)

    resp = app_client.get(f"/api/profiles/{sample_profile['id']}/cookies/export", params={"format": "json"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition and "cookies.json" in disposition
    exported = resp.json()
    assert exported[0]["name"] == "sid"
    assert exported[0]["expirationDate"] == 1893456000
    assert exported[0]["session"] is False
    assert "expirationDate" not in exported[1]
    assert exported[1]["session"] is True
    assert exported[1]["sameSite"] == "no_restriction"


def test_export_endpoint_netscape_parses_back(app_client: TestClient, sample_profile, monkeypatch):
    _patch_pull(monkeypatch)

    resp = app_client.get(f"/api/profiles/{sample_profile['id']}/cookies/export", params={"format": "netscape"})

    assert resp.status_code == 200
    assert "cookies.txt" in resp.headers["content-disposition"]
    fmt, parsed = parse_cookie_text(resp.text)
    assert fmt == "netscape"
    assert {c["name"] for c in parsed} == {"sid", "pref"}


def test_export_endpoint_rejects_unknown_format(app_client: TestClient, sample_profile):
    resp = app_client.get(f"/api/profiles/{sample_profile['id']}/cookies/export", params={"format": "yaml"})
    assert resp.status_code == 422


# ── Manual launches: the extension channel ──────────────────────────────────

# chrome.cookies.getAll shape: lowercase snake sameSite, session flag.
EXTENSION_COOKIES = [
    {
        "name": "sid", "value": SECRET_VALUE, "domain": ".example.com", "path": "/",
        "secure": True, "httpOnly": True, "hostOnly": False,
        "sameSite": "lax", "session": False, "expirationDate": 1893456000.0,
    },
    {
        "name": "pref", "value": "zh", "domain": "example.com", "path": "/",
        "secure": False, "httpOnly": False, "hostOnly": True,
        "sameSite": "no_restriction", "session": True,
    },
]

EXTENSION_PULLED = [
    {
        "name": "sid", "value": SECRET_VALUE, "domain": ".example.com", "path": "/",
        "secure": True, "httpOnly": True, "hostOnly": False,
        "sameSite": "lax", "expirationDate": 1893456000,
    },
    {
        "name": "pref", "value": "zh", "domain": "example.com", "path": "/",
        "secure": False, "httpOnly": False, "hostOnly": True,
        "sameSite": "none", "session": True,
    },
]


@pytest.mark.asyncio
async def test_pull_manual_launch_goes_through_the_extension(tmp_path, caplog):
    manager = _manager_with_context(tmp_path, None)
    token = manager.cookie_pulls.register_token("p1")

    async def fake_extension() -> None:
        for _ in range(200):
            request_id = manager.cookie_pulls.pending_request("p1", token)
            if request_id:
                break
            await asyncio.sleep(0.01)
        else:  # pragma: no cover - the pull must register a pending request
            raise AssertionError("no pending pull request appeared")
        assert manager.cookie_pulls.submit_result("p1", token, request_id, EXTENSION_COOKIES)

    with caplog.at_level(logging.INFO):
        task = asyncio.create_task(fake_extension())
        cookies = await manager.pull_profile_cookies("p1")
        await task

    assert cookies == EXTENSION_PULLED
    assert SECRET_VALUE not in caplog.text
    assert token not in caplog.text


@pytest.mark.asyncio
async def test_pull_manual_launch_times_out_when_the_browser_stays_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_manager_module, "PULL_TIMEOUT_SECONDS", 0.2)
    manager = _manager_with_context(tmp_path, None)
    manager.cookie_pulls.register_token("p1")

    with pytest.raises(CookiePullError, match="没有响应"):
        await manager.pull_profile_cookies("p1")


@pytest.mark.asyncio
async def test_pull_manual_launch_fails_fast_when_the_browser_closes(tmp_path):
    manager = _manager_with_context(tmp_path, None)
    manager.cookie_pulls.register_token("p1")

    async def close_browser() -> None:
        await asyncio.sleep(0.05)
        manager.cookie_pulls.drop("p1")

    task = asyncio.create_task(close_browser())
    with pytest.raises(CookiePullError, match="浏览器已关闭"):
        await manager.pull_profile_cookies("p1")
    await task


# ── The channel registry itself ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_channel_rejects_wrong_tokens_and_stale_requests():
    channel = CookiePullChannel()
    token = channel.register_token("p1")

    waiter = asyncio.create_task(channel.request_cookies("p1", timeout=5))
    await asyncio.sleep(0.05)

    assert channel.pending_request("p1", "wrong-token") is None
    request_id = channel.pending_request("p1", token)
    assert request_id
    assert not channel.submit_result("p1", "wrong-token", request_id, [])
    assert not channel.submit_result("p1", token, "some-other-request", [])
    assert not channel.submit_result("p1", token, request_id, "not-a-list")
    assert channel.submit_result("p1", token, request_id, EXTENSION_COOKIES)
    # A second submit for the same request is too late.
    assert not channel.submit_result("p1", token, request_id, [])

    assert await waiter == EXTENSION_COOKIES


@pytest.mark.asyncio
async def test_channel_request_times_out():
    channel = CookiePullChannel()
    channel.register_token("p1")

    with pytest.raises(CookiePullTimeout):
        await channel.request_cookies("p1", timeout=0.1)
    # The timed-out request no longer shows as pending.
    assert channel.pending_request("p1", channel.register_token("p1")) is None


@pytest.mark.asyncio
async def test_channel_drop_fails_a_waiting_pull():
    channel = CookiePullChannel()
    channel.register_token("p1")

    waiter = asyncio.create_task(channel.request_cookies("p1", timeout=30))
    await asyncio.sleep(0.05)
    channel.drop("p1")

    with pytest.raises(CookiePullUnavailable, match="浏览器已关闭"):
        await waiter
    assert not channel.has_token("p1")


# ── The extension endpoints over HTTP ───────────────────────────────────────


def _start_http_waiter(app_client: TestClient, channel: CookiePullChannel, profile_id: str):
    """A panel-side pull waiting on the app's own event loop, as in production.

    Returns (future, outcome); the future resolves once the extension's
    post-back lands and ``outcome["cookies"]`` holds the raw entries.
    """
    outcome: dict = {}

    async def wait() -> None:
        outcome["cookies"] = await channel.request_cookies(profile_id, timeout=10)

    future = app_client.portal.start_task_soon(wait)
    return future, outcome


def _poll_request_id(app_client: TestClient, profile_id: str, token: str) -> str:
    request_id = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not request_id:
        resp = app_client.get(
            f"/ext/cookie-pull/{profile_id}/pending",
            headers={"X-Profile-Token": token, "X-Forwarded-For": "127.0.0.1"},
        )
        assert resp.status_code == 200
        request_id = resp.json()["request_id"]
        if not request_id:
            time.sleep(0.05)
    assert request_id
    return request_id


def test_extension_endpoints_round_trip(app_client: TestClient, sample_profile):
    channel = main.browser_mgr.cookie_pulls
    profile_id = sample_profile["id"]
    token = channel.register_token(profile_id)
    future, outcome = _start_http_waiter(app_client, channel, profile_id)

    request_id = _poll_request_id(app_client, profile_id, token)

    resp = app_client.post(
        f"/ext/cookie-pull/{profile_id}/result",
        headers={"X-Profile-Token": token, "X-Forwarded-For": "127.0.0.1"},
        json={"request_id": request_id, "cookies": EXTENSION_COOKIES},
    )
    assert resp.status_code == 200
    future.result(timeout=5)
    assert outcome["cookies"] == EXTENSION_COOKIES


def test_extension_endpoints_reject_bad_tokens(app_client: TestClient, sample_profile):
    channel = main.browser_mgr.cookie_pulls
    profile_id = sample_profile["id"]
    token = channel.register_token(profile_id)
    future, outcome = _start_http_waiter(app_client, channel, profile_id)

    # A wrong token learns nothing about the pending request…
    resp = app_client.get(
        f"/ext/cookie-pull/{profile_id}/pending",
        headers={"X-Profile-Token": "wrong", "X-Forwarded-For": "127.0.0.1"},
    )
    assert resp.json() == {"request_id": None}

    request_id = _poll_request_id(app_client, profile_id, token)

    # …and cannot answer it either.
    resp = app_client.post(
        f"/ext/cookie-pull/{profile_id}/result",
        headers={"X-Profile-Token": "wrong", "X-Forwarded-For": "127.0.0.1"},
        json={"request_id": request_id, "cookies": EXTENSION_COOKIES},
    )
    assert resp.status_code == 403
    resp = app_client.post(
        f"/ext/cookie-pull/{profile_id}/result",
        headers={"X-Profile-Token": token, "X-Forwarded-For": "127.0.0.1"},
        json={"request_id": "not-the-pending-one", "cookies": EXTENSION_COOKIES},
    )
    assert resp.status_code == 403

    # The real answer still lands.
    resp = app_client.post(
        f"/ext/cookie-pull/{profile_id}/result",
        headers={"X-Profile-Token": token, "X-Forwarded-For": "127.0.0.1"},
        json={"request_id": request_id, "cookies": EXTENSION_COOKIES},
    )
    assert resp.status_code == 200
    future.result(timeout=5)
    assert outcome["cookies"] == EXTENSION_COOKIES


def test_export_endpoint_surfaces_the_readable_error(app_client: TestClient, sample_profile, monkeypatch):
    _patch_pull(monkeypatch, error=CookiePullError("这个浏览器是普通模式启动的"))

    resp = app_client.get(f"/api/profiles/{sample_profile['id']}/cookies/export")

    assert resp.status_code == 409
    assert "普通模式" in resp.json()["detail"]
