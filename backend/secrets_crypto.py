"""Transparent encryption-at-rest for sensitive profile fields.

Proxy credentials (which may embed a username/password) and saved cookies are
stored encrypted in SQLite so that a leaked database file or backup cannot
expose a user's paid proxy accounts or session cookies. Plaintext values are
still accepted on read (recognized by the ``enc::`` prefix) so existing rows
migrate automatically on the next write.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .runtime import resolve_runtime

DATA_DIR = resolve_runtime().data_dir

_PREFIX = "enc::"

_lock = threading.Lock()
_key: Fernet | None = None


def _key_path() -> Path:
    return DATA_DIR / ".secret_key"


def _load_key() -> Fernet:
    global _key
    if _key is not None:
        return _key
    with _lock:
        if _key is not None:
            return _key
        path = _key_path()
        if path.exists():
            raw = path.read_text(encoding="utf-8").strip()
        else:
            raw = Fernet.generate_key().decode("ascii")
            path.write_text(raw, encoding="utf-8")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        _key = Fernet(raw.encode("ascii"))
        return _key


def encrypt_value(value: str | None) -> str | None:
    """Encrypt a string for storage. Returns ``None`` as-is, else ``enc::<b64>``."""
    if value is None:
        return None
    token = _load_key().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt_value(value: str | None) -> str | None:
    """Return the plaintext for a stored value.

    Values without the ``enc::`` prefix are returned unchanged, which keeps
    existing plaintext rows readable until they are next written.
    """
    if not value:
        return value
    if not value.startswith(_PREFIX):
        return value
    try:
        token = value[len(_PREFIX):].encode("ascii")
        return _load_key().decrypt(token).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError):
        # Corrupt or key-mismatched value: do not crash, but do not return
        # garbage either — return None so callers treat it as "unset".
        return None


def encrypt_json(value: object | None) -> str | None:
    """Encrypt an arbitrary JSON-serializable object (e.g. cookies_json)."""
    if value is None:
        return None
    return encrypt_value(json.dumps(value, ensure_ascii=False))


def decrypt_json(value: str | None) -> object | None:
    """Decrypt a value produced by :func:`encrypt_json` back into an object."""
    raw = decrypt_value(value)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
