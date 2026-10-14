from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.request_guard import allowed_hostnames, host_is_allowed, origin_matches_host
from backend.runtime import RuntimeConfig


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1:8080", True),
        ("localhost:8080", True),
        ("[::1]:8080", True),
        ("127.0.0.1", True),
        ("attacker.example:8080", False),
        ("127.0.0.1.attacker.example", False),
        ("", False),
        (None, False),
    ],
)
def test_host_is_allowed_only_for_loopback(host, expected):
    assert host_is_allowed(host, allowed_hostnames({})) is expected


def test_allowed_hosts_env_extends_loopback():
    allowed = allowed_hostnames({"CLOAKBROWSER_MANAGER_ALLOWED_HOSTS": "mac-mini.local, [fd00::1]"})
    assert host_is_allowed("mac-mini.local:8080", allowed)
    assert host_is_allowed("[fd00::1]:8080", allowed)
    assert not host_is_allowed("other.local:8080", allowed)


@pytest.mark.parametrize(
    ("origin", "host", "expected"),
    [
        (None, "127.0.0.1:8080", True),
        ("http://127.0.0.1:8080", "127.0.0.1:8080", True),
        ("https://manager.example", "manager.example", True),
        ("https://manager.example", "manager.example:443", True),
        ("http://localhost:8080", "127.0.0.1:8080", False),
        ("http://127.0.0.1:3000", "127.0.0.1:8080", False),
        ("https://attacker.example", "127.0.0.1:8080", False),
        ("null", "127.0.0.1:8080", False),
        ("file://", "127.0.0.1:8080", False),
    ],
)
def test_origin_must_match_host(origin, host, expected):
    assert origin_matches_host(origin, host) is expected


@pytest.fixture()
def native_client(app_client: TestClient, tmp_db, monkeypatch: pytest.MonkeyPatch):
    from backend import main

    monkeypatch.setattr(
        main.browser_mgr, "runtime", RuntimeConfig("macos", "native", "native-window", tmp_db)
    )
    return app_client


def test_native_rejects_dns_rebinding_host(native_client: TestClient):
    assert native_client.get("/api/profiles").status_code == 200
    resp = native_client.get("/api/profiles", headers={"host": "attacker.example:8080"})
    assert resp.status_code == 403


def test_native_rejects_cross_site_post(native_client: TestClient):
    blocked = native_client.post(
        "/api/profiles",
        json={"name": "Forged"},
        headers={"origin": "https://attacker.example"},
    )
    assert blocked.status_code == 403
    assert native_client.get("/api/profiles").json() == []

    allowed = native_client.post(
        "/api/profiles",
        json={"name": "Panel"},
        headers={"origin": "http://127.0.0.1:8080"},
    )
    assert allowed.status_code == 201


def test_cross_site_get_is_not_blocked_by_origin(native_client: TestClient):
    # Cross-site GETs cannot read the response (CORS); only Host is enforced.
    resp = native_client.get("/api/status", headers={"origin": "https://attacker.example"})
    assert resp.status_code == 200


def test_native_rejects_cross_site_websocket(native_client: TestClient):
    with pytest.raises(Exception):
        with native_client.websocket_connect(
            "/api/profiles/missing/cdp", headers={"origin": "https://attacker.example"}
        ):
            pass


def test_docker_mode_allows_public_host_but_blocks_cross_site(app_client: TestClient):
    host = {"host": "manager.example"}
    assert app_client.get("/api/profiles", headers=host).status_code == 200
    resp = app_client.post(
        "/api/profiles",
        json={"name": "Forged"},
        headers={**host, "origin": "https://attacker.example"},
    )
    assert resp.status_code == 403
