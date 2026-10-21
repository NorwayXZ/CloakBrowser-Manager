"""Tests for the Windows device template library and its API endpoints."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from backend import device_templates
from backend.device_templates import (
    FAMILIES,
    get_template,
    list_templates,
    pick_template,
    random_template,
    validate_template,
)


def test_template_count_at_least_100():
    assert len(list_templates()) >= 100


def test_template_ids_unique():
    ids = [t["id"] for t in list_templates()]
    assert len(ids) == len(set(ids))


def test_all_templates_pass_validation():
    errors = [e for t in list_templates() for e in validate_template(t)]
    assert errors == []


def test_templates_cover_required_gpu_families():
    assert set(FAMILIES) == {
        "nvidia-rtx40", "nvidia-rtx30", "nvidia-gtx16", "nvidia-rtx20",
        "intel-igpu", "amd-radeon", "qualcomm",
    }
    by_family = {}
    for t in list_templates():
        by_family.setdefault(t["family"], []).append(t)
    for family in FAMILIES:
        assert by_family.get(family), f"family {family} has no templates"


def test_required_gpu_models_present():
    renderers = " | ".join(t["gpu_renderer"] for t in list_templates())
    for model in (
        "RTX 4060", "RTX 4070", "RTX 4080", "RTX 4090",
        "RTX 3050", "RTX 3060", "RTX 3070",
        "GTX 1650", "GTX 1660", "RTX 2060",
        "Iris(R) Xe", "UHD Graphics 620", "UHD Graphics 630",
        "UHD Graphics 730", "UHD Graphics 770", "Arc(TM) A370M",
        "780M", "680M", "660M", "RX 6600", "RX 7600", "6650M", "Vega 8",
        "Adreno(TM) X1",
    ):
        assert model in renderers, f"GPU model {model} missing from library"


def test_get_template_known_and_unknown():
    tpl = get_template("win-rtx4060-laptop-1920x1080-01")
    assert tpl is not None
    assert tpl["gpu_vendor"] == "Google Inc. (NVIDIA)"
    assert "RTX 4060 Laptop GPU" in tpl["gpu_renderer"]
    assert get_template("win-does-not-exist") is None


def test_pick_template_deterministic():
    assert pick_template(42) == pick_template(42)
    assert pick_template("seed-abc") == pick_template("seed-abc")
    # int wraps around the library
    n = len(list_templates())
    assert pick_template(n + 3) == pick_template(3)
    assert pick_template(-1) == pick_template(n - 1)


def test_random_template_in_library():
    ids = {t["id"] for t in list_templates()}
    for _ in range(10):
        assert random_template()["id"] in ids


def test_validate_template_catches_inconsistency():
    base = get_template("win-rtx4060-laptop-1920x1080-01")
    assert base is not None

    bad_vendor = dict(base, gpu_vendor="Google Inc. (AMD)")
    assert any("厂商不一致" in e for e in validate_template(bad_vendor))

    bad_screen = dict(base, screen_width=8000, screen_height=4000)
    assert validate_template(bad_screen)

    bad_mem = dict(base, device_memory=16)
    assert any("内存桶" in e for e in validate_template(bad_mem))

    bad_cores = dict(base, hardware_concurrency=2)
    assert any("核数" in e for e in validate_template(bad_cores))


# ── API endpoints ──────────────────────────────────────────────────────────


def test_api_list_device_templates(app_client: TestClient):
    resp = app_client.get("/api/device-templates")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 100
    first = items[0]
    for field in ("id", "name", "family", "cpu", "gpu_vendor", "gpu_renderer",
                  "screen_width", "screen_height", "hardware_concurrency",
                  "device_memory", "device_scale_factor"):
        assert field in first, f"missing field {field}"


def test_api_list_device_templates_family_filter(app_client: TestClient):
    resp = app_client.get("/api/device-templates", params={"family": "qualcomm"})
    assert resp.status_code == 200
    items = resp.json()
    assert items
    assert all(i["family"] == "qualcomm" for i in items)


def test_api_list_device_templates_q_filter(app_client: TestClient):
    resp = app_client.get("/api/device-templates", params={"q": "RTX 4090"})
    assert resp.status_code == 200
    items = resp.json()
    assert items
    assert all("RTX 4090" in i["gpu_renderer"] for i in items)


def test_api_get_device_template(app_client: TestClient):
    resp = app_client.get("/api/device-templates/win-rtx4060-laptop-1920x1080-01")
    assert resp.status_code == 200
    assert resp.json()["gpu_vendor"] == "Google Inc. (NVIDIA)"


def test_api_get_device_template_not_found(app_client: TestClient):
    resp = app_client.get("/api/device-templates/win-nope-0000-00")
    assert resp.status_code == 404


def test_api_apply_device_template_end_to_end(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Template Apply"})
    assert create.status_code == 201
    pid = create.json()["id"]

    tpl = get_template("win-rtx4060-laptop-1920x1080-01")
    assert tpl is not None

    resp = app_client.post(
        f"/api/profiles/{pid}/apply-device-template",
        json={"template_id": tpl["id"]},
    )
    assert resp.status_code == 200
    applied = resp.json()
    assert applied["platform"] == "windows"
    assert applied["screen_width"] == tpl["screen_width"]
    assert applied["screen_height"] == tpl["screen_height"]
    assert applied["gpu_vendor"] == tpl["gpu_vendor"]
    assert applied["gpu_renderer"] == tpl["gpu_renderer"]
    assert applied["hardware_concurrency"] == tpl["hardware_concurrency"]
    assert applied["device_memory"] == tpl["device_memory"]
    assert applied["device_profile"] == tpl["id"]

    # Fields stay pinned on a fresh read.
    reread = app_client.get(f"/api/profiles/{pid}").json()
    assert reread["gpu_renderer"] == tpl["gpu_renderer"]
    assert reread["device_profile"] == tpl["id"]


def test_api_apply_device_template_unknown_template(app_client: TestClient):
    pid = app_client.post("/api/profiles", json={"name": "Bad Template"}).json()["id"]
    resp = app_client.post(
        f"/api/profiles/{pid}/apply-device-template",
        json={"template_id": "win-nope-0000-00"},
    )
    assert resp.status_code == 404


def test_api_apply_device_template_unknown_profile(app_client: TestClient):
    resp = app_client.post(
        "/api/profiles/nonexistent/apply-device-template",
        json={"template_id": "win-rtx4060-laptop-1920x1080-01"},
    )
    assert resp.status_code == 404


def test_api_apply_device_template_validation(app_client: TestClient):
    pid = app_client.post("/api/profiles", json={"name": "Validation"}).json()["id"]
    resp = app_client.post(
        f"/api/profiles/{pid}/apply-device-template",
        json={"template_id": ""},
    )
    assert resp.status_code == 422
