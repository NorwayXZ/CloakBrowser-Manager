"""SQLite database operations for browser profiles."""

from __future__ import annotations

import datetime
import json
import random
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .runtime import resolve_runtime

RUNTIME = resolve_runtime()
DATA_DIR = RUNTIME.data_dir
DB_PATH = DATA_DIR / "profiles.db"


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                browser_engine TEXT DEFAULT 'auto',
                device_profile TEXT,
                fingerprint_seed INTEGER NOT NULL,
                proxy TEXT,
                timezone TEXT,
                locale TEXT,
                platform TEXT DEFAULT 'windows',
                user_agent TEXT,
                screen_width INTEGER DEFAULT 1920,
                screen_height INTEGER DEFAULT 1080,
                gpu_vendor TEXT,
                gpu_renderer TEXT,
                hardware_concurrency INTEGER,
                humanize BOOLEAN DEFAULT 1,
                human_preset TEXT DEFAULT 'default',
                headless BOOLEAN DEFAULT 0,
                geoip BOOLEAN DEFAULT 0,
                clipboard_sync BOOLEAN DEFAULT 1,
                auto_launch BOOLEAN DEFAULT 0,
                color_scheme TEXT,
                group_name TEXT DEFAULT '未分组',
                account_platform TEXT,
                cookies_json TEXT,
                startup_urls TEXT DEFAULT '[]',
                launch_args TEXT DEFAULT '[]',
                last_opened_at TEXT,
                proxy_geo_json TEXT,
                deleted_at TEXT,
                notes TEXT,
                user_data_dir TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profile_groups (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                color TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS proxy_presets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                proxy TEXT NOT NULL,
                mode TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profile_tags (
                profile_id TEXT REFERENCES profiles(id) ON DELETE CASCADE,
                tag TEXT NOT NULL,
                color TEXT,
                PRIMARY KEY (profile_id, tag)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.commit()

        # Migrations for existing databases
        cols = {row[1] for row in conn.execute("PRAGMA table_info(profiles)").fetchall()}
        if "clipboard_sync" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN clipboard_sync BOOLEAN DEFAULT 1")
            conn.commit()
        if "launch_args" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN launch_args TEXT DEFAULT '[]'")
            conn.commit()
        if "auto_launch" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN auto_launch BOOLEAN DEFAULT 0")
            conn.commit()
        if "browser_engine" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN browser_engine TEXT DEFAULT 'auto'")
            conn.commit()
        if "device_profile" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN device_profile TEXT")
            conn.commit()
        if "group_name" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN group_name TEXT DEFAULT '未分组'")
            conn.commit()
        if "account_platform" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN account_platform TEXT")
            conn.commit()
        if "cookies_json" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN cookies_json TEXT")
            conn.commit()
        if "startup_urls" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN startup_urls TEXT DEFAULT '[]'")
            conn.commit()
        if "last_opened_at" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN last_opened_at TEXT")
            conn.commit()
        if "proxy_geo_json" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN proxy_geo_json TEXT")
            conn.commit()
        if "deleted_at" not in cols:
            conn.execute("ALTER TABLE profiles ADD COLUMN deleted_at TEXT")
            conn.commit()
        cutoff = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
        ).isoformat()
        conn.execute(
            "DELETE FROM profiles WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff,),
        )
        conn.commit()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _load_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _load_json_dict(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def get_setting(key: str) -> str | None:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    now = _now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        conn.commit()


def delete_setting(key: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        conn.commit()


def create_profile(
    name: str,
    fingerprint_seed: int | None = None,
    **fields: Any,
) -> dict[str, Any]:
    profile_id = str(uuid.uuid4())
    seed = fingerprint_seed if fingerprint_seed is not None else random.randint(10000, 99999)
    user_data_dir = str(DATA_DIR / "profiles" / profile_id)
    now = _now()
    tags = fields.pop("tags", None) or []

    with get_db() as conn:
        conn.execute(
            """INSERT INTO profiles (
                id, name, browser_engine, device_profile, fingerprint_seed, proxy, timezone, locale, platform,
                user_agent, screen_width, screen_height, gpu_vendor, gpu_renderer,
                hardware_concurrency, humanize, human_preset, headless, geoip,
                clipboard_sync, auto_launch, color_scheme, group_name, account_platform,
                cookies_json, startup_urls, launch_args, notes,
                user_data_dir, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                profile_id, name,
                fields.get("browser_engine", "auto"),
                fields.get("device_profile"),
                seed,
                fields.get("proxy"),
                fields.get("timezone"),
                fields.get("locale"),
                fields.get("platform", "windows"),
                fields.get("user_agent"),
                fields.get("screen_width", 1920),
                fields.get("screen_height", 1080),
                fields.get("gpu_vendor"),
                fields.get("gpu_renderer"),
                fields.get("hardware_concurrency"),
                fields.get("humanize", True),
                fields.get("human_preset", "default"),
                fields.get("headless", False),
                fields.get("geoip", False),
                fields.get("clipboard_sync", True),
                fields.get("auto_launch", False),
                fields.get("color_scheme"),
                fields.get("group_name") or "未分组",
                fields.get("account_platform"),
                fields.get("cookies_json"),
                json.dumps(fields.get("startup_urls") or []),
                json.dumps(fields.get("launch_args") or []),
                fields.get("notes"),
                user_data_dir, now, now,
            ),
        )
        for t in tags:
            conn.execute(
                "INSERT INTO profile_tags (profile_id, tag, color) VALUES (?, ?, ?)",
                (profile_id, t["tag"], t.get("color")),
            )
        conn.commit()

    return get_profile(profile_id)  # type: ignore[return-value]


def get_profile(profile_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            return None
        profile = dict(row)
        profile["startup_urls"] = _load_json_list(profile.get("startup_urls"))
        profile["launch_args"] = _load_json_list(profile.get("launch_args"))
        profile["proxy_geo"] = _load_json_dict(profile.get("proxy_geo_json"))
        tags = conn.execute(
            "SELECT tag, color FROM profile_tags WHERE profile_id = ?",
            (profile_id,),
        ).fetchall()
        profile["tags"] = [dict(t) for t in tags]
        return profile


def _hydrate_profile(row: sqlite3.Row) -> dict[str, Any]:
    profile = dict(row)
    profile["startup_urls"] = _load_json_list(profile.get("startup_urls"))
    profile["launch_args"] = _load_json_list(profile.get("launch_args"))
    profile["proxy_geo"] = _load_json_dict(profile.get("proxy_geo_json"))
    with get_db() as conn:
        tags = conn.execute(
            "SELECT tag, color FROM profile_tags WHERE profile_id = ?",
            (profile["id"],),
        ).fetchall()
    profile["tags"] = [dict(t) for t in tags]
    return profile


def list_profiles() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM profiles WHERE deleted_at IS NULL ORDER BY created_at DESC"
        ).fetchall()
    return [_hydrate_profile(row) for row in rows]


def list_deleted_profiles() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM profiles WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
        ).fetchall()
    return [_hydrate_profile(row) for row in rows]


def update_profile(profile_id: str, **fields: Any) -> dict[str, Any] | None:
    existing = get_profile(profile_id)
    if not existing:
        return None

    tags = fields.pop("tags", None)

    # Only update fields that were explicitly provided
    update_cols = []
    update_vals = []
    # Pre-serialize list fields to JSON before the generic update loop
    if "startup_urls" in fields:
        fields["startup_urls"] = json.dumps(fields["startup_urls"] or [])
    if "launch_args" in fields:
        fields["launch_args"] = json.dumps(fields["launch_args"] or [])
    if fields.get("fingerprint_seed") is None:
        fields.pop("fingerprint_seed", None)

    for col in (
        "name", "browser_engine", "device_profile", "fingerprint_seed", "proxy", "timezone", "locale", "platform",
        "user_agent", "screen_width", "screen_height", "gpu_vendor", "gpu_renderer",
        "hardware_concurrency", "humanize", "human_preset", "headless", "geoip",
        "clipboard_sync", "auto_launch", "color_scheme", "group_name", "account_platform", "cookies_json",
        "startup_urls", "launch_args", "notes",
    ):
        if col in fields:
            update_cols.append(f"{col} = ?")
            update_vals.append(fields[col])

    if update_cols:
        update_cols.append("updated_at = ?")
        update_vals.append(_now())
        update_vals.append(profile_id)
        with get_db() as conn:
            conn.execute(
                f"UPDATE profiles SET {', '.join(update_cols)} WHERE id = ?",
                update_vals,
            )
            conn.commit()

    if tags is not None:
        with get_db() as conn:
            conn.execute("DELETE FROM profile_tags WHERE profile_id = ?", (profile_id,))
            for t in tags:
                conn.execute(
                    "INSERT INTO profile_tags (profile_id, tag, color) VALUES (?, ?, ?)",
                    (profile_id, t["tag"], t.get("color")),
                )
            conn.commit()

    return get_profile(profile_id)


def mark_profile_opened(profile_id: str, proxy_geo: dict[str, Any] | None = None) -> None:
    now = _now()
    with get_db() as conn:
        conn.execute(
            """
            UPDATE profiles
            SET last_opened_at = ?,
                proxy_geo_json = COALESCE(?, proxy_geo_json),
                updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                json.dumps(proxy_geo, ensure_ascii=False) if proxy_geo else None,
                now,
                profile_id,
            ),
        )
        conn.commit()


def delete_profile(profile_id: str) -> bool:
    now = _now()
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE profiles SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, profile_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def restore_profile(profile_id: str) -> dict[str, Any] | None:
    now = _now()
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE profiles SET deleted_at = NULL, updated_at = ? WHERE id = ?",
            (now, profile_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
    return get_profile(profile_id)


def purge_profile(profile_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        conn.commit()
        return cursor.rowcount > 0


def list_groups() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM profile_groups ORDER BY created_at ASC").fetchall()
        return [dict(row) for row in rows]


def create_group(name: str, color: str | None = None) -> dict[str, Any]:
    group_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO profile_groups (id, name, color, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (group_id, name, color, now, now),
        )
        conn.commit()
    return {"id": group_id, "name": name, "color": color, "created_at": now, "updated_at": now}


def delete_group(group_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT name FROM profile_groups WHERE id = ?", (group_id,)).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE profiles SET group_name = '未分组' WHERE group_name = ?",
            (row["name"],),
        )
        cursor = conn.execute("DELETE FROM profile_groups WHERE id = ?", (group_id,))
        conn.commit()
        return cursor.rowcount > 0


def list_proxy_presets() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM proxy_presets ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


def create_proxy_preset(name: str, proxy: str, mode: str) -> dict[str, Any]:
    preset_id = str(uuid.uuid4())
    now = _now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO proxy_presets (id, name, proxy, mode, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                proxy = excluded.proxy,
                mode = excluded.mode,
                updated_at = excluded.updated_at
            """,
            (preset_id, name, proxy, mode, now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM proxy_presets WHERE name = ?",
            (name,),
        ).fetchone()
        return dict(row)


def delete_proxy_preset(preset_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM proxy_presets WHERE id = ?", (preset_id,))
        conn.commit()
        return cursor.rowcount > 0
