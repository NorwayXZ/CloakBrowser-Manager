"""Routing changes must preserve old profiles and never bypass a selected relay."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import database as db, main
from backend.xray_runtime import XrayProxyError, build_xray_config, validate_relay_link

RELAY = "trojan://relay-password@relay.example:443?sni=relay.example"
SOCKS = "socks5://alice:p%40ss%3Aword@exit.example:1080"


def test_chain_keeps_final_socks_credentials_and_routes_only_through_relay():
    config = build_xray_config(SOCKS, 18080, relay_link=RELAY)
    final, relay = config["outbounds"]
    assert final["protocol"] == "socks"
    assert final["settings"]["servers"][0] == {
        "address": "exit.example", "port": 1080, "users": [{"user": "alice", "pass": "p@ss:word"}],
    }
    assert final["streamSettings"]["sockopt"]["dialerProxy"] == relay["tag"]
    assert relay["protocol"] == "trojan"
    assert all(item["protocol"] != "freedom" for item in config["outbounds"])
    assert config["inbounds"][0]["listen"] == "127.0.0.1"
    assert config["inbounds"][0]["settings"]["udp"] is False


def test_unencrypted_relay_and_non_socks_final_are_rejected():
    with pytest.raises(XrayProxyError, match="加密"):
        validate_relay_link("vless://11111111-1111-1111-1111-111111111111@relay.example:80")
    with pytest.raises(XrayProxyError, match="SOCKS5"):
        build_xray_config("http://exit.example:8080", 18080, relay_link=RELAY)
    with pytest.raises(XrayProxyError):
        build_xray_config("socks5://exit.example:1080/path", 18080, relay_link=RELAY)


def test_old_profiles_stay_direct_and_selected_relay_is_persistent(tmp_db):
    old = db.create_profile("old", proxy=SOCKS)
    assert old["proxy_connection_mode"] == "direct" and old["relay_id"] is None
    relay = db.create_relay_node("US relay", RELAY)
    changed = db.update_profile(old["id"], proxy_connection_mode="relay", relay_id=relay["id"])
    db.init_db()
    assert db.get_profile(old["id"])["relay_id"] == relay["id"]
    assert changed["proxy"] == SOCKS
    with db.get_db() as conn:
        raw = conn.execute("SELECT proxy FROM relay_nodes").fetchone()[0]
    assert "relay-password" not in raw
    with pytest.raises(ValueError, match="仍被"):
        db.delete_relay_node(relay["id"])
    db.update_profile(old["id"], proxy_connection_mode="direct")
    assert db.get_profile(old["id"])["relay_id"] is None
    assert db.delete_relay_node(relay["id"])


def test_missing_relay_never_saves_an_implicitly_direct_profile(tmp_db):
    with pytest.raises(ValueError, match="中转"):
        db.create_profile("broken", proxy=SOCKS, proxy_connection_mode="relay", relay_id="missing")
    assert db.list_profiles() == []


def test_configuration_import_remaps_relay_ids_and_preserves_exit(tmp_db):
    relay = db.create_relay_node("Shared", RELAY)
    db.create_profile("through relay", proxy=SOCKS, proxy_connection_mode="relay", relay_id=relay["id"])
    exported = db.export_configuration()
    db.import_configuration(exported)
    profiles = db.list_profiles()
    assert len(profiles) == 2
    assert len({p["relay_id"] for p in profiles}) == 2
    assert all(p["proxy"] == SOCKS and p["proxy_connection_mode"] == "relay" for p in profiles)
    broken = {**exported, "relay_nodes": []}
    with pytest.raises(ValueError, match="缺少"):
        db.import_configuration(broken)
    assert len(db.list_profiles()) == 2


def test_relay_crud_and_profile_api(app_client):
    result = app_client.post("/api/relay-nodes", json={"name": "USA", "proxy": RELAY})
    assert result.status_code == 201
    relay = result.json()
    profile = app_client.post("/api/profiles", json={"name": "US socks", "proxy": SOCKS,
        "proxy_connection_mode": "relay", "relay_id": relay["id"]})
    assert profile.status_code == 201
    assert profile.json()["relay_id"] == relay["id"]
    assert app_client.get("/api/relay-nodes").json()[0]["profile_count"] == 1
    assert app_client.delete(f'/api/relay-nodes/{relay["id"]}').status_code == 409
    assert app_client.put(f'/api/profiles/{profile.json()["id"]}', json={"proxy_connection_mode": "direct"}).status_code == 200
    assert app_client.delete(f'/api/relay-nodes/{relay["id"]}').status_code == 200


def test_proxy_test_runs_the_selected_chain_and_returns_final_exit(app_client, monkeypatch):
    relay = db.create_relay_node("US hop", RELAY)
    process = type("Process", (), {"browser_proxy": "socks5://127.0.0.1:19090", "close": AsyncMock()})()
    start = AsyncMock(return_value=process)
    geo = AsyncMock(return_value={"ip": "203.0.113.20", "country": "US", "source": "test"})
    monkeypatch.setattr(main, "start_xray_proxy", start)
    monkeypatch.setattr(main, "fetch_proxy_geo", geo)
    monkeypatch.setattr(main, "check_ip_quality", AsyncMock(return_value=None))
    result = app_client.post("/api/proxy/test", json={"proxy": SOCKS, "proxy_connection_mode": "relay", "relay_id": relay["id"]})
    assert result.status_code == 200
    assert result.json()["ip"] == "203.0.113.20"
    assert result.json()["relay_name"] == "US hop"
    assert result.json()["elapsed_ms"] is not None
    assert start.call_args.kwargs["relay_link"] == RELAY
    geo.assert_awaited_once_with(process.browser_proxy)
    process.close.assert_awaited_once()


def test_broken_chain_does_not_fall_back_to_the_original_proxy(app_client, monkeypatch):
    relay = db.create_relay_node("broken", RELAY)
    monkeypatch.setattr(main, "start_xray_proxy", AsyncMock(side_effect=RuntimeError("relay unavailable")))
    geo = AsyncMock()
    monkeypatch.setattr(main, "fetch_proxy_geo", geo)
    result = app_client.post("/api/proxy/test", json={"proxy": SOCKS, "proxy_connection_mode": "relay", "relay_id": relay["id"]})
    assert result.status_code == 400
    geo.assert_not_awaited()


@pytest.mark.asyncio
async def test_browser_launch_uses_the_saved_chain_and_closes_its_runtime(tmp_db, tmp_path, monkeypatch):
    from backend import browser_manager as module
    from backend.tests.test_browser_manager import NATIVE_RUNTIME, _launch_profile
    relay = db.create_relay_node("US hop", RELAY)
    process = MagicMock()
    process.browser_proxy = "socks5://127.0.0.1:19090"
    process.close = AsyncMock()
    context = MagicMock()
    context.pages = []
    context.add_init_script = AsyncMock()
    context.close = AsyncMock()
    start = AsyncMock(return_value=process)
    launch = AsyncMock(return_value=context)
    monkeypatch.setattr(module, "start_xray_proxy", start)
    monkeypatch.setattr(module, "launch_persistent_context_async", launch)
    monkeypatch.setattr(module, "fetch_proxy_geo", AsyncMock(return_value={"ip": "203.0.113.20", "country_code": "US", "source": "test"}))
    manager = module.BrowserManager(NATIVE_RUNTIME)
    manager._wait_for_cdp = AsyncMock()
    profile = {**_launch_profile(tmp_path), "proxy": SOCKS, "proxy_connection_mode": "relay", "relay_id": relay["id"]}
    try:
        await manager.launch(profile, launch_mode="debug")
        assert start.call_args.kwargs["relay_link"] == RELAY
        assert launch.call_args.kwargs["proxy"] == process.browser_proxy
        assert "--disable-quic" in launch.call_args.kwargs["args"]
    finally:
        await manager.stop(profile["id"])
    process.close.assert_awaited_once()
