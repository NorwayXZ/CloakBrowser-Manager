"""Tests for FastAPI routes via TestClient."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from backend import main
from backend.browser_manager import RunningProfile
from backend.cloak_runtime import CloakRuntimeInfo
from backend.runtime import RuntimeConfig


# ── Profile CRUD ─────────────────────────────────────────────────────────────


def test_list_profiles_empty(app_client: TestClient):
    resp = app_client.get("/api/profiles")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_profile(app_client: TestClient):
    resp = app_client.post("/api/profiles", json={"name": "Test"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test"
    assert data["status"] == "stopped"
    assert data["humanize"] is True
    assert "id" in data
    assert len(data["id"]) == 36  # UUID


def test_create_profile_with_all_fields(app_client: TestClient):
    resp = app_client.post("/api/profiles", json={
        "name": "Full",
        "fingerprint_seed": 42,
        "proxy": "http://host:8080",
        "platform": "macos",
        "screen_width": 2560,
        "screen_height": 1440,
        "humanize": True,
        "human_preset": "careful",
        "tags": [{"tag": "work", "color": "#ff0000"}],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["fingerprint_seed"] == 42
    assert data["platform"] == "macos"
    assert len(data["tags"]) == 1


def test_create_profile_invalid_platform(app_client: TestClient):
    resp = app_client.post("/api/profiles", json={"name": "Bad", "platform": "android"})
    assert resp.status_code == 422


def test_get_profile(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Get Me"})
    pid = create.json()["id"]
    resp = app_client.get(f"/api/profiles/{pid}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Get Me"


def test_get_profile_not_found(app_client: TestClient):
    resp = app_client.get("/api/profiles/nonexistent")
    assert resp.status_code == 404


def test_profile_start_page(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Start Page"})
    profile_id = create.json()["id"]

    resp = app_client.get(f"/profile/{profile_id}/start")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Start Page" in resp.text
    assert "代理出口 IP" in resp.text
    assert "直连（本地网络）" in resp.text
    assert "Whoer" in resp.text


def test_update_profile(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Original"})
    pid = create.json()["id"]
    resp = app_client.put(f"/api/profiles/{pid}", json={"name": "Renamed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"


def test_update_profile_not_found(app_client: TestClient):
    resp = app_client.put("/api/profiles/nonexistent", json={"name": "x"})
    assert resp.status_code == 404


def test_delete_profile(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Delete Me"})
    pid = create.json()["id"]
    resp = app_client.delete(f"/api/profiles/{pid}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # Confirm gone
    assert app_client.get(f"/api/profiles/{pid}").status_code == 404


def test_delete_profile_not_found(app_client: TestClient):
    resp = app_client.delete("/api/profiles/nonexistent")
    assert resp.status_code == 404


def test_create_proxy_preset_with_socks5_auth(app_client: TestClient):
    resp = app_client.post("/api/proxy-presets", json={
        "name": "美国",
        "mode": "socks5",
        "proxy": "socks5://user:pass@192.168.0.1:8000",
    })

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "美国"
    assert data["proxy"] == "socks5://user:pass@192.168.0.1:8000"


def test_create_proxy_presets_bulk(app_client: TestClient):
    resp = app_client.post("/api/proxy-presets/bulk", json={
        "items": [
            {"name": "美国 1", "mode": "socks5", "proxy": "192.168.0.1:8000:user:pass"},
            {"name": "美国 2", "mode": "http", "proxy": "http://proxy.example:8080"},
        ],
    })

    assert resp.status_code == 201
    data = resp.json()
    assert len(data) == 2
    assert data[0]["proxy"] == "socks5://user:pass@192.168.0.1:8000"
    assert data[1]["proxy"] == "http://proxy.example:8080"


def test_delete_profile_stops_running(app_client: TestClient):
    """Deleting a running profile should stop it first."""
    create = app_client.post("/api/profiles", json={"name": "Running"})
    pid = create.json()["id"]

    # Inject mock running profile
    mock_running = MagicMock(spec=RunningProfile)
    mock_running.display = 100
    mock_running.ws_port = 6100
    mock_running.cdp_port = 5100
    main.browser_mgr.running[pid] = mock_running
    main.browser_mgr.stop = AsyncMock()

    resp = app_client.delete(f"/api/profiles/{pid}")
    assert resp.status_code == 200
    main.browser_mgr.stop.assert_called_once_with(pid)


# ── Profile Status ───────────────────────────────────────────────────────────


def test_get_profile_status_stopped(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Status"})
    pid = create.json()["id"]
    resp = app_client.get(f"/api/profiles/{pid}/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_get_profile_status_not_found(app_client: TestClient):
    resp = app_client.get("/api/profiles/nonexistent/status")
    assert resp.status_code == 404


def test_profile_response_reports_viewer_capability(app_client: TestClient):
    response = app_client.post("/api/profiles", json={"name": "Runtime"})
    assert response.status_code == 201
    assert response.json()["runtime_mode"] == "docker"
    assert response.json()["viewer_mode"] == "vnc"


# ── Launch / Stop ────────────────────────────────────────────────────────────


def test_launch_not_found(app_client: TestClient):
    resp = app_client.post("/api/profiles/nonexistent/launch")
    assert resp.status_code == 404


def test_launch_already_running(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Running"})
    pid = create.json()["id"]
    # Inject into running dict
    main.browser_mgr.running[pid] = MagicMock(spec=RunningProfile)
    resp = app_client.post(f"/api/profiles/{pid}/launch")
    assert resp.status_code == 409
    # Cleanup
    main.browser_mgr.running.pop(pid, None)


def test_launch_invalid_proxy_400(app_client: TestClient):
    """ValueError from browser_mgr.launch should map to 400."""
    create = app_client.post("/api/profiles", json={"name": "BadProxy"})
    pid = create.json()["id"]
    main.browser_mgr.launch = AsyncMock(side_effect=ValueError("Invalid proxy scheme 'ftp'"))
    resp = app_client.post(f"/api/profiles/{pid}/launch")
    assert resp.status_code == 400
    assert "ftp" in resp.json()["detail"]


def test_launch_defaults_to_manual_mode(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Manual"})
    pid = create.json()["id"]
    running = RunningProfile(pid, None, None, launch_mode="manual")
    main.browser_mgr.launch = AsyncMock(return_value=running)

    resp = app_client.post(f"/api/profiles/{pid}/launch")

    assert resp.status_code == 200
    main.browser_mgr.launch.assert_awaited_once()
    assert main.browser_mgr.launch.await_args.kwargs["launch_mode"] == "manual"
    assert resp.json()["cdp_url"] is None
    assert resp.json()["launch_mode"] == "manual"


def test_launch_accepts_debug_mode(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Debug"})
    pid = create.json()["id"]
    running = RunningProfile(pid, MagicMock(), 53123, launch_mode="debug")
    main.browser_mgr.launch = AsyncMock(return_value=running)

    resp = app_client.post(f"/api/profiles/{pid}/launch", json={"launch_mode": "debug"})

    assert resp.status_code == 200
    assert main.browser_mgr.launch.await_args.kwargs["launch_mode"] == "debug"
    assert resp.json()["cdp_url"] == f"/api/profiles/{pid}/cdp"
    assert resp.json()["launch_mode"] == "debug"


def test_launch_failure_500(app_client: TestClient):
    """Generic exception from browser_mgr.launch should map to 500."""
    create = app_client.post("/api/profiles", json={"name": "Crash"})
    pid = create.json()["id"]
    main.browser_mgr.launch = AsyncMock(side_effect=RuntimeError("Xvnc failed"))
    resp = app_client.post(f"/api/profiles/{pid}/launch")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to launch browser"


def test_license_launch_failure_returns_actionable_conflict(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "License limited"})
    pid = create.json()["id"]
    reason = "启动失败：授权并发已满，请先关闭其他伪装画像（免费版仅支持 1 个）"
    main.browser_mgr.launch = AsyncMock(side_effect=main.BrowserLaunchError(reason))

    resp = app_client.post(f"/api/profiles/{pid}/launch")

    assert resp.status_code == 409
    assert resp.json()["detail"] == reason
    assert main.db.get_profile(pid)["last_exit_reason"] == reason


def test_native_launch_has_no_vnc_display(
    app_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    create = app_client.post("/api/profiles", json={"name": "Native"})
    pid = create.json()["id"]
    monkeypatch.setattr(
        main.browser_mgr,
        "runtime",
        RuntimeConfig("windows", "native", "native-window", Path("C:/data")),
    )
    running = RunningProfile(pid, MagicMock(), 53123)
    monkeypatch.setattr(main.browser_mgr, "launch", AsyncMock(return_value=running))

    response = app_client.post(f"/api/profiles/{pid}/launch")

    assert response.status_code == 200
    assert response.json()["viewer_mode"] == "native-window"
    assert response.json()["vnc_ws_port"] is None
    assert response.json()["display"] is None


def test_stop_not_running(app_client: TestClient):
    resp = app_client.post("/api/profiles/nonexistent/stop")
    assert resp.status_code == 404


# ── System Status ────────────────────────────────────────────────────────────


def test_system_status(app_client: TestClient):
    # Clear any leaked running profiles from prior tests
    main.browser_mgr.running.clear()

    # Create a profile so profiles_total > 0
    app_client.post("/api/profiles", json={"name": "Status Test"})
    resp = app_client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running_count"] == 0
    assert data["binary_version"] == "0.0.0-test"
    assert data["profiles_total"] >= 1


def test_profile_preflight_reports_capabilities(app_client: TestClient):
    created = app_client.post("/api/profiles", json={"name": "Preflight"}).json()
    response = app_client.get(f"/api/profiles/{created['id']}/preflight")

    assert response.status_code == 200
    data = response.json()
    assert data["can_launch"] is True
    assert data["capabilities"]["tls_externally_verified"] is False


@dataclass
class FakeUpdateResult:
    ok: bool = True
    updated: bool = True
    before: str | None = "old123"
    after: str | None = "new456"
    branch: str | None = "main"
    restart_required: bool = True
    message: str = "已升级"
    log: list[str] | None = None

    def __post_init__(self):
        if self.log is None:
            self.log = ["$ git pull --ff-only"]


def test_update_manager(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "update_from_git", lambda _root: FakeUpdateResult())

    resp = app_client.post("/api/update")

    assert resp.status_code == 200
    data = resp.json()
    assert data["updated"] is True
    assert data["restart_required"] is True
    assert data["after"] == "new456"


def test_update_manager_conflict(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    def fail(_root):
        raise main.UpdateError("本地代码有未提交改动")

    monkeypatch.setattr(main, "update_from_git", fail)

    resp = app_client.post("/api/update")

    assert resp.status_code == 409
    assert "未提交改动" in resp.json()["detail"]


def test_browser_update_reports_current_platform_version(
    app_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import cloakbrowser
    monkeypatch.setattr(cloakbrowser, "check_for_update", lambda: None, raising=False)
    monkeypatch.setattr(main, "get_effective_chromium_version", lambda: "145.0.0.0")
    monkeypatch.setattr(
        main,
        "inspect_cloak_runtime",
        lambda *, ensure_binary: CloakRuntimeInfo(
            wrapper_version="0.5.7",
            configured_version="145.0.0.0",
            effective_version="145.0.0.0",
            platform="darwin-arm64",
            binary_path=Path("/cache/chromium-145.0.0.0/Chromium"),
            binary_version="145.0.0.0",
            binary_verified=True,
        ),
    )

    resp = app_client.post("/api/browser/update")

    assert resp.status_code == 200
    assert resp.json()["updated"] is False
    assert resp.json()["current_version"] == "145.0.0.0"
    assert resp.json()["installed_version"] == "145.0.0.0"
    assert resp.json()["binary_verified"] is True


def test_browser_update_reports_new_effective_and_installed_version(
    app_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import cloakbrowser

    monkeypatch.setattr(cloakbrowser, "check_for_update", lambda: "150.0.0.0.1", raising=False)
    monkeypatch.setattr(main, "get_effective_chromium_version", lambda: "145.0.0.0.1")
    monkeypatch.setattr(
        main,
        "inspect_cloak_runtime",
        lambda *, ensure_binary: CloakRuntimeInfo(
            wrapper_version="0.5.7",
            configured_version="145.0.0.0.1",
            effective_version="150.0.0.0.1",
            platform="windows-x64",
            binary_path=Path("C:/cache/chromium-150.0.0.0.1/chrome.exe"),
            binary_version="150.0.0.0.1",
            binary_verified=True,
        ),
    )

    resp = app_client.post("/api/browser/update")

    assert resp.status_code == 200
    assert resp.json()["updated"] is True
    assert resp.json()["available_version"] == "150.0.0.0.1"
    assert resp.json()["installed_version"] == "150.0.0.0.1"
    assert resp.json()["restart_required"] is True


def test_browser_update_fails_when_downloaded_binary_version_is_stale(
    app_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import cloakbrowser

    monkeypatch.setattr(cloakbrowser, "check_for_update", lambda: "150.0.0.0.1", raising=False)
    monkeypatch.setattr(main, "get_effective_chromium_version", lambda: "145.0.0.0.1")
    monkeypatch.setattr(
        main,
        "inspect_cloak_runtime",
        lambda *, ensure_binary: CloakRuntimeInfo(
            wrapper_version="0.5.7",
            configured_version="145.0.0.0.1",
            effective_version="150.0.0.0.1",
            platform="windows-x64",
            binary_path=Path("C:/cache/chromium-145.0.0.0.1/chrome.exe"),
            binary_version="145.0.0.0.1",
            binary_verified=False,
        ),
    )

    resp = app_client.post("/api/browser/update")

    assert resp.status_code == 502
    assert "未通过版本核对" in resp.json()["detail"]


# ── Launch Args ─────────────────────────────────────────────────────────────


def test_profile_launch_args_default_empty(app_client: TestClient):
    resp = app_client.post("/api/profiles", json={"name": "NoArgs"})
    assert resp.status_code == 201
    assert resp.json()["launch_args"] == []


def test_profile_launch_args_create(app_client: TestClient):
    resp = app_client.post("/api/profiles", json={
        "name": "WithArgs",
        "launch_args": ["--load-extension=/data/ext", "--disable-features=Foo"],
    })
    assert resp.status_code == 201
    assert resp.json()["launch_args"] == ["--load-extension=/data/ext", "--disable-features=Foo"]


def test_profile_launch_args_update(app_client: TestClient):
    resp = app_client.post("/api/profiles", json={"name": "UpdateArgs"})
    pid = resp.json()["id"]
    resp = app_client.put(f"/api/profiles/{pid}", json={"launch_args": ["--new-flag"]})
    assert resp.status_code == 200
    assert resp.json()["launch_args"] == ["--new-flag"]


def test_profile_launch_args_get(app_client: TestClient):
    resp = app_client.post("/api/profiles", json={
        "name": "GetArgs",
        "launch_args": ["--flag"],
    })
    pid = resp.json()["id"]
    resp = app_client.get(f"/api/profiles/{pid}")
    assert resp.json()["launch_args"] == ["--flag"]


def test_purge_deleted_profile_removes_it_from_trash(app_client: TestClient):
    created = app_client.post("/api/profiles", json={"name": "Trash me"}).json()
    profile_id = created["id"]
    assert app_client.delete(f"/api/profiles/{profile_id}").status_code == 200
    assert any(item["id"] == profile_id for item in app_client.get("/api/profiles/trash").json())

    response = app_client.delete(f"/api/profiles/{profile_id}/purge")

    assert response.status_code == 200
    assert not any(item["id"] == profile_id for item in app_client.get("/api/profiles/trash").json())


def test_configuration_export_and_import(app_client: TestClient):
    app_client.post("/api/groups", json={"name": "美国账号"})
    app_client.post("/api/proxy-presets", json={
        "name": "US SOCKS",
        "proxy": "socks5://127.0.0.1:1080",
        "mode": "socks5",
    })
    app_client.post("/api/profiles", json={
        "name": "Portable",
        "group_name": "美国账号",
        "cookies_json": '[{"name":"sid","value":"abc","domain":"example.com"}]',
    })

    backup_response = app_client.get("/api/configuration/export")
    assert backup_response.status_code == 200
    backup = backup_response.json()
    assert backup["format"] == "cloakbrowser-manager-configuration"
    assert backup["includes_browser_user_data"] is False
    assert any(item["name"] == "Portable" for item in backup["profiles"])

    import_response = app_client.post("/api/configuration/import", json=backup)
    assert import_response.status_code == 200
    assert import_response.json()["profiles"] >= 1
    assert len([item for item in app_client.get("/api/profiles").json() if item["name"] == "Portable"]) == 2


def test_configuration_import_rejects_unknown_format(app_client: TestClient):
    response = app_client.post("/api/configuration/import", json={"format": "unknown"})
    assert response.status_code == 400


def test_configuration_import_requires_stopped_browsers(app_client: TestClient):
    created = app_client.post("/api/profiles", json={"name": "Running"}).json()
    main.browser_mgr.running[created["id"]] = MagicMock(spec=RunningProfile)
    try:
        response = app_client.post("/api/configuration/import", json={})
        assert response.status_code == 409
    finally:
        main.browser_mgr.running.pop(created["id"], None)


# ── Clipboard Sync Setting ──────────────────────────────────────────────────


def test_profile_clipboard_sync_default_true(app_client: TestClient):
    """New profiles should have clipboard_sync=true by default."""
    resp = app_client.post("/api/profiles", json={"name": "Clipboard Test"})
    assert resp.status_code == 201
    assert resp.json()["clipboard_sync"] is True


def test_profile_clipboard_sync_update(app_client: TestClient):
    """clipboard_sync can be toggled per profile."""
    resp = app_client.post("/api/profiles", json={"name": "Clipboard Toggle"})
    pid = resp.json()["id"]
    resp = app_client.put(f"/api/profiles/{pid}", json={"clipboard_sync": False})
    assert resp.status_code == 200
    assert resp.json()["clipboard_sync"] is False
    resp = app_client.put(f"/api/profiles/{pid}", json={"clipboard_sync": True})
    assert resp.json()["clipboard_sync"] is True


# ── Clipboard ────────────────────────────────────────────────────────────────


def test_set_clipboard_not_running(app_client: TestClient):
    resp = app_client.post("/api/profiles/nonexistent/clipboard", json={"text": "hello"})
    assert resp.status_code == 404


def test_get_clipboard_not_running(app_client: TestClient):
    resp = app_client.get("/api/profiles/nonexistent/clipboard")
    assert resp.status_code == 404


def test_set_clipboard_success(app_client: TestClient):
    """Mock a running profile and patch xclip subprocess."""
    create = app_client.post("/api/profiles", json={"name": "Clip"})
    pid = create.json()["id"]

    # Inject mock running profile
    mock_running = MagicMock(spec=RunningProfile)
    mock_running.display = 100
    mock_running.cdp_port = 5100
    main.browser_mgr.running[pid] = mock_running

    # Mock asyncio.create_subprocess_exec to avoid actual xclip
    mock_proc = AsyncMock()
    mock_proc.returncode = None
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.write = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdin.close = MagicMock()

    with patch("backend.main.asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        resp = app_client.post(f"/api/profiles/{pid}/clipboard", json={"text": "test clipboard"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Cleanup
    main.browser_mgr.running.pop(pid, None)


def test_get_clipboard_from_page(app_client: TestClient):
    """Mock running profile with a page that has clipboard text."""
    create = app_client.post("/api/profiles", json={"name": "ClipRead"})
    pid = create.json()["id"]

    # Mock page with clipboard text
    mock_page = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value="copied text")

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_running = MagicMock(spec=RunningProfile)
    mock_running.display = 100
    mock_running.cdp_port = 5100
    mock_running.context = mock_context
    main.browser_mgr.running[pid] = mock_running

    resp = app_client.get(f"/api/profiles/{pid}/clipboard")
    assert resp.status_code == 200
    assert resp.json()["text"] == "copied text"

    # Cleanup
    main.browser_mgr.running.pop(pid, None)


# ── Response shape ───────────────────────────────────────────────────────────


def test_profile_response_has_status_field(app_client: TestClient):
    app_client.post("/api/profiles", json={"name": "Shape"})
    resp = app_client.get("/api/profiles")
    for profile in resp.json():
        assert "status" in profile
        assert profile["status"] in ("running", "stopped")


def test_profile_response_has_cdp_url_field(app_client: TestClient):
    """Stopped profiles should have cdp_url=null."""
    app_client.post("/api/profiles", json={"name": "CdpShape"})
    resp = app_client.get("/api/profiles")
    for profile in resp.json():
        assert "cdp_url" in profile
        if profile["status"] == "stopped":
            assert profile["cdp_url"] is None


def test_status_stopped_has_cdp_url_null(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "CdpStatus"})
    pid = create.json()["id"]
    resp = app_client.get(f"/api/profiles/{pid}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cdp_url"] is None


def test_running_profile_has_cdp_url(app_client: TestClient):
    """Running profile should have a cdp_url in list/get responses."""
    create = app_client.post("/api/profiles", json={"name": "CdpRunning"})
    pid = create.json()["id"]

    mock_running = MagicMock(spec=RunningProfile)
    mock_running.display = 100
    mock_running.ws_port = 6100
    mock_running.cdp_port = 5100
    mock_running.profile_id = pid
    main.browser_mgr.running[pid] = mock_running

    resp = app_client.get(f"/api/profiles/{pid}")
    data = resp.json()
    assert data["status"] == "running"
    assert data["cdp_url"] == f"/api/profiles/{pid}/cdp"

    # Cleanup
    main.browser_mgr.running.pop(pid, None)


# ── CDP Proxy ───────────────────────────────────────────────────────────────


def test_cdp_json_version_not_running(app_client: TestClient):
    resp = app_client.get("/api/profiles/nonexistent/cdp/json/version")
    assert resp.status_code == 404


def test_cdp_json_list_not_running(app_client: TestClient):
    resp = app_client.get("/api/profiles/nonexistent/cdp/json/list")
    assert resp.status_code == 404


def _mock_running_profile(pid: str) -> MagicMock:
    """Create a mock RunningProfile and register it in browser_mgr."""
    mock = MagicMock(spec=RunningProfile)
    mock.display = 100
    mock.ws_port = 6100
    mock.cdp_port = 5100
    mock.profile_id = pid
    main.browser_mgr.running[pid] = mock
    return mock


def _passive_report_payload() -> dict:
    values = {
        "navigator": {
            "webdriver": False,
            "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0) Chrome/145.0.0.0 Safari/537.36",
            "platform": "MacIntel",
            "language": "en-US",
            "languages": ["en-US", "en"],
            "userAgentData": {"platform": "macOS"},
        },
        "intl": {
            "dateTime": {"locale": "en-US"},
            "number": {"locale": "en-US"},
            "collator": {"locale": "en-US"},
        },
        "date": {"timezone": "America/New_York"},
        "page": {"secureContext": True},
        "screen": {},
        "graphics": {"canvasHashA": "a", "canvasHashB": "a", "audioHashA": "b", "audioHashB": "b"},
        "nativeStrings": {},
    }
    return {
        "main": values,
        "iframe": values,
        "worker": values,
    }


def test_manual_profile_accepts_and_returns_passive_fingerprint_report(app_client: TestClient):
    create = app_client.post("/api/profiles", json={
        "name": "Passive report",
        "platform": "macos",
        "browser_engine": "cloakbrowser",
        "locale": "en-US",
        "timezone": "America/New_York",
    })
    pid = create.json()["id"]
    main.browser_mgr.running[pid] = RunningProfile(
        profile_id=pid,
        context=None,
        cdp_port=None,
        browser_engine="cloakbrowser",
        launch_mode="manual",
        effective_locale="en-US",
        effective_timezone="America/New_York",
    )

    submitted = app_client.post(
        f"/profile/{pid}/fingerprint-report",
        json=_passive_report_payload(),
    )
    assert submitted.status_code == 200
    report = submitted.json()
    assert report["collection"] == "passive"
    assert report["expected"]["external_cdp"] is False
    assert report["analysis"]["status"] == "pass"

    fetched = app_client.get(f"/api/profiles/{pid}/fingerprint-report")
    assert fetched.status_code == 200
    assert fetched.json()["analysis"]["status"] == "pass"
    main.browser_mgr.running.pop(pid, None)


def test_profile_start_page_embeds_automatic_passive_check(app_client: TestClient):
    create = app_client.post("/api/profiles", json={"name": "Start report"})
    pid = create.json()["id"]

    response = app_client.get(f"/profile/{pid}/start")

    assert response.status_code == 200
    assert "启动自检" in response.text
    assert f"/profile/{pid}/fingerprint-report" in response.text
    assert "const collectFingerprint = async () =>" in response.text


def test_cdp_json_version_rewrites_ws_url(app_client: TestClient):
    """GET /cdp/json/version rewrites webSocketDebuggerUrl through our proxy."""
    create = app_client.post("/api/profiles", json={"name": "CdpVer"})
    pid = create.json()["id"]
    _mock_running_profile(pid)

    chrome_response = MagicMock()
    chrome_response.json.return_value = {
        "webSocketDebuggerUrl": "ws://127.0.0.1:5100/devtools/browser/abc-123",
        "Browser": "Chrome/145.0.0.0",
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=chrome_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = app_client.get(f"/api/profiles/{pid}/cdp/json/version")

    assert resp.status_code == 200
    data = resp.json()
    assert data["webSocketDebuggerUrl"] == f"ws://testserver/api/profiles/{pid}/cdp"
    assert data["Browser"] == "Chrome/145.0.0.0"
    main.browser_mgr.running.pop(pid, None)


def test_cdp_json_version_uses_wss_behind_https(app_client: TestClient):
    """X-Forwarded-Proto: https should produce wss:// URLs."""
    create = app_client.post("/api/profiles", json={"name": "CdpWss"})
    pid = create.json()["id"]
    _mock_running_profile(pid)

    chrome_response = MagicMock()
    chrome_response.json.return_value = {
        "webSocketDebuggerUrl": "ws://127.0.0.1:5100/devtools/browser/abc",
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=chrome_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = app_client.get(
            f"/api/profiles/{pid}/cdp/json/version",
            headers={"X-Forwarded-Proto": "https"},
        )

    assert resp.status_code == 200
    assert resp.json()["webSocketDebuggerUrl"].startswith("wss://")
    main.browser_mgr.running.pop(pid, None)


def test_cdp_json_list_rewrites_page_urls(app_client: TestClient):
    """GET /cdp/json/list rewrites per-page webSocketDebuggerUrl."""
    create = app_client.post("/api/profiles", json={"name": "CdpList"})
    pid = create.json()["id"]
    _mock_running_profile(pid)

    chrome_response = MagicMock()
    chrome_response.json.return_value = [
        {
            "id": "page1",
            "webSocketDebuggerUrl": "ws://127.0.0.1:5100/devtools/page/DEADBEEF",
        },
        {
            "id": "page2",
            "title": "No WS URL",
        },
    ]
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=chrome_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = app_client.get(f"/api/profiles/{pid}/cdp/json/list")

    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["webSocketDebuggerUrl"] == (
        f"ws://testserver/api/profiles/{pid}/cdp/devtools/page/DEADBEEF"
    )
    assert "webSocketDebuggerUrl" not in data[1]
    main.browser_mgr.running.pop(pid, None)


def test_cdp_json_version_chrome_unreachable(app_client: TestClient):
    """502 when Chrome CDP endpoint is down."""
    create = app_client.post("/api/profiles", json={"name": "CdpDown"})
    pid = create.json()["id"]
    _mock_running_profile(pid)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=ConnectionError("refused"))

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = app_client.get(f"/api/profiles/{pid}/cdp/json/version")

    assert resp.status_code == 502
    main.browser_mgr.running.pop(pid, None)


