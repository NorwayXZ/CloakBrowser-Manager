"""Disposable identities: one-click creation and irreversible burn.

Creation must be coherent (unused device template, recommended defaults,
region-matched timezone/locale, disposable flag set). Burn must be a hard
purge — row and user data dir gone, nothing in the trash — and must
refuse non-disposable profiles and unconfirmed requests. The normal
soft-delete/restore flow stays untouched.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from backend import database as db
from backend import device_templates, main


def _create_disposable(client: TestClient, **body) -> dict:
    res = client.post("/api/profiles/disposable", json=body)
    assert res.status_code == 201, res.text
    return res.json()


# ── schema / flag ────────────────────────────────────────────────────────


def test_disposable_column_exists_and_defaults_off(tmp_db):
    with db.get_db() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()}
    assert "disposable" in cols
    profile = db.create_profile(name="普通画像")
    assert not profile.get("disposable")


# ── creation ─────────────────────────────────────────────────────────────


def test_create_disposable_defaults_us_persona(app_client: TestClient):
    profile = _create_disposable(app_client)
    assert profile["disposable"] is True
    assert profile["timezone"] == "America/New_York"
    assert profile["locale"] == "en-US"
    assert profile["platform"] == "windows"
    assert profile["name"].startswith("一次性身份 US")


def test_create_disposable_applies_recommended_defaults(app_client: TestClient):
    profile = _create_disposable(app_client)
    options = profile["fingerprint_options"]
    assert options["noise"] is False
    assert options["storage_quota_mb"] == 50000


def test_create_disposable_template_is_real_and_coherent(app_client: TestClient):
    profile = _create_disposable(app_client)
    tpl = device_templates.get_template(profile["device_profile"])
    assert tpl is not None
    assert profile["gpu_vendor"] == tpl["gpu_vendor"]
    assert profile["gpu_renderer"] == tpl["gpu_renderer"]
    assert profile["screen_width"] == tpl["screen_width"]
    assert profile["screen_height"] == tpl["screen_height"]
    assert profile["hardware_concurrency"] == tpl["hardware_concurrency"]
    assert profile["device_memory"] == tpl["device_memory"]


def test_create_disposable_region_persona(app_client: TestClient):
    profile = _create_disposable(app_client, region="JP")
    assert profile["timezone"] == "Asia/Tokyo"
    assert profile["locale"] == "ja-JP"


def test_create_disposable_explicit_timezone_locale_win(app_client: TestClient):
    profile = _create_disposable(
        app_client, region="JP", timezone="Europe/Berlin", locale="de-DE", name="临时工",
    )
    assert profile["timezone"] == "Europe/Berlin"
    assert profile["locale"] == "de-DE"
    assert profile["name"] == "临时工"


def test_create_disposable_avoids_templates_already_in_use(app_client: TestClient):
    first_template = device_templates.list_templates()[0]
    db.create_profile(name="已占用", device_profile=first_template["id"])
    created = [_create_disposable(app_client) for _ in range(5)]
    assert all(p["device_profile"] != first_template["id"] for p in created)


def test_create_disposable_never_repeats_a_template_while_unused_remain(app_client: TestClient):
    created = [_create_disposable(app_client) for _ in range(6)]
    ids = [p["device_profile"] for p in created]
    assert len(ids) == len(set(ids))


# ── burn ─────────────────────────────────────────────────────────────────


def _make_user_data(profile: dict, files: int = 3) -> Path:
    root = Path(profile["user_data_dir"])
    (root / "Default").mkdir(parents=True, exist_ok=True)
    for i in range(files):
        (root / "Default" / f"f{i}.dat").write_bytes(b"x" * 10)
    return root


def test_burn_requires_explicit_confirm(app_client: TestClient):
    profile = _create_disposable(app_client)
    assert app_client.post(f"/api/profiles/{profile['id']}/burn", json={}).status_code == 400
    assert app_client.post(
        f"/api/profiles/{profile['id']}/burn", json={"confirm": False}
    ).status_code == 400
    # Still there after both refusals.
    assert app_client.get(f"/api/profiles/{profile['id']}").status_code == 200


def test_burn_removes_row_and_directory(app_client: TestClient):
    profile = _create_disposable(app_client)
    root = _make_user_data(profile, files=3)

    res = app_client.post(f"/api/profiles/{profile['id']}/burn", json={"confirm": True})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is True
    assert payload["files_removed"] == 3
    assert payload["was_running"] is False
    assert not root.exists()
    assert db.get_profile(profile["id"]) is None
    assert app_client.get(f"/api/profiles/{profile['id']}").status_code == 404
    trash = app_client.get("/api/profiles/trash").json()
    assert all(p["id"] != profile["id"] for p in trash)


def test_burn_never_removes_the_profiles_root(app_client: TestClient):
    profile = _create_disposable(app_client)
    root = db.DATA_DIR / "profiles"
    keeper = root / "other-profile" / "Default"
    keeper.mkdir(parents=True, exist_ok=True)
    (keeper / "Cookies").write_bytes(b"keep")
    with db.get_db() as conn:
        conn.execute("UPDATE profiles SET user_data_dir = ? WHERE id = ?", (str(root), profile["id"]))
        conn.commit()

    res = app_client.post(f"/api/profiles/{profile['id']}/burn", json={"confirm": True})

    assert res.status_code == 200, res.text
    assert (keeper / "Cookies").exists()


def test_burn_refuses_non_disposable_profile(app_client: TestClient):
    res = app_client.post("/api/profiles", json={"name": "普通画像"})
    assert res.status_code == 201
    profile = res.json()
    assert profile["disposable"] is False
    burn = app_client.post(f"/api/profiles/{profile['id']}/burn", json={"confirm": True})
    assert burn.status_code == 400
    assert app_client.get(f"/api/profiles/{profile['id']}").status_code == 200


def test_burn_unknown_profile_is_404(app_client: TestClient):
    res = app_client.post("/api/profiles/does-not-exist/burn", json={"confirm": True})
    assert res.status_code == 404


def test_burn_stops_running_profile_and_drops_cookie_pull_state(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch,
):
    profile = _create_disposable(app_client)
    pid = profile["id"]
    stop = AsyncMock()
    monkeypatch.setattr(main.browser_mgr, "stop", stop)
    main.browser_mgr.running[pid] = object()  # type: ignore[assignment]
    main.browser_mgr.cookie_pulls.register_token(pid)
    try:
        res = app_client.post(f"/api/profiles/{pid}/burn", json={"confirm": True})
    finally:
        main.browser_mgr.running.pop(pid, None)
    assert res.status_code == 200, res.text
    assert res.json()["was_running"] is True
    stop.assert_awaited_once_with(pid)
    assert not main.browser_mgr.cookie_pulls.has_token(pid)


def test_disposable_still_supports_soft_delete_and_restore(app_client: TestClient):
    profile = _create_disposable(app_client)
    pid = profile["id"]
    assert app_client.delete(f"/api/profiles/{pid}").status_code == 200
    trash = app_client.get("/api/profiles/trash").json()
    assert any(p["id"] == pid for p in trash)
    restored = app_client.post(f"/api/profiles/{pid}/restore")
    assert restored.status_code == 200
    assert restored.json()["disposable"] is True
