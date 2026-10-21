"""Pulling a running browser's cookies back, and exporting them.

The read channel is the Playwright context of a debug-mode launch; the
manager tests fake that context, the API tests fake the manager method.
Cookie values must never appear in logs.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from backend import main
from backend.browser_manager import (
    BrowserManager,
    CookiePullError,
    RunningProfile,
)
from backend.cookie_formats import parse_cookie_text
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

    with pytest.raises(CookiePullError, match="调试模式"):
        await manager.pull_profile_cookies("missing")


@pytest.mark.asyncio
async def test_pull_explains_manual_launches_have_no_channel(tmp_path):
    manager = _manager_with_context(tmp_path, None)

    with pytest.raises(CookiePullError, match="普通模式"):
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


def test_export_endpoint_surfaces_the_readable_error(app_client: TestClient, sample_profile, monkeypatch):
    _patch_pull(monkeypatch, error=CookiePullError("这个浏览器是普通模式启动的"))

    resp = app_client.get(f"/api/profiles/{sample_profile['id']}/cookies/export")

    assert resp.status_code == 409
    assert "普通模式" in resp.json()["detail"]
