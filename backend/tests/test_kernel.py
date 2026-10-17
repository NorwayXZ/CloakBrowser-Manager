"""Kernel center: license-aware updates, cached versions, settings."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from backend import kernel, main
from backend.cloak_runtime import CloakRuntimeInfo

FREE_KEY = ({"tier": "free", "valid": True}, True)
PAID_KEY = ({"tier": "pro", "valid": True, "expires": "2027-01-01"}, True)
NO_KEY = ({"tier": "free"}, False)


@pytest.fixture()
def wrapper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Fake the cloakbrowser submodules the kernel center calls into."""
    cache = tmp_path / "cache"
    cache.mkdir()
    state = types.SimpleNamespace(license=NO_KEY, effective={"version": "146.0.7680.177.5"}, cache=cache)

    cli = types.ModuleType("cloakbrowser.__main__")
    cli._resolve_license = lambda: state.license
    cli._effective_binary = lambda entitled, quick=True: {
        "pinned": False,
        "bundled_version": "146.0.7680.177.5",
        "installed": True,
        **state.effective,
    }
    download = types.ModuleType("cloakbrowser.download")
    download.check_for_update = MagicMock(return_value=None)
    download.check_for_pro_update = MagicMock(return_value=None)
    download._get_latest_chromium_version = MagicMock(return_value="146.0.7680.177.5")
    license_mod = types.ModuleType("cloakbrowser.license")
    license_mod.resolve_license_key = lambda _key=None: "cb_test"
    license_mod.get_pro_latest_release = MagicMock(
        return_value=types.SimpleNamespace(version="155.0.1.1.1")
    )
    for name, mod in {
        "cloakbrowser.__main__": cli,
        "cloakbrowser.download": download,
        "cloakbrowser.license": license_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    config = sys.modules["cloakbrowser.config"]
    monkeypatch.setattr(config, "get_cache_dir", lambda: cache, raising=False)
    monkeypatch.setattr(config, "get_platform_tag", lambda: "darwin-arm64", raising=False)
    monkeypatch.setattr(
        config,
        "_version_newer",
        lambda a, b: tuple(map(int, a.split("."))) > tuple(map(int, b.split("."))),
        raising=False,
    )
    monkeypatch.setattr(config, "normalize_requested_version", lambda v: v.strip(), raising=False)
    for env in (kernel.ENV_AUTO_UPDATE, kernel.ENV_RELEASE_CHANNEL, kernel.ENV_PINNED_VERSION):
        monkeypatch.delenv(env, raising=False)
    state.download = download
    state.license_mod = license_mod
    return state


def _verified(version: str, verified: bool = True):
    return lambda *, ensure_binary: CloakRuntimeInfo(
        wrapper_version="0.6.2",
        configured_version="146.0.7680.177.5",
        effective_version=version,
        platform="darwin-arm64",
        binary_path=Path(f"/cache/chromium-{version}/Chromium"),
        binary_version=version if verified else "145.0.0.0",
        binary_verified=verified,
    )


def _make_kernel(cache: Path, name: str, size: int = 10) -> None:
    (cache / name).mkdir()
    (cache / name / "chrome").write_bytes(b"x" * size)


# ── Update ───────────────────────────────────────────────────────────────────


def test_keyed_update_uses_the_pro_channel_not_the_free_one(
    app_client: TestClient, wrapper, monkeypatch: pytest.MonkeyPatch,
):
    wrapper.license = FREE_KEY
    wrapper.effective = {"version": "154.0.8037.57.1"}
    wrapper.download.check_for_pro_update.return_value = "155.0.1.1.1"
    monkeypatch.setattr(kernel, "inspect_cloak_runtime", _verified("155.0.1.1.1"))

    resp = app_client.post("/api/kernel/update")

    assert resp.status_code == 200
    wrapper.download.check_for_pro_update.assert_called_once_with("cb_test", "stable")
    wrapper.download.check_for_update.assert_not_called()
    body = resp.json()
    assert body["updated"] is True
    assert body["current_version"] == "154.0.8037.57.1"
    assert body["installed_version"] == "155.0.1.1.1"
    assert body["restart_required"] is True


def test_keyless_update_uses_the_free_channel(app_client: TestClient, wrapper, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(kernel, "inspect_cloak_runtime", _verified("146.0.7680.177.5"))

    resp = app_client.post("/api/browser/update")

    assert resp.status_code == 200
    wrapper.download.check_for_update.assert_called_once_with()
    wrapper.download.check_for_pro_update.assert_not_called()
    assert resp.json()["updated"] is False
    assert "已是最新" in resp.json()["message"]


def test_update_fails_when_the_downloaded_binary_does_not_verify(
    app_client: TestClient, wrapper, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(kernel, "inspect_cloak_runtime", _verified("150.0.0.0.1", verified=False))

    resp = app_client.post("/api/kernel/update")

    assert resp.status_code == 502
    assert "未通过版本核对" in resp.json()["detail"]


def test_pinned_kernel_is_not_replaced_by_update(app_client: TestClient, wrapper, monkeypatch: pytest.MonkeyPatch):
    main.db.set_setting(kernel.SETTING_PINNED_VERSION, "146.0.7680.177.5")
    monkeypatch.setattr(kernel, "inspect_cloak_runtime", _verified("146.0.7680.177.5"))

    resp = app_client.post("/api/kernel/update")

    assert resp.status_code == 200
    wrapper.download.check_for_update.assert_not_called()
    assert "已锁定" in resp.json()["message"]


# ── Check ────────────────────────────────────────────────────────────────────


def test_check_reports_newer_pro_build(app_client: TestClient, wrapper):
    wrapper.license = FREE_KEY
    wrapper.effective = {"version": "154.0.8037.57.1"}

    resp = app_client.post("/api/kernel/check")

    assert resp.status_code == 200
    assert resp.json() == {
        "current_version": "154.0.8037.57.1",
        "latest_version": "155.0.1.1.1",
        "update_available": True,
        "pinned": False,
    }


def test_check_reports_offline_server(app_client: TestClient, wrapper):
    wrapper.download._get_latest_chromium_version.return_value = None

    resp = app_client.post("/api/kernel/check")

    assert resp.status_code == 502
    assert "发布服务器" in resp.json()["detail"]


# ── Overview ─────────────────────────────────────────────────────────────────


def test_overview_lists_cached_kernels_and_marks_the_one_in_use(app_client: TestClient, wrapper):
    wrapper.license = FREE_KEY
    in_use = wrapper.cache / "chromium-154.0.8037.57.1-pro"
    wrapper.effective = {"version": "154.0.8037.57.1", "cache_dir": str(in_use)}
    _make_kernel(wrapper.cache, "chromium-145.0.7632.109.2", size=5)
    _make_kernel(wrapper.cache, "chromium-154.0.8037.57.1-pro", size=7)
    (wrapper.cache / "geoip").mkdir()
    (wrapper.cache / "license.key").write_text("secret")

    resp = app_client.get("/api/kernel")

    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "154.0.8037.57.1"
    assert body["license"] == {"tier": "free", "plan": "free", "expires": None, "can_pin": False}
    assert "secret" not in resp.text
    assert [(k["name"], k["pro"], k["size_bytes"], k["in_use"]) for k in body["installed_kernels"]] == [
        ("chromium-154.0.8037.57.1-pro", True, 7, True),
        ("chromium-145.0.7632.109.2", False, 5, False),
    ]
    assert body["settings"] == {"auto_update": True, "release_channel": "stable", "pinned_version": None}


def test_paid_and_keyless_licenses_can_pin(wrapper):
    wrapper.license = PAID_KEY
    assert kernel.resolve_license().tier == "paid"
    assert kernel.resolve_license().can_pin is True
    wrapper.license = NO_KEY
    assert kernel.resolve_license().tier == "none"
    assert kernel.resolve_license().can_pin is True
    wrapper.license = ({"tier": "invalid", "valid": False}, False)
    assert kernel.resolve_license().can_pin is False


# ── Settings ─────────────────────────────────────────────────────────────────


def test_settings_are_saved_and_exported_to_the_wrapper_env(app_client: TestClient, wrapper):
    import os

    wrapper.license = PAID_KEY
    resp = app_client.put("/api/kernel/settings", json={
        "auto_update": False, "release_channel": "preview", "pinned_version": "154.0.8037.57.1",
    })

    assert resp.status_code == 200
    assert resp.json()["settings"]["pinned_version"] == "154.0.8037.57.1"
    assert os.environ[kernel.ENV_AUTO_UPDATE] == "false"
    assert os.environ[kernel.ENV_RELEASE_CHANNEL] == "preview"
    assert os.environ[kernel.ENV_PINNED_VERSION] == "154.0.8037.57.1"

    resp = app_client.put("/api/kernel/settings", json={"auto_update": True, "release_channel": "stable"})
    assert resp.json()["settings"]["pinned_version"] is None
    assert kernel.ENV_AUTO_UPDATE not in os.environ
    assert kernel.ENV_RELEASE_CHANNEL not in os.environ
    assert kernel.ENV_PINNED_VERSION not in os.environ
    assert main.db.get_setting(kernel.SETTING_PINNED_VERSION) is None


def test_free_key_cannot_pin(app_client: TestClient, wrapper):
    wrapper.license = FREE_KEY

    resp = app_client.put("/api/kernel/settings", json={"pinned_version": "154.0.8037.57.1"})

    assert resp.status_code == 400
    assert "不能锁定" in resp.json()["detail"]


def test_env_set_by_hand_survives_until_settings_are_saved(monkeypatch: pytest.MonkeyPatch, tmp_db: Path):
    environ = {kernel.ENV_AUTO_UPDATE: "false"}
    assert kernel.has_saved_settings(main.db.get_setting) is False
    main.db.set_setting(kernel.SETTING_AUTO_UPDATE, "true")
    assert kernel.has_saved_settings(main.db.get_setting) is True
    kernel.apply_settings(kernel.read_settings(main.db.get_setting), environ)
    assert environ == {}


# ── Delete ───────────────────────────────────────────────────────────────────


def test_delete_old_kernel_frees_space(app_client: TestClient, wrapper):
    wrapper.effective = {"version": "146.0.7680.177.5", "cache_dir": str(wrapper.cache / "chromium-146.0.7680.177.5")}
    _make_kernel(wrapper.cache, "chromium-145.0.7632.109.2", size=9)

    resp = app_client.delete("/api/kernel/versions/chromium-145.0.7632.109.2")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "freed_bytes": 9}
    assert not (wrapper.cache / "chromium-145.0.7632.109.2").exists()


def test_delete_refuses_the_kernel_in_use(app_client: TestClient, wrapper):
    name = "chromium-146.0.7680.177.5"
    wrapper.effective = {"version": "146.0.7680.177.5", "cache_dir": str(wrapper.cache / name)}
    _make_kernel(wrapper.cache, name)

    resp = app_client.delete(f"/api/kernel/versions/{name}")

    assert resp.status_code == 400
    assert (wrapper.cache / name).exists()


@pytest.mark.parametrize("name", ["geoip", "license.key", "chromium-..", "chromium-1.2.3.4-pro.bak"])
def test_delete_only_touches_kernel_folders(app_client: TestClient, wrapper, name: str):
    resp = app_client.delete(f"/api/kernel/versions/{name}")
    assert resp.status_code in {400, 404}


def test_delete_waits_for_browsers_to_close(app_client: TestClient, wrapper, monkeypatch: pytest.MonkeyPatch):
    _make_kernel(wrapper.cache, "chromium-145.0.7632.109.2")
    monkeypatch.setitem(main.browser_mgr.running, "p1", MagicMock())

    resp = app_client.delete("/api/kernel/versions/chromium-145.0.7632.109.2")

    assert resp.status_code == 409
    assert (wrapper.cache / "chromium-145.0.7632.109.2").exists()


def test_same_pro_build_is_not_reported_as_an_update(
    app_client: TestClient, wrapper, monkeypatch: pytest.MonkeyPatch,
):
    wrapper.license = FREE_KEY
    wrapper.effective = {"version": "154.0.8037.57.1"}
    monkeypatch.setattr(kernel, "inspect_cloak_runtime", lambda *, ensure_binary: CloakRuntimeInfo(
        wrapper_version="0.6.2",
        configured_version="146.0.7680.177.5",
        effective_version="154.0.8037.57.1",
        platform="darwin-arm64",
        binary_path=Path("/cache/chromium-154.0.8037.57.1-pro/Chromium"),
        binary_version="154.0.8037.57.1-pro",
        binary_verified=True,
    ))

    resp = app_client.post("/api/kernel/update")

    assert resp.status_code == 200
    assert resp.json()["updated"] is False
    assert resp.json()["restart_required"] is False
    assert "已是最新" in resp.json()["message"]
