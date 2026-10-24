"""Disposable identities and one-sentence profiles must launch on this host.

On a native macOS or Windows host the launch preflight refuses a profile
whose platform is not the host's, so both quick-create paths have to pick
a persona from the host's own template library. The host OS is
monkeypatched, so these run the same on every CI runner.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from backend import database as db
from backend import device_templates, main
from backend.runtime import RuntimeConfig

HOSTS = ["macos", "windows"]


@pytest.fixture()
def native_host(app_client: TestClient, tmp_db: Path, monkeypatch: pytest.MonkeyPatch):
    """Switch the running app to a native desktop host of the given OS."""

    def use(host_os: str) -> TestClient:
        monkeypatch.setattr(
            main.browser_mgr, "runtime", RuntimeConfig(host_os, "native", "native-window", tmp_db),
        )
        return app_client

    return use


def _preflight_errors(profile_id: str) -> list[dict]:
    report = main.browser_mgr.preflight(db.get_profile(profile_id))
    return [issue for issue in report["issues"] if issue["severity"] == "error"]


def _assert_host_persona(profile: dict, host_os: str) -> None:
    assert profile["platform"] == host_os
    tpl = device_templates.get_template(profile["device_profile"])
    assert tpl is not None and tpl["platform"] == host_os
    assert profile["gpu_vendor"] == tpl["gpu_vendor"]
    assert profile["gpu_renderer"] == tpl["gpu_renderer"]
    assert profile["screen_width"] == tpl["screen_width"]
    assert profile["hardware_concurrency"] == tpl["hardware_concurrency"]
    assert _preflight_errors(profile["id"]) == []


# ── template library ─────────────────────────────────────────────────────


def test_platform_for_host():
    assert device_templates.platform_for_host("macos") == "macos"
    assert device_templates.platform_for_host("windows") == "windows"
    assert device_templates.platform_for_host("linux") == "windows"


def test_mac_templates_are_valid_unique_and_apple():
    mac = device_templates.list_templates("macos")
    assert len(mac) >= 40
    assert [e for t in mac for e in device_templates.validate_template(t)] == []
    all_ids = [t["id"] for t in (*mac, *device_templates.list_templates())]
    assert len(all_ids) == len(set(all_ids))
    assert all(t["gpu_vendor"] == "Google Inc. (Apple)" for t in mac)


def test_mac_template_ids_match_frontend_device_profiles():
    """The edit form recognises a Mac persona by its deviceProfiles.ts id."""
    source = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "deviceProfiles.ts"
    ).read_text(encoding="utf-8")
    for tpl in device_templates.list_templates("macos"):
        assert f'appleProfile("{tpl["id"]}"' in source, tpl["id"]


# ── disposable identity ──────────────────────────────────────────────────


@pytest.mark.parametrize("host_os", HOSTS)
def test_disposable_profile_passes_preflight_on_host(native_host, host_os):
    client = native_host(host_os)
    res = client.post("/api/profiles/disposable", json={})
    assert res.status_code == 201, res.text
    _assert_host_persona(res.json(), host_os)


@pytest.mark.parametrize("host_os", HOSTS)
def test_disposable_profiles_never_repeat_a_host_template(native_host, host_os):
    client = native_host(host_os)
    taken = device_templates.list_templates(host_os)[0]["id"]
    db.create_profile(name="已占用", device_profile=taken)
    ids = []
    for _ in range(6):
        res = client.post("/api/profiles/disposable", json={})
        assert res.status_code == 201, res.text
        ids.append(res.json()["device_profile"])
    assert taken not in ids
    assert len(ids) == len(set(ids))


# ── one-sentence profile ─────────────────────────────────────────────────


@pytest.mark.parametrize("host_os", HOSTS)
def test_sentence_profile_passes_preflight_on_host(native_host, host_os):
    client = native_host(host_os)
    sentence = "建个美国号，西雅图，平时喜欢露营和摄影"
    draft = client.post("/api/profiles/from-sentence/draft", json={"sentence": sentence})
    assert draft.status_code == 200, draft.text
    assembled = draft.json()["assembled"]
    assert assembled["platform"] == host_os
    assert device_templates.get_template(assembled["device_profile"])["platform"] == host_os

    res = client.post(
        "/api/profiles/from-sentence", json={"sentence": sentence, "assembled": assembled},
    )
    assert res.status_code == 201, res.text
    profile = res.json()
    assert profile["device_profile"] == assembled["device_profile"]
    assert profile["warnings"] == []
    _assert_host_persona(profile, host_os)


@pytest.mark.parametrize("host_os", HOSTS)
def test_sentence_confirm_swaps_a_foreign_platform_template(native_host, host_os):
    client = native_host(host_os)
    sentence = "建个美国号，西雅图"
    assembled = client.post(
        "/api/profiles/from-sentence/draft", json={"sentence": sentence},
    ).json()["assembled"]
    foreign = "macos" if host_os == "windows" else "windows"
    assembled["device_profile"] = device_templates.list_templates(foreign)[0]["id"]
    assembled["platform"] = foreign

    res = client.post(
        "/api/profiles/from-sentence", json={"sentence": sentence, "assembled": assembled},
    )
    assert res.status_code == 201, res.text
    profile = res.json()
    assert any("不能在这台电脑上启动" in w for w in profile["warnings"])
    _assert_host_persona(profile, host_os)


@pytest.mark.parametrize("host_os", HOSTS)
def test_template_picker_lists_the_host_library(native_host, host_os):
    client = native_host(host_os)
    items = client.get("/api/device-templates").json()
    assert items and all(item["platform"] == host_os for item in items)
    other = "macos" if host_os == "windows" else "windows"
    explicit = client.get("/api/device-templates", params={"platform": other}).json()
    assert explicit and all(item["platform"] == other for item in explicit)
    assert client.get("/api/device-templates", params={"platform": "linux"}).status_code == 422


def test_apply_mac_template_sets_macos_platform(native_host):
    client = native_host("macos")
    profile = db.create_profile(name="改成 Mac")
    res = client.post(
        f"/api/profiles/{profile['id']}/apply-device-template",
        json={"template_id": "mbp_14_m3_pro_2023"},
    )
    assert res.status_code == 200, res.text
    _assert_host_persona(res.json(), "macos")
