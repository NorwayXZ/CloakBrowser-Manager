"""Credential vault for agent sign-ups.

When an agent registers an account it needs a password, but the agent should not
be the one holding it: tool calls and results end up in its context, in logs and
in the audit trail. So the Manager generates the password, stores it encrypted,
and hands the agent a *reference*:

    {{vault:<entry id>.password}}     {{vault:<entry id>.username}}     {{vault:<entry id>.email}}

``browser_type`` (and a batch ``type`` step) accept a reference anywhere in
``text``; it is replaced by the real value on the Manager just before typing.
Anything the page echoes back that matches a stored password (a "show password"
toggle in a snapshot, say) is rewritten to the reference on the way out.

A reference only works on the profile that owns the entry.
"""

from __future__ import annotations

import re
import secrets
import string
from typing import Any
from urllib.parse import urlsplit

from . import database as db

REF_RE = re.compile(r"\{\{vault:([0-9a-f]{8,32})\.(password|username|email)\}\}")
FIELDS = ("password", "username", "email")
STATUSES = ("new", "registered", "verified", "failed")
MIN_REDACT_LEN = 8

_LOWER = "abcdefghijkmnopqrstuvwxyz"  # no l
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I, O
_DIGITS = "23456789"  # no 0, 1
_SYMBOLS = "!@#$%^&*-_=+"


class VaultError(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def generate_password(length: int = 20, *, symbols: bool = True) -> str:
    """A random password with at least one character of every class it uses.

    Look-alike characters are left out, and the symbol set is the conservative one
    most sign-up forms accept.
    """
    length = max(12, min(int(length), 64))
    classes = [_LOWER, _UPPER, _DIGITS] + ([_SYMBOLS] if symbols else [])
    chars = [secrets.choice(group) for group in classes]
    pool = "".join(classes)
    chars += [secrets.choice(pool) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def site_key(site: str) -> str:
    """Normalise ``https://www.Example.com/signup`` (or ``example.com``) to ``example.com``."""
    raw = (site or "").strip().lower()
    if not raw:
        raise VaultError("invalid_argument", "site 不能为空（写网站域名，如 example.com）。")
    host = urlsplit(raw if "://" in raw else f"//{raw}").hostname or ""
    host = host.removeprefix("www.")
    if not re.fullmatch(r"[a-z0-9.-]{3,253}", host) or "." not in host:
        raise VaultError("invalid_argument", f"「{site}」不像一个网站域名。")
    return host


def entry_view(entry: dict[str, Any]) -> dict[str, Any]:
    """What an agent (or the panel list) may see of an entry: no password."""
    ref = entry["id"]
    return {
        "id": ref,
        "profile_id": entry["profile_id"],
        "site": entry["site"],
        "username": entry.get("username"),
        "email": entry.get("email"),
        "status": entry["status"],
        "notes": entry.get("notes"),
        "created_at": entry["created_at"],
        "updated_at": entry["updated_at"],
        "refs": {field: "{{vault:%s.%s}}" % (ref, field) for field in FIELDS},
    }


def resolve_refs(text: str, profile_id: str) -> str:
    """Replace every ``{{vault:…}}`` in ``text`` with its value.

    Raises ``VaultError`` for an unknown entry or one that belongs to another profile.
    """

    def substitute(match: re.Match[str]) -> str:
        entry = db.get_vault_entry(match.group(1), with_password=True)
        if entry is None or entry["profile_id"] != profile_id:
            raise VaultError(
                "vault_ref_invalid",
                f"保险库里没有 {match.group(1)}，或它不属于这个画像。用 vault_list 查看这个画像的条目。",
            )
        value = entry.get(match.group(2))
        if not value:
            raise VaultError("vault_ref_invalid", f"条目 {match.group(1)} 没有 {match.group(2)}。")
        return str(value)

    return REF_RE.sub(substitute, text)


def has_refs(value: Any) -> bool:
    return isinstance(value, str) and REF_RE.search(value) is not None


def redaction_map(profile_id: str) -> dict[str, str]:
    """``{plaintext password: reference}`` for this profile's entries."""
    return {
        entry["password"]: "{{vault:%s.password}}" % entry["id"]
        for entry in db.list_vault_entries(profile_id, with_password=True)
        if entry.get("password") and len(entry["password"]) >= MIN_REDACT_LEN
    }


def redact(value: Any, secrets_map: dict[str, str]) -> Any:
    """``value`` with stored passwords replaced by their references, recursively."""
    if not secrets_map:
        return value
    if isinstance(value, str):
        for plaintext, ref in secrets_map.items():
            if plaintext in value:
                value = value.replace(plaintext, ref)
        return value
    if isinstance(value, list):
        return [redact(item, secrets_map) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, secrets_map) for key, item in value.items()}
    return value
