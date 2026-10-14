"""Full data backups (database, encryption key, browser profiles) and restore.

A full backup is a zip with:

* ``manifest.json`` – format version, creation time, profile count
* ``profiles.db``   – consistent SQLite snapshot (sqlite3 backup API)
* ``.secret_key``   – Fernet key; without it saved proxies/cookies can't be decrypted
* ``profiles/<id>/`` – Chrome user data dirs (cookies, history, local storage, tabs)
  minus caches Chrome rebuilds on its own

Restoring never deletes anything: the current database, key and profile folders
are moved to ``backups/before-restore-<time>/`` first.

Startup also keeps rotating database snapshots in ``backups/auto/``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

BACKUP_FORMAT = 1
MANIFEST_NAME = "manifest.json"
DB_NAME = "profiles.db"
KEY_NAME = ".secret_key"
PROFILES_DIR = "profiles"
AUTO_SNAPSHOTS_KEPT = 10

FULL_BACKUP_RE = re.compile(r"^CloakBrowser-backup-\d{8}-\d{6}(-\d+)?\.zip$")
AUTO_SNAPSHOT_RE = re.compile(r"^profiles-\d{8}-\d{6}(-\d+)?\.db$")

# Directory names inside a Chrome user data dir that are pure caches.
_SKIPPED_DIRS = frozenset({
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "GraphiteDawnCache",
    "GrShaderCache",
    "ShaderCache",
    "GPUPersistentCache",
    "component_crx_cache",
    "extensions_crx_cache",
    "Crashpad",
    "optimization_guide_model_store",
    "OptimizationHints",
    "OnDeviceHeadSuggestModel",
})
# Per-process lock files; copying them would make Chrome think the profile is in use.
_SKIPPED_FILES = frozenset({
    "SingletonLock",
    "SingletonSocket",
    "SingletonCookie",
    "RunningChromeVersion",
    "lockfile",
    "LOCK",
})
_SKIPPED_FILE_PREFIXES = ("BrowserMetrics",)


class BackupError(RuntimeError):
    """A backup could not be created or restored safely."""


@dataclass(frozen=True)
class BackupFile:
    name: str
    kind: str  # "full" | "auto"
    size: int
    created_at: float


def backups_dir(data_dir: Path) -> Path:
    return data_dir / "backups"


def full_backups_dir(data_dir: Path) -> Path:
    return backups_dir(data_dir) / "full"


def auto_snapshots_dir(data_dir: Path) -> Path:
    return backups_dir(data_dir) / "auto"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _unique_path(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def _snapshot_sqlite(source: Path, target: Path) -> None:
    """Copy a live WAL database consistently."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _should_skip(relative: PurePosixPath, is_dir: bool) -> bool:
    name = relative.name
    if is_dir:
        return name in _SKIPPED_DIRS
    return name in _SKIPPED_FILES or name.startswith(_SKIPPED_FILE_PREFIXES)


def _iter_profile_files(profiles_root: Path):
    for root, dirs, files in os.walk(profiles_root):
        root_path = Path(root)
        rel_root = PurePosixPath(root_path.relative_to(profiles_root).as_posix())
        dirs[:] = sorted(d for d in dirs if not _should_skip(rel_root / d, True))
        for filename in sorted(files):
            path = root_path / filename
            if path.is_symlink() or _should_skip(rel_root / filename, False):
                continue
            yield path, rel_root / filename


def _profile_ids(db_path: Path) -> list[str]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return [row[0] for row in conn.execute("SELECT id FROM profiles")]
    finally:
        conn.close()


