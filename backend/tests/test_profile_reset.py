"""One-click profile reset: same profile, brand-new browser.

Reset must wipe the whole user data dir (and only that profile's own one),
roll a new seed and device, clear imported cookies and the IP-derived
timezone/locale, and keep name, group, notes, tags and the proxy binding.
A running profile is stopped the normal way first; mail addresses and vault
entries follow the chosen ``bindings``.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from backend import agent_tools
from backend import database as db
from backend import main, profile_reset

ROOT = Path(__file__).resolve().parents[2]
EDITOR_PRESETS = ROOT / "frontend" / "src" / "next" / "features" / "editor" / "deviceProfiles.ts"

PROXY = "socks5://user:pass@203.0.113.7:1080"


def _make_profile(client: TestClient, **extra) -> dict:
    body = {
        "name": "注册号 A",
        "group_name": "美区",
        "notes": "第一次注册失败",
        "proxy": PROXY,
        "platform": "windows",
        "device_profile": "win_laptop_iris_xe_2256",
        "fingerprint_seed": 24680,
        "timezone": "America/Chicago",
        "locale": "en-US",
        "user_agent": "Mozilla/5.0 old",
        "cookies_json": '[{"name":"sid","value":"abc","domain":".example.com","path":"/"}]',
        "tags": [{"tag": "失败", "color": "#f00"}],
        **extra,
    }
    res = client.post("/api/profiles", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def _make_user_data(profile: dict) -> Path:
    root = Path(profile["user_data_dir"])
    for rel in ("Default/Cookies", "Default/Local Storage/leveldb/000003.log", "Default/IndexedDB/x.db",
                "Default/History", "Default/Service Worker/Database/MANIFEST", "Default/Login Data"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old")
    return root


def _reset(client: TestClient, pid: str, **body):
    return client.post(f"/api/profiles/{pid}/reset", json={"confirm": True, **body})


def test_reset_requires_explicit_confirm(app_client: TestClient):
    profile = _make_profile(app_client)
    root = _make_user_data(profile)
    assert app_client.post(f"/api/profiles/{profile['id']}/reset", json={}).status_code == 400
    assert app_client.post(f"/api/profiles/{profile['id']}/reset", json={"confirm": False}).status_code == 400
    assert (root / "Default" / "Cookies").exists()
    assert db.get_profile(profile["id"])["fingerprint_seed"] == 24680


def test_reset_wipes_browser_data_and_rolls_a_new_fingerprint(app_client: TestClient):
    profile = _make_profile(app_client)
    root = _make_user_data(profile)

    res = _reset(app_client, profile["id"])

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is True
    assert payload["was_running"] is False
    assert payload["files_removed"] == 6
    assert payload["old_fingerprint_seed"] == 24680
    assert payload["new_fingerprint_seed"] != 24680
    assert not root.exists()
    assert not any(p.name.startswith(".reset-") for p in root.parent.iterdir())

    stored = db.get_profile(profile["id"])
    assert stored["fingerprint_seed"] == payload["new_fingerprint_seed"]
    assert stored["device_profile"] != "win_laptop_iris_xe_2256"
    assert stored["device_profile"] == payload["device_profile"]
    assert stored["platform"] == "windows"
    device = next(d for d in profile_reset.DEVICE_PRESETS if d["id"] == stored["device_profile"])
    assert (stored["screen_width"], stored["screen_height"]) == (device["screen_width"], device["screen_height"])
    assert stored["gpu_renderer"] == device["gpu_renderer"]
    assert stored["hardware_concurrency"] == device["hardware_concurrency"]
    assert stored["user_agent"] is None
    assert stored["cookies_json"] is None
    assert stored["timezone"] is None and stored["locale"] is None


def test_reset_keeps_name_group_notes_tags_and_proxy(app_client: TestClient):
    profile = _make_profile(app_client)
    before = db.get_profile(profile["id"])

    assert _reset(app_client, profile["id"]).status_code == 200

    after = db.get_profile(profile["id"])
    for key in ("name", "group_name", "notes", "proxy", "proxy_id", "proxy_connection_mode", "relay_id",
                "startup_urls", "fingerprint_options", "user_data_dir", "created_at"):
        assert after[key] == before[key], key
    assert after["proxy"] == PROXY
    assert after["tags"] == [{"tag": "失败", "color": "#f00"}]


def test_reset_keeps_the_proxy_library_binding(app_client: TestClient):
    proxy_id = db.create_proxy_preset("家宽 1", PROXY, "direct")["id"]
    profile = _make_profile(app_client, proxy_id=proxy_id)
    assert db.get_profile(profile["id"])["proxy_id"] == proxy_id

    assert _reset(app_client, profile["id"]).status_code == 200

    assert db.get_profile(profile["id"])["proxy_id"] == proxy_id


def test_reset_macos_profile_picks_a_mac_device(app_client: TestClient):
    profile = _make_profile(app_client, platform="macos", device_profile="mba_13_m1_2020")

    res = _reset(app_client, profile["id"])

    assert res.status_code == 200, res.text
    stored = db.get_profile(profile["id"])
    assert stored["platform"] == "macos"
    assert stored["device_profile"] != "mba_13_m1_2020"
    assert stored["gpu_vendor"] == "Google Inc. (Apple)"


def test_reset_of_never_opened_profile_works(app_client: TestClient):
    profile = _make_profile(app_client)
    assert not Path(profile["user_data_dir"]).exists()
    res = _reset(app_client, profile["id"])
    assert res.status_code == 200, res.text
    assert res.json()["files_removed"] == 0


def test_reset_refuses_a_data_dir_that_is_not_the_profiles_own(app_client: TestClient):
    profile = _make_profile(app_client)
    other = db.DATA_DIR / "profiles" / "other-profile" / "Default"
    other.mkdir(parents=True, exist_ok=True)
    (other / "Cookies").write_bytes(b"keep")
    for bad in (db.DATA_DIR / "profiles", other.parent, db.DATA_DIR):
        with db.get_db() as conn:
            conn.execute("UPDATE profiles SET user_data_dir = ? WHERE id = ?", (str(bad), profile["id"]))
            conn.commit()
        res = _reset(app_client, profile["id"])
        assert res.status_code == 409, res.text
    assert (other / "Cookies").exists()
    assert db.get_profile(profile["id"])["fingerprint_seed"] == 24680


def test_reset_unknown_or_trashed_profile_is_404(app_client: TestClient):
    assert _reset(app_client, "does-not-exist").status_code == 404
    profile = _make_profile(app_client)
    assert app_client.delete(f"/api/profiles/{profile['id']}").status_code == 200
    assert _reset(app_client, profile["id"]).status_code == 404


def test_reset_stops_a_running_profile_first(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    profile = _make_profile(app_client)
    pid = profile["id"]
    root = _make_user_data(profile)
    order: list[str] = []

    async def fake_stop(profile_id, reason="用户关闭", **_kw):
        order.append("stop")
        assert (root / "Default" / "Cookies").exists()  # stopped before the wipe
        main.browser_mgr.running.pop(profile_id, None)

    stop = AsyncMock(side_effect=fake_stop)
    monkeypatch.setattr(main.browser_mgr, "stop", stop)
    main.browser_mgr.running[pid] = object()  # type: ignore[assignment]
    main.browser_mgr.cookie_pulls.register_token(pid)
    try:
        res = _reset(app_client, pid)
    finally:
        main.browser_mgr.running.pop(pid, None)

    assert res.status_code == 200, res.text
    assert res.json()["was_running"] is True
    stop.assert_awaited_once_with(pid, "重置环境")
    assert order == ["stop"]
    assert not root.exists()
    assert not main.browser_mgr.cookie_pulls.has_token(pid)


def test_reset_refuses_while_launching(app_client: TestClient):
    profile = _make_profile(app_client)
    root = _make_user_data(profile)
    main.browser_mgr._launching.add(profile["id"])
    try:
        res = _reset(app_client, profile["id"])
    finally:
        main.browser_mgr._launching.discard(profile["id"])
    assert res.status_code == 409, res.text
    assert (root / "Default" / "Cookies").exists()


async def test_held_stopped_blocks_a_launch():
    mgr = main.browser_mgr
    async with mgr.held_stopped("pid-x"):
        assert "pid-x" in mgr._launching
        with pytest.raises(RuntimeError):
            async with mgr.held_stopped("pid-x"):
                pass
    assert "pid-x" not in mgr._launching


def _bind_mail_and_vault(pid: str) -> None:
    db.add_mail_address("a1@mail.test", pid)
    db.add_mail_address("other@mail.test", "someone-else")
    db.create_vault_entry(profile_id=pid, site="example.com", username="u", email="a1@mail.test", password="p" * 20)


def test_reset_unbinds_mail_and_vault_by_default(app_client: TestClient):
    profile = _make_profile(app_client)
    _bind_mail_and_vault(profile["id"])

    res = _reset(app_client, profile["id"])

    assert res.status_code == 200, res.text
    assert res.json()["bindings"] == "unbind"
    assert res.json()["mail_addresses"] == 1 and res.json()["vault_entries"] == 1
    assert db.list_mail_addresses(profile["id"]) == []
    assert db.get_mail_address("a1@mail.test")["profile_id"] is None
    assert db.get_mail_address("other@mail.test")["profile_id"] == "someone-else"
    assert db.list_vault_entries(profile["id"]) == []
    kept = db.list_vault_entries()
    assert len(kept) == 1 and kept[0]["profile_id"] == ""


def test_reset_can_keep_or_delete_bindings(app_client: TestClient):
    kept = _make_profile(app_client)
    _bind_mail_and_vault(kept["id"])
    assert _reset(app_client, kept["id"], bindings="keep").status_code == 200
    assert len(db.list_mail_addresses(kept["id"])) == 1
    assert len(db.list_vault_entries(kept["id"])) == 1

    gone = _make_profile(app_client, name="注册号 B")
    db.add_mail_address("b1@mail.test", gone["id"])
    db.create_vault_entry(profile_id=gone["id"], site="example.com", username="u", email=None, password="p" * 20)
    assert _reset(app_client, gone["id"], bindings="delete").status_code == 200
    assert db.get_mail_address("b1@mail.test") is None
    assert db.list_vault_entries(gone["id"]) == []
    assert db.get_mail_address("other@mail.test")["profile_id"] == "someone-else"


def test_reset_rejects_unknown_bindings(app_client: TestClient):
    profile = _make_profile(app_client)
    assert _reset(app_client, profile["id"], bindings="nuke").status_code == 422


def test_fresh_identity_native_engine_clears_spoofed_hardware():
    fields = profile_reset.fresh_identity(
        {"platform": "windows", "device_profile": "win_laptop_arc_2880", "fingerprint_seed": 1},
        host_os="windows", native=True,
    )
    assert fields["gpu_vendor"] is None and fields["hardware_concurrency"] is None
    assert fields["device_profile"].startswith("win_")
    assert fields["fingerprint_seed"] != 1


def test_device_presets_match_the_editor_list():
    text = EDITOR_PRESETS.read_text(encoding="utf-8")
    editor_ids = set(re.findall(r'(?:appleProfile|windowsProfile)\(\s*"([a-z0-9_]+)"', text))
    assert editor_ids, "editor presets not found"
    assert {d["id"] for d in profile_reset.DEVICE_PRESETS} == editor_ids


def test_windows_presets_report_a_real_chrome_renderer_with_the_pci_device_id():
    # Real Chrome on Windows says "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002503) Direct3D11 ...)";
    # a renderer without the device id matches no real machine.
    from backend.device_templates import _RENDERER_RE

    windows = [d for d in profile_reset.DEVICE_PRESETS if d["platform"] == "windows"]
    assert windows
    for device in windows:
        assert _RENDERER_RE.match(device["gpu_renderer"]), device["gpu_renderer"]

    text = EDITOR_PRESETS.read_text(encoding="utf-8")
    editor = re.findall(r'windowsRenderer\("(\w+)", "([^"]+)", "([0-9A-F]+)"\)', text)
    assert len(editor) == len(windows)
    assert sorted(f"ANGLE ({v}, {m} (0x{int(i, 16):08X}) Direct3D11 vs_5_0 ps_5_0, D3D11)" for v, m, i in editor) == sorted(
        d["gpu_renderer"] for d in windows
    )


# ── agent tool ───────────────────────────────────────────────────────────────


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def post(self, path, json_body=None, timeout=None):
        self.calls.append((path, json_body))
        return self.response


async def test_reset_profile_tool_requires_confirm():
    client = _FakeClient((200, {}))
    result = await agent_tools.TOOLS["reset_profile"].handler(client, {"profile_id": "p1"})
    assert result["ok"] is False and result["reason"] == "invalid_argument"
    assert client.calls == []


async def test_reset_profile_tool_calls_the_reset_endpoint():
    client = _FakeClient((200, {
        "ok": True, "profile": {"id": "p1", "name": "A"}, "was_running": False, "files_removed": 4,
        "new_fingerprint_seed": 55555, "device_profile": "mba_13_m2_2022", "bindings": "keep",
        "mail_addresses": 1, "vault_entries": 0,
    }))
    result = await agent_tools.TOOLS["reset_profile"].handler(
        client, {"profile_id": "p1", "confirm": True, "bindings": "keep"},
    )
    assert client.calls == [("/api/profiles/p1/reset", {"confirm": True, "bindings": "keep"})]
    assert result["ok"] is True
    assert result["new_fingerprint_seed"] == 55555
    assert result["profile"]["id"] == "p1"
    assert agent_tools.TOOLS["reset_profile"].layer == "action"