# ── WebSocket Origin Validation ──────────────────────────────────────────────


def test_vnc_ws_rejects_cross_origin(app_client: TestClient):
    """VNC WebSocket should reject cross-origin browser connections."""
    create = app_client.post("/api/profiles", json={"name": "OriginVnc"})
    pid = create.json()["id"]
    _mock_running_profile(pid)

    with pytest.raises(Exception):
        with app_client.websocket_connect(
            f"/api/profiles/{pid}/vnc",
            headers={"origin": "http://evil.com"},
        ):
            pass
    main.browser_mgr.running.pop(pid, None)


def test_cdp_ws_rejects_cross_origin(app_client: TestClient):
    """CDP WebSocket should reject cross-origin browser connections."""
    create = app_client.post("/api/profiles", json={"name": "OriginCdp"})
    pid = create.json()["id"]
    _mock_running_profile(pid)

    with pytest.raises(Exception):
        with app_client.websocket_connect(
            f"/api/profiles/{pid}/cdp",
            headers={"origin": "http://evil.com"},
        ):
            pass
    main.browser_mgr.running.pop(pid, None)


def test_ws_allows_same_origin(app_client: TestClient):
    """WebSocket from same origin should pass Origin check (not get 4403)."""
    create = app_client.post("/api/profiles", json={"name": "OriginOk"})
    pid = create.json()["id"]
    _mock_running_profile(pid)

    # Same-origin passes Origin check. VNC proxy then fails to connect to
    # real KasmVNC (not running), but that's fine — we're testing Origin only.
    # The connection is accepted (no 4403), then closes due to VNC connect error.
    try:
        with app_client.websocket_connect(
            f"/api/profiles/{pid}/vnc",
            headers={"origin": "http://testserver"},
        ) as ws:
            pass  # connection accepted = Origin check passed
    except Exception as exc:
        # Any error other than 4403 means Origin check passed
        assert "4403" not in str(exc)
    main.browser_mgr.running.pop(pid, None)


def test_ws_allows_no_origin(app_client: TestClient):
    """WebSocket without Origin header (Playwright/Puppeteer) should be accepted."""
    create = app_client.post("/api/profiles", json={"name": "NoOrigin"})
    pid = create.json()["id"]
    _mock_running_profile(pid)

    try:
        with app_client.websocket_connect(f"/api/profiles/{pid}/vnc") as ws:
            pass
    except Exception as exc:
        assert "4403" not in str(exc)
    main.browser_mgr.running.pop(pid, None)
