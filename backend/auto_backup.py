"""Scheduled full backups, with a second copy kept outside the data directory.

App cleaners delete ``Application Support/CloakBrowser Manager`` together with
the app, so the backups stored inside it vanish too. Every automatic backup
is therefore also copied to a folder in the user's home directory (no macOS
folder-permission prompt there), and only automatic backups are pruned.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from . import backup as backups

SETTING_ENABLED = "auto_backup_enabled"
SETTING_INTERVAL_DAYS = "auto_backup_interval_days"
SETTING_KEEP = "auto_backup_keep"
SETTING_COPY_DIR = "auto_backup_copy_dir"
SETTING_LAST_AT = "auto_backup_last_at"
SETTING_LAST_ERROR = "auto_backup_last_error"
SETTING_LAST_COPY = "auto_backup_last_copy"

COPY_DIR_ENV = "CLOAKBROWSER_MANAGER_BACKUP_COPY_DIR"
DEFAULT_INTERVAL_DAYS = 7
DEFAULT_KEEP = 4


def default_copy_dir() -> Path:
    override = os.environ.get(COPY_DIR_ENV)
    return Path(override) if override else Path.home() / "CloakBrowser Manager Backups"


@dataclass
class AutoBackupSettings:
    enabled: bool = True
    interval_days: int = DEFAULT_INTERVAL_DAYS
    keep: int = DEFAULT_KEEP
    # None = keep backups only inside the data directory.
    copy_dir: str | None = None


def _int_setting(raw: str | None, default: int, low: int, high: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        return default
    return min(max(value, low), high)


def read_settings(get_setting: Callable[[str], str | None]) -> AutoBackupSettings:
    copy_dir = get_setting(SETTING_COPY_DIR)
    return AutoBackupSettings(
        enabled=(get_setting(SETTING_ENABLED) or "true") != "false",
        interval_days=_int_setting(get_setting(SETTING_INTERVAL_DAYS), DEFAULT_INTERVAL_DAYS, 1, 90),
        keep=_int_setting(get_setting(SETTING_KEEP), DEFAULT_KEEP, 1, 52),
        # An unset value means the default folder; an empty string means "no copy".
        copy_dir=str(default_copy_dir()) if copy_dir is None else (copy_dir or None),
    )


def save_settings(set_setting: Callable[[str, str], None], settings: AutoBackupSettings) -> None:
    set_setting(SETTING_ENABLED, "true" if settings.enabled else "false")
    set_setting(SETTING_INTERVAL_DAYS, str(settings.interval_days))
    set_setting(SETTING_KEEP, str(settings.keep))
    set_setting(SETTING_COPY_DIR, settings.copy_dir or "")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def next_due(settings: AutoBackupSettings, last_at: str | None) -> datetime | None:
    """When the next automatic backup is due; None when switched off."""
    if not settings.enabled:
        return None
    last = _parse_time(last_at)
    if last is None:
        return datetime.now().astimezone()
    return last + timedelta(days=settings.interval_days)


def is_due(settings: AutoBackupSettings, last_at: str | None, now: datetime | None = None) -> bool:
    if not settings.enabled:
        return False
    last = _parse_time(last_at)
    if last is None:
        # Never backed up automatically: do it at the first quiet moment.
        return True
    return (now or datetime.now().astimezone()) >= last + timedelta(days=settings.interval_days)


@dataclass
class AutoBackupResult:
    path: Path
    copy: Path | None
    copy_error: str | None


def run_backup(
    data_dir: Path,
    settings: AutoBackupSettings,
    *,
    origin: str = "auto",
    app_version: str | None = None,
) -> AutoBackupResult:
    """Make one backup, copy it outside the data directory, prune old ones of the same origin."""
    path = backups.create_full_backup(data_dir, app_version=app_version, origin=origin)
    backups.prune_backups(backups.full_backups_dir(data_dir), origin, settings.keep)
    copy: Path | None = None
    copy_error: str | None = None
    if settings.copy_dir:
        target_dir = Path(settings.copy_dir).expanduser()
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            copy = target_dir / path.name
            partial = copy.with_suffix(".zip.partial")
            shutil.copy2(path, partial)
            os.chmod(partial, 0o600)
            partial.replace(copy)
            backups.prune_backups(target_dir, origin, settings.keep)
        except OSError as exc:
            copy = None
            copy_error = f"备份已保存在数据目录，但复制到 {target_dir} 失败：{exc.strerror or exc}"
    return AutoBackupResult(path=path, copy=copy, copy_error=copy_error)
