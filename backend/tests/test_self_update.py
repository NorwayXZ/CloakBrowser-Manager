"""One-click update: asset choice, checksum, swap script, job, API."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from backend import self_update
from backend.update_job import UpdateEnv, UpdateJob

PAYLOAD = b"new app bytes" * 1000
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _release(version: str = "0.5.0", digest: str | None = f"sha256:{SHA}", extra_assets: list | None = None) -> dict:
    asset = {"name": f"CloakBrowser-Manager-{version}-abc1234-arm64.dmg", "size": len(PAYLOAD),
             "browser_download_url": "https://example.invalid/app.dmg"}
    if digest:
        asset["digest"] = digest
    return {"tag_name": f"v{version}", "assets": [asset, *(extra_assets or [])]}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ── Plan and download ────────────────────────────────────────────────────────


def test_plan_uses_github_digest():
    plan = self_update.plan_update(_release(), "arm64.dmg")
    assert (plan.version, plan.sha256, plan.size) == ("0.5.0", SHA, len(PAYLOAD))


def test_plan_falls_back_to_sha256sums():
    sums = {"name": "SHA256SUMS.txt", "browser_download_url": "https://example.invalid/sums"}
    text = f"{SHA}  CloakBrowser-Manager-0.5.0-abc1234-arm64.dmg\n{'0' * 64}  other.exe\n"
    plan = self_update.plan_update(_release(digest=None, extra_assets=[sums]), "arm64.dmg", fetch_text=lambda _u: text)
    assert plan.sha256 == SHA


def test_plan_refuses_without_any_checksum():
    with pytest.raises(self_update.UpdateError, match="校验码"):
        self_update.plan_update(_release(digest=None), "arm64.dmg")


def test_plan_refuses_when_no_asset_fits():
    with pytest.raises(self_update.UpdateError, match="适合"):
        self_update.plan_update(_release(), "windows")


def test_download_keeps_a_matching_file(tmp_path: Path):
    plan = self_update.plan_update(_release(), "arm64.dmg")
    seen = []
    path = self_update.download_verified(plan, tmp_path, progress=lambda d, t: seen.append(d),
                                         opener=lambda _u: _Response(PAYLOAD))
    assert path.read_bytes() == PAYLOAD
    assert seen[-1] == len(PAYLOAD)


def test_download_discards_a_tampered_file(tmp_path: Path):
    plan = self_update.plan_update(_release(), "arm64.dmg")
    with pytest.raises(self_update.UpdateError, match="对不上"):
        self_update.download_verified(plan, tmp_path, opener=lambda _u: _Response(PAYLOAD + b"!"))
    assert list(tmp_path.iterdir()) == []


def test_translocated_app_is_installed_where_it_really_lives(tmp_path: Path):
    home = tmp_path / "home"
    (home / "Applications" / "CloakBrowser Manager.app").mkdir(parents=True)
    running = Path("/private/var/folders/x/T/AppTranslocation/ABC/d/CloakBrowser Manager.app")

    folders = (tmp_path / "system-Applications", home / "Applications")
    assert self_update.macos_install_target(running, folders=folders) == home / "Applications" / "CloakBrowser Manager.app"
    with pytest.raises(self_update.UpdateError, match="找不到"):
        self_update.macos_install_target(running, folders=(tmp_path / "nowhere",))
    assert self_update.macos_install_target(Path("/Applications/CloakBrowser Manager.app")) == Path(
        "/Applications/CloakBrowser Manager.app"
    )


def test_windows_script_waits_then_installs_silently(tmp_path: Path):
    script = self_update.windows_install_script(pid=4242, installer=tmp_path / "setup.exe", log_path=tmp_path / "u.log")
    assert 'tasklist /FI "PID eq 4242"' in script
    assert "/VERYSILENT" in script and "/SUPPRESSMSGBOXES" in script


# ── Pending note ─────────────────────────────────────────────────────────────


def test_settle_reports_success_and_clears_the_note(tmp_path: Path):
    self_update.write_pending(tmp_path, from_version="0.4.3", to_version="0.5.0")
    result = self_update.settle_pending(tmp_path, "0.5.0")
    assert result["ok"] is True and result["from"] == "0.4.3"
    assert self_update.settle_pending(tmp_path, "0.5.0") is None


def test_settle_reports_failure_with_the_scripts_last_line(tmp_path: Path):
    self_update.write_pending(tmp_path, from_version="0.4.3", to_version="0.5.0")
    (self_update.updates_dir(tmp_path) / self_update.SCRIPT_LOG_NAME).write_text(
        "waiting\ncannot move the current app aside (macOS App Management?)\n"
    )
    result = self_update.settle_pending(tmp_path, "0.4.3")
    assert result["ok"] is False
    assert "App Management" in result["reason"]


# ── The macOS swap script, run for real on fake bundles ──────────────────────


def _status_server(version: str | None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({"running_count": 0, "app_version": version}, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _fake_bundles(tmp_path: Path) -> tuple[Path, Path, Path]:
    apps = tmp_path / "Applications"
    target = apps / "CloakBrowser Manager.app"
    (target / "Contents").mkdir(parents=True)
    (target / "Contents" / "version").write_text("old")
    staged = apps / ".CloakBrowser Manager.update-0.5.0.app"
    (staged / "Contents").mkdir(parents=True)
    (staged / "Contents" / "version").write_text("new")
    return target, staged, apps / ".CloakBrowser Manager.previous.app"


def _run_swap(tmp_path: Path, version_served: str | None, health_timeout: int) -> tuple[Path, Path, int]:
    target, staged, backup = _fake_bundles(tmp_path)
    server = _status_server(version_served)
    old_app = subprocess.Popen(["sleep", "1"])
    # Reap it as soon as it exits; a zombie would still answer `kill -0`.
    reaper = threading.Thread(target=old_app.wait, daemon=True)
    reaper.start()
    script = tmp_path / "swap.sh"
    script.write_text(self_update.macos_swap_script(
        pid=old_app.pid, target_app=target, staged_app=staged, backup_app=backup, version="0.5.0",
        port=server.server_address[1], log_path=tmp_path / "update.log",
        health_timeout=health_timeout, open_command="true",
    ))
    try:
        code = subprocess.run(["/bin/sh", str(script)], timeout=60).returncode
    finally:
        reaper.join()
        server.shutdown()
    return target, backup, code


@pytest.mark.skipif(sys.platform == "win32", reason="macOS swap script needs /bin/sh")
def test_swap_script_installs_the_new_version_and_keeps_the_old_one(tmp_path: Path):
    target, backup, code = _run_swap(tmp_path, "0.5.0", health_timeout=10)

    assert code == 0
    assert (target / "Contents" / "version").read_text() == "new"
    assert (backup / "Contents" / "version").read_text() == "old"
    assert "0.5.0 is running" in (tmp_path / "update.log").read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="macOS swap script needs /bin/sh")
def test_swap_script_rolls_back_when_the_new_version_never_answers(tmp_path: Path):
    target, backup, code = _run_swap(tmp_path, "0.4.3", health_timeout=2)

    assert code == 1
    assert (target / "Contents" / "version").read_text() == "old"
    assert (Path(f"{target}.failed") / "Contents" / "version").read_text() == "new"
    assert "rolling back" in (tmp_path / "update.log").read_text()


# ── Job ──────────────────────────────────────────────────────────────────────


def _env(tmp_path: Path, **overrides) -> UpdateEnv:
    staged = tmp_path / "Applications" / ".CloakBrowser Manager.update-0.5.0.app"
    values = dict(
        data_dir=tmp_path / "data",
        current_version="0.4.3",
        port=8080,
        platform="darwin",
        keyword="arm64.dmg",
        fetch_release=lambda: _release(),
        backup=MagicMock(),
        request_exit=MagicMock(return_value=True),
        running_app=tmp_path / "Applications" / "CloakBrowser Manager.app",
        pid=4242,
        download=lambda plan, work, progress=None: (work / plan.asset_name).write_bytes(PAYLOAD) or work / plan.asset_name,
        stage_macos=MagicMock(return_value=staged),
        launch=MagicMock(),
    )
    values.update(overrides)
    return UpdateEnv(**values)


def test_job_backs_up_prepares_and_hands_over(tmp_path: Path):
    job = UpdateJob()
    env = _env(tmp_path)

    job.run(env)

    env.backup.assert_called_once()
    command = env.launch.call_args.args[0]
    assert command[0] == "/bin/sh" and command[1].endswith("swap.sh")
    script = Path(command[1]).read_text()
    assert "kill -0 4242" in script and '"app_version":"0.5.0"' in script
    env.request_exit.assert_called_once()
    assert job.snapshot()["phase"] == "restarting"
    assert json.loads((tmp_path / "data" / "updates" / "pending.json").read_text())["to"] == "0.5.0"


def test_job_stops_when_already_up_to_date(tmp_path: Path):
    env = _env(tmp_path, current_version="0.5.0")
    with pytest.raises(self_update.UpdateError, match="已是最新"):
        UpdateJob().run(env)
    env.backup.assert_not_called()
    env.launch.assert_not_called()


def test_job_reports_failure_through_its_state(tmp_path: Path):
    job = UpdateJob()
    env = _env(tmp_path, fetch_release=lambda: _release(digest=None))
    job._set(phase="checking")
    job._run(env)
    state = job.snapshot()
    assert state["phase"] == "failed" and "校验码" in state["error"]


# ── API ──────────────────────────────────────────────────────────────────────


def test_source_checkouts_cannot_self_update(app_client: TestClient):
    status = app_client.get("/api/app/update").json()
    assert status["supported"] is False and status["phase"] == "idle"
    assert app_client.post("/api/app/update").status_code == 409


def test_update_needs_browsers_closed(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from backend import main

    monkeypatch.setattr(main, "_self_update_supported", lambda: True)
    monkeypatch.setitem(main.browser_mgr.running, "p1", MagicMock())
    resp = app_client.post("/api/app/update")
    assert resp.status_code == 409 and "关闭所有浏览器" in resp.json()["detail"]


def test_update_starts_the_job(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from backend import main

    started = []
    monkeypatch.setattr(main, "_self_update_supported", lambda: True)
    monkeypatch.setattr(main.update_job, "start", lambda env: started.append(env) or True)

    resp = app_client.post("/api/app/update")

    assert resp.status_code == 200
    assert started and started[0].backup is main._pre_update_backup


def test_last_update_result_is_reported_once(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from backend import database as db
    from backend import main

    self_update.write_pending(db.DATA_DIR, from_version="0.4.3", to_version="0.5.0")
    monkeypatch.setattr(main, "desktop_app_version", lambda: "0.5.0")
    main._settle_last_update()

    result = app_client.get("/api/app/update").json()["last_result"]
    assert result["ok"] is True and result["to"] == "0.5.0"
    app_client.delete("/api/app/update/result")
    assert app_client.get("/api/app/update").json()["last_result"] is None
