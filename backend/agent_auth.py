"""Scoped API tokens for AI agents.

The Manager's own ``AUTH_TOKEN`` / admin password is all-powerful. An agent
should get less, so an admin can mint agent tokens with a scope:

========  =====================================================  ===========
scope     what the token can do                                   mode ceiling
========  =====================================================  ===========
read      look: the read tools                                    read-only
control   read + start/stop profiles, run checks/warm-up          full
cdp       control + the browser tools and the CDP proxy           automation
========  =====================================================  ===========

Two things are enforced for a request that authenticates with an agent token:

* The effective ``mcp.mode`` can never exceed the scope's ceiling
  (``clamp_mode``), whatever the Manager setting says.
* Raw REST is closed. The token may only use the shaped agent tool API
  (``/api/agent/...``), where the field policy (no cookies, no proxy
  credentials, no free-text notes) is applied, plus the CDP proxy for ``cdp``.
  ``path_allowed`` is that allowlist.

Tokens are only checked when the Manager has authentication turned on; with
auth off every local caller is already an administrator.

Plaintext tokens are shown once at creation; only a SHA-256 digest is stored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from typing import Callable

SETTING_KEY = "agent.tokens"
TOKEN_PREFIX = "cbm_"

SCOPE_READ = "read"
SCOPE_CONTROL = "control"
SCOPE_CDP = "cdp"
SCOPES = (SCOPE_READ, SCOPE_CONTROL, SCOPE_CDP)

# Mirrors agent_tools.MODE_* (kept literal: this module stays import-free).
_MODE_RANK = {"off": 0, "read-only": 1, "full": 2, "automation": 3}
SCOPE_CEILING = {SCOPE_READ: "read-only", SCOPE_CONTROL: "full", SCOPE_CDP: "automation"}

MAX_TOKENS = 50


def clamp_mode(mode: str, scope: str | None) -> str:
    """The lower of the configured mode and the token scope's ceiling."""
    if scope is None:
        return mode
    ceiling = SCOPE_CEILING.get(scope, "off")
    if _MODE_RANK.get(mode, 0) <= _MODE_RANK[ceiling]:
        return mode
    return ceiling


_AGENT_API_PATHS = (
    ("GET", re.compile(r"^/api/agent/(tools|guide)$")),
    ("POST", re.compile(r"^/api/agent/tools/[^/]+$")),
    ("*", re.compile(r"^/api/agent/mcp(/.*)?$")),
)
_CDP_PATH = re.compile(r"^/api/profiles/[^/]+/cdp(/.*)?$")


def path_allowed(scope: str, method: str, path: str) -> bool:
    """Raw-REST allowlist for an agent token (HTTP method, or ``WS`` for websockets)."""
    method = method.upper()
    for allowed_method, pattern in _AGENT_API_PATHS:
        if pattern.match(path) and allowed_method in ("*", method):
            return True
    return scope == SCOPE_CDP and bool(_CDP_PATH.match(path))


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenStore:
    """Agent tokens persisted in the Manager's settings table."""

    def __init__(
        self,
        get_setting: Callable[[str], str | None],
        set_setting: Callable[[str, str], None],
    ) -> None:
        self._get = get_setting
        self._set = set_setting

    def _load(self) -> list[dict]:
        raw = self._get(SETTING_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def _save(self, records: list[dict]) -> None:
        self._set(SETTING_KEY, json.dumps(records, ensure_ascii=False))

    @staticmethod
    def public(record: dict) -> dict:
        return {key: record.get(key) for key in ("id", "name", "scope", "created_at")}

    def create(self, name: str, scope: str) -> tuple[dict, str]:
        if scope not in SCOPES:
            raise ValueError(f"scope 只能是 {'/'.join(SCOPES)}")
        name = name.strip()
        if not name:
            raise ValueError("name 不能为空")
        records = self._load()
        if len(records) >= MAX_TOKENS:
            raise ValueError(f"最多 {MAX_TOKENS} 个 agent token，先撤销不用的")
        token = f"{TOKEN_PREFIX}{scope}_{secrets.token_urlsafe(32)}"
        record = {
            "id": uuid.uuid4().hex[:12],
            "name": name[:80],
            "scope": scope,
            "sha256": _digest(token),
            "created_at": int(time.time()),
        }
        self._save([*records, record])
        return self.public(record), token

    def list(self) -> list[dict]:
        return [self.public(record) for record in self._load()]

    def revoke(self, token_id: str) -> bool:
        records = self._load()
        kept = [record for record in records if record.get("id") != token_id]
        if len(kept) == len(records):
            return False
        self._save(kept)
        return True

    def verify(self, token: str) -> dict | None:
        """The (public) record for a valid agent token, else ``None``."""
        if not token.startswith(TOKEN_PREFIX):
            return None
        digest = _digest(token)
        found: dict | None = None
        for record in self._load():  # compare against all: no early exit
            if hmac.compare_digest(str(record.get("sha256", "")), digest):
                found = record
        return self.public(found) if found else None