def create_full_backup(data_dir: Path, app_version: str | None = None) -> Path:
    """Write a full backup zip into ``backups/full`` and return its path."""
    db_path = data_dir / DB_NAME
    if not db_path.is_file():
        raise BackupError("还没有画像数据库，暂时没有可以备份的数据。")

    target_dir = full_backups_dir(data_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _unique_path(target_dir, f"CloakBrowser-backup-{_timestamp()}", ".zip")
    partial = target.with_suffix(".zip.partial")

    with tempfile.TemporaryDirectory(prefix="cbm-backup-") as tmp:
        snapshot = Path(tmp) / DB_NAME
        _snapshot_sqlite(db_path, snapshot)
        profile_ids = _profile_ids(snapshot)
        manifest = {
            "format": BACKUP_FORMAT,
            "app": "CloakBrowser Manager",
            "app_version": app_version,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "profiles": len(profile_ids),
        }
        try:
            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
                archive.write(snapshot, DB_NAME)
                key = data_dir / KEY_NAME
                if key.is_file():
                    archive.write(key, KEY_NAME)
                profiles_root = data_dir / PROFILES_DIR
                for profile_id in profile_ids:
                    profile_dir = profiles_root / profile_id
                    if not profile_dir.is_dir():
                        continue
                    for path, relative in _iter_profile_files(profile_dir):
                        archive.write(path, f"{PROFILES_DIR}/{profile_id}/{relative}")
            os.chmod(partial, 0o600)
            partial.replace(target)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
    return target


def snapshot_database(data_dir: Path, keep: int = AUTO_SNAPSHOTS_KEPT) -> Path | None:
    """Keep a rotating copy of profiles.db; called on every Manager start."""
    db_path = data_dir / DB_NAME
    if not db_path.is_file():
        return None
    target_dir = auto_snapshots_dir(data_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _unique_path(target_dir, f"profiles-{_timestamp()}", ".db")
    _snapshot_sqlite(db_path, target)
    os.chmod(target, 0o600)
    snapshots = sorted(
        (p for p in target_dir.iterdir() if AUTO_SNAPSHOT_RE.match(p.name)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in snapshots[keep:]:
        old.unlink(missing_ok=True)
    return target


def list_backups(data_dir: Path) -> list[BackupFile]:
    found: list[BackupFile] = []
    for kind, directory, pattern in (
        ("full", full_backups_dir(data_dir), FULL_BACKUP_RE),
        ("auto", auto_snapshots_dir(data_dir), AUTO_SNAPSHOT_RE),
    ):
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and pattern.match(path.name):
                stat = path.stat()
                found.append(BackupFile(path.name, kind, stat.st_size, stat.st_mtime))
    return sorted(found, key=lambda item: item.created_at, reverse=True)


def resolve_backup(data_dir: Path, kind: str, name: str) -> Path:
    """Map a listed backup name to its path, rejecting anything else."""
    if kind == "full" and FULL_BACKUP_RE.match(name):
        path = full_backups_dir(data_dir) / name
    elif kind == "auto" and AUTO_SNAPSHOT_RE.match(name):
        path = auto_snapshots_dir(data_dir) / name
    else:
        raise BackupError("备份文件名无效。")
    if not path.is_file():
        raise BackupError("找不到这个备份文件。")
    return path


def _validate_sqlite(path: Path) -> None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            result = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError("备份里的数据库已损坏，无法恢复。") from exc
    if "profiles" not in tables or not result or result[0] != "ok":
        raise BackupError("备份里的数据库不完整，无法恢复。")


def _safe_member(name: str) -> PurePosixPath | None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts or "\\" in name:
        return None
    return path


def _set_profile_paths(db_path: Path, profiles_root: Path) -> None:
    """Point every profile at this machine's data directory."""
    conn = sqlite3.connect(str(db_path))
    try:
        ids = [row[0] for row in conn.execute("SELECT id FROM profiles")]
        for profile_id in ids:
            conn.execute(
                "UPDATE profiles SET user_data_dir = ? WHERE id = ?",
                (str(profiles_root / profile_id), profile_id),
            )
        conn.commit()
    finally:
        conn.close()


def _move_current_data_aside(data_dir: Path, *, include_profiles: bool) -> Path:
    holding = _unique_path(backups_dir(data_dir), f"before-restore-{_timestamp()}", "")
    holding.mkdir(parents=True)
    names = [DB_NAME, f"{DB_NAME}-wal", f"{DB_NAME}-shm", KEY_NAME]
    if include_profiles:
        names.append(PROFILES_DIR)
    for name in names:
        current = data_dir / name
        if current.exists():
            shutil.move(str(current), str(holding / name))
    return holding


def restore_full_backup(data_dir: Path, archive_file: Path | BinaryIO) -> dict:
    """Replace the current data with a full backup. Caller ensures no browser runs."""
    try:
        archive = zipfile.ZipFile(archive_file)
    except zipfile.BadZipFile as exc:
        raise BackupError("这不是有效的完整备份文件（.zip）。") from exc

    with archive, tempfile.TemporaryDirectory(prefix="cbm-restore-", dir=data_dir) as tmp:
        staging = Path(tmp)
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME))
        except (KeyError, ValueError) as exc:
            raise BackupError("备份文件缺少说明信息，可能不是 CloakBrowser Manager 的完整备份。") from exc
        if manifest.get("format") != BACKUP_FORMAT:
            raise BackupError("备份文件版本不受支持，请升级 Manager 后再恢复。")

        for info in archive.infolist():
            member = _safe_member(info.filename)
            if member is None:
                raise BackupError(f"备份文件包含不安全的路径：{info.filename}")
            if info.is_dir():
                continue
            if member.parts[0] not in {MANIFEST_NAME, DB_NAME, KEY_NAME, PROFILES_DIR}:
                continue
            destination = staging.joinpath(*member.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(destination, "wb") as dst:
                shutil.copyfileobj(src, dst)

        staged_db = staging / DB_NAME
        if not staged_db.is_file():
            raise BackupError("备份文件里没有画像数据库。")
        _validate_sqlite(staged_db)
        _set_profile_paths(staged_db, data_dir / PROFILES_DIR)

        holding = _move_current_data_aside(data_dir, include_profiles=True)
        shutil.move(str(staged_db), str(data_dir / DB_NAME))
        if (staging / KEY_NAME).is_file():
            shutil.move(str(staging / KEY_NAME), str(data_dir / KEY_NAME))
            os.chmod(data_dir / KEY_NAME, 0o600)
        if (staging / PROFILES_DIR).is_dir():
            shutil.move(str(staging / PROFILES_DIR), str(data_dir / PROFILES_DIR))
        else:
            (data_dir / PROFILES_DIR).mkdir(exist_ok=True)

    return {
        "profiles": int(manifest.get("profiles") or 0),
        "created_at": manifest.get("created_at"),
        "previous_data": str(holding),
    }


def restore_database_snapshot(data_dir: Path, snapshot: Path) -> dict:
    """Roll profiles.db back to an automatic snapshot; profile folders stay as they are."""
    _validate_sqlite(snapshot)
    with tempfile.TemporaryDirectory(prefix="cbm-restore-", dir=data_dir) as tmp:
        staged = Path(tmp) / DB_NAME
        shutil.copy2(snapshot, staged)
        _set_profile_paths(staged, data_dir / PROFILES_DIR)
        holding = _move_current_data_aside(data_dir, include_profiles=False)
        key_backup = holding / KEY_NAME
        if key_backup.exists():
            # The snapshot was written with the same key; keep using it.
            shutil.copy2(key_backup, data_dir / KEY_NAME)
        shutil.move(str(staged), str(data_dir / DB_NAME))
    return {"previous_data": str(holding)}


def describe(item: BackupFile) -> dict:
    return {
        "name": item.name,
        "kind": item.kind,
        "size": item.size,
        "created_at": datetime.fromtimestamp(item.created_at).astimezone().isoformat(timespec="seconds"),
    }

