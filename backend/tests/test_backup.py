from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import backup as backups
from backend import database as db


def _make_profile_dir(data_dir: Path, profile_id: str) -> Path:
    root = data_dir / "profiles" / profile_id
    (root / "Default" / "Cache").mkdir(parents=True)
    (root / "Default" / "Cache" / "data_0").write_bytes(b"cache")
    (root / "Default" / "Cookies").write_bytes(b"cookie-db")
    (root / "Default" / "Local Storage" / "leveldb").mkdir(parents=True)
    (root / "Default" / "Local Storage" / "leveldb" / "000003.log").write_bytes(b"ls")
    (root / "Default" / "Local Storage" / "leveldb" / "LOCK").write_bytes(b"")
    (root / "SingletonLock").write_text("host-123")
    return root


@pytest.fixture()
def data_with_profile(tmp_db: Path):
    profile = db.create_profile(name="Backup Me", fingerprint_seed=1)
    _make_profile_dir(tmp_db, profile["id"])
    (tmp_db / ".secret_key").write_text("original-key")
    return tmp_db, profile


def test_full_backup_contains_data_but_not_caches(data_with_profile):
    data_dir, profile = data_with_profile
    path = backups.create_full_backup(data_dir)

    assert path.parent == data_dir / "backups" / "full"
    assert backups.FULL_BACKUP_RE.match(path.name)
    assert path.stat().st_mode & 0o077 == 0
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    prefix = f"profiles/{profile['id']}/"
    assert {"manifest.json", "profiles.db", ".secret_key"} <= names
    assert prefix + "Default/Cookies" in names
    assert prefix + "Default/Local Storage/leveldb/000003.log" in names
    assert prefix + "Default/Cache/data_0" not in names
    assert prefix + "SingletonLock" not in names
    assert prefix + "Default/Local Storage/leveldb/LOCK" not in names
    assert manifest["format"] == backups.BACKUP_FORMAT
    assert manifest["profiles"] == 1


def test_full_backup_round_trip_keeps_previous_data(data_with_profile):
    data_dir, profile = data_with_profile
    backup_path = backups.create_full_backup(data_dir)

    # Simulate damage after the backup.
    with sqlite3.connect(data_dir / "profiles.db") as conn:
        conn.execute("DELETE FROM profiles")
    cookies = data_dir / "profiles" / profile["id"] / "Default" / "Cookies"
    cookies.write_bytes(b"corrupted")
    (data_dir / ".secret_key").write_text("other-key")

    result = backups.restore_full_backup(data_dir, backup_path)

    assert [p["id"] for p in db.list_profiles()] == [profile["id"]]
    assert cookies.read_bytes() == b"cookie-db"
    assert (data_dir / ".secret_key").read_text() == "original-key"
    previous = Path(result["previous_data"])
    assert previous.parent == data_dir / "backups"
    assert (previous / "profiles" / profile["id"] / "Default" / "Cookies").read_bytes() == b"corrupted"
    assert (previous / ".secret_key").read_text() == "other-key"


def test_restore_rewrites_profile_paths_for_this_machine(data_with_profile, tmp_path: Path):
    data_dir, profile = data_with_profile
    with sqlite3.connect(data_dir / "profiles.db") as conn:
        conn.execute("UPDATE profiles SET user_data_dir = ?", ("/Users/old/profiles/" + profile["id"],))
    backup_path = backups.create_full_backup(data_dir)

    backups.restore_full_backup(data_dir, backup_path)

    restored = db.get_profile(profile["id"])
    assert restored["user_data_dir"] == str(data_dir / "profiles" / profile["id"])


@pytest.mark.parametrize("bad_name", ["../evil.txt", "/abs/path", "profiles/../../x"])
def test_restore_rejects_unsafe_paths(data_with_profile, bad_name):
    data_dir, _ = data_with_profile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": backups.BACKUP_FORMAT}))
        archive.writestr(bad_name, "x")
    buffer.seek(0)
    before = (data_dir / "profiles.db").read_bytes()

    with pytest.raises(backups.BackupError, match="不安全"):
        backups.restore_full_backup(data_dir, buffer)
    assert (data_dir / "profiles.db").read_bytes() == before


def test_restore_rejects_non_backup_zip(data_with_profile):
    data_dir, _ = data_with_profile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "x")
    buffer.seek(0)
    with pytest.raises(backups.BackupError, match="说明信息"):
        backups.restore_full_backup(data_dir, buffer)
    with pytest.raises(backups.BackupError, match="有效"):
        backups.restore_full_backup(data_dir, io.BytesIO(b"not a zip"))


def test_auto_snapshots_rotate(tmp_db: Path):
    for _ in range(4):
        backups.snapshot_database(tmp_db, keep=2)
    snapshots = [b for b in backups.list_backups(tmp_db) if b.kind == "auto"]
    assert len(snapshots) == 2


def test_restore_database_snapshot(tmp_db: Path):
    kept = db.create_profile(name="Before", fingerprint_seed=1)
    snapshot = backups.snapshot_database(tmp_db)
    with sqlite3.connect(tmp_db / "profiles.db") as conn:
        conn.execute("DELETE FROM profiles")

    backups.restore_database_snapshot(tmp_db, snapshot)

    assert [p["id"] for p in db.list_profiles()] == [kept["id"]]


def test_resolve_backup_rejects_arbitrary_names(tmp_db: Path):
    with pytest.raises(backups.BackupError):
        backups.resolve_backup(tmp_db, "full", "../profiles.db")
    with pytest.raises(backups.BackupError):
        backups.resolve_backup(tmp_db, "auto", "profiles.db")


def test_backup_api_flow(app_client: TestClient, tmp_db: Path):
    created = app_client.post("/api/profiles", json={"name": "Api"}).json()
    _make_profile_dir(tmp_db, created["id"])

    made = app_client.post("/api/backups")
    assert made.status_code == 200
    name = made.json()["name"]

    listing = app_client.get("/api/backups").json()
    assert name in [b["name"] for b in listing["backups"] if b["kind"] == "full"]
    assert any(b["kind"] == "auto" for b in listing["backups"])  # startup snapshot

    download = app_client.get(f"/api/backups/full/{name}/download")
    assert download.status_code == 200
    payload = download.content

    app_client.delete(f"/api/profiles/{created['id']}")
    restored = app_client.post(
        "/api/backups/restore-upload", content=payload, headers={"content-type": "application/zip"}
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["profiles"] == 1
    assert [p["id"] for p in app_client.get("/api/profiles").json()] == [created["id"]]

    assert app_client.delete(f"/api/backups/full/{name}").status_code == 200
    assert app_client.get(f"/api/backups/full/{name}/download").status_code == 404


def test_backup_requires_stopped_browsers(app_client: TestClient):
    from backend import main

    main.browser_mgr.running["busy"] = object()
    try:
        assert app_client.post("/api/backups").status_code == 409
        assert app_client.post("/api/backups/restore-upload", content=b"x").status_code == 409
    finally:
        main.browser_mgr.running.pop("busy", None)
