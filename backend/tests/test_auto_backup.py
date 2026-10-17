"""Scheduled full backups with a copy outside the data directory."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from backend import auto_backup, backup as backups
from backend import database as db


def _settings(copy_dir: Path | None, keep: int = 2) -> auto_backup.AutoBackupSettings:
    return auto_backup.AutoBackupSettings(enabled=True, interval_days=7, keep=keep, copy_dir=str(copy_dir) if copy_dir else None)


def test_defaults_point_the_copy_outside_the_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv(auto_backup.COPY_DIR_ENV, str(tmp_path / "copies"))
    settings = auto_backup.read_settings(lambda _key: None)

    assert settings.enabled is True
    assert settings.interval_days == 7
    assert settings.keep == 4
    assert settings.copy_dir == str(tmp_path / "copies")
    # An empty stored value means "no extra copy".
    assert auto_backup.read_settings({auto_backup.SETTING_COPY_DIR: ""}.get).copy_dir is None


def test_due_after_the_interval_and_never_when_switched_off():
    settings = _settings(None)
    now = datetime.now().astimezone()

    assert auto_backup.is_due(settings, None, now)
    assert not auto_backup.is_due(settings, (now - timedelta(days=6)).isoformat(), now)
    assert auto_backup.is_due(settings, (now - timedelta(days=7, minutes=1)).isoformat(), now)
    settings.enabled = False
    assert not auto_backup.is_due(settings, None, now)
    assert auto_backup.next_due(settings, None) is None


def test_run_copies_outside_and_prunes_only_automatic_backups(sample_profile: dict, tmp_db: Path, tmp_path: Path):
    copies = tmp_path / "copies"
    manual = backups.create_full_backup(tmp_db)

    results = []
    for _ in range(3):
        results.append(auto_backup.run_backup(tmp_db, _settings(copies, keep=2)))
        time.sleep(1.05)  # distinct timestamps in the file names

    full_dir = backups.full_backups_dir(tmp_db)
    autos = sorted(p.name for p in full_dir.iterdir() if backups.backup_origin(p.name) == "auto")
    assert autos == sorted(r.path.name for r in results[1:])
    assert manual.exists()
    assert sorted(p.name for p in copies.iterdir()) == autos
    assert all(r.copy_error is None for r in results)


def test_copy_failure_keeps_the_backup_and_explains(sample_profile: dict, tmp_db: Path, tmp_path: Path):
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("file in the way")

    result = auto_backup.run_backup(tmp_db, _settings(blocked / "copies"))

    assert result.path.exists()
    assert result.copy is None
    assert "复制到" in (result.copy_error or "")


# ── Scheduler and API ────────────────────────────────────────────────────────


def test_scheduler_waits_for_browsers_to_close(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from backend import main

    monkeypatch.setitem(main.browser_mgr.running, "p1", MagicMock())
    assert main._run_auto_backup(force=False) is None
    assert app_client.get("/api/backups/auto").json()["waiting_for_browsers"] is True
    assert db.get_setting(auto_backup.SETTING_LAST_AT) is None


def test_scheduler_skips_when_not_due(app_client: TestClient):
    from backend import main

    db.set_setting(auto_backup.SETTING_LAST_AT, datetime.now().astimezone().isoformat())
    assert main._run_auto_backup(force=False) is None


def test_run_now_backs_up_and_copies(app_client: TestClient, tmp_path: Path):
    app_client.post("/api/profiles", json={"name": "Backed up"})
    copies = tmp_path / "copies"
    app_client.put("/api/backups/auto", json={"enabled": True, "interval_days": 7, "keep": 4, "copy_dir": str(copies)})

    resp = app_client.post("/api/backups/auto/run")

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"].startswith("CloakBrowser-backup-auto-")
    assert Path(body["copy"]).parent == copies
    assert (copies / body["name"]).exists()
    status = body["status"]
    assert status["last_at"] and status["last_error"] is None
    listed = app_client.get("/api/backups").json()["backups"]
    assert [b["origin"] for b in listed if b["kind"] == "full"] == ["auto"]


def test_run_now_needs_browsers_closed(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from backend import main

    monkeypatch.setitem(main.browser_mgr.running, "p1", MagicMock())
    assert app_client.post("/api/backups/auto/run").status_code == 409


def test_settings_reject_a_relative_copy_folder(app_client: TestClient):
    resp = app_client.put("/api/backups/auto", json={"enabled": True, "interval_days": 7, "keep": 4, "copy_dir": "backups"})
    assert resp.status_code == 422


def test_settings_round_trip(app_client: TestClient):
    resp = app_client.put("/api/backups/auto", json={"enabled": False, "interval_days": 3, "keep": 8, "copy_dir": ""})

    body = resp.json()
    assert (body["enabled"], body["interval_days"], body["keep"], body["copy_dir"]) == (False, 3, 8, None)
    assert body["next_due_at"] is None
    assert body["default_copy_dir"] == os.environ[auto_backup.COPY_DIR_ENV]
