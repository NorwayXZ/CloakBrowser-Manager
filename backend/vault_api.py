"""HTTP surface of the credential vault (``backend/vault.py``).

Two audiences:

* **Agent tools** (``backend/agent_tools.py``) use the profile-scoped endpoints under
  ``/api/profiles/{id}/vault``. They only ever see entry *metadata and references*,
  never a password, and only the entries of that profile.
* **The panel** (a person) uses ``/api/vault`` — including the one explicit way to read
  a password back, ``POST /api/vault/{id}/reveal``. Agent tokens cannot reach these
  paths (see ``agent_auth.path_allowed``).

Failures answer ``{"ok": false, "reason", "detail"}`` like the page endpoints, so the
tool layer can pass them through.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Callable

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import database as db
from . import vault

logger = logging.getLogger("cloakbrowser.manager.vault")

# New entries per rolling 24 hours: a runaway agent loop must not fill the vault.
MAX_NEW_PER_DAY = 30

_STATUS = {"invalid_argument": 400, "not_found": 404, "quota_exceeded": 429}


def _fail(reason: str, detail: str) -> JSONResponse:
    return JSONResponse({"ok": False, "reason": reason, "detail": detail}, status_code=_STATUS.get(reason, 409))


class VaultCreateRequest(BaseModel):
    site: str = Field(min_length=3, max_length=253)
    username: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    password_length: int = Field(default=20, ge=12, le=64)
    symbols: bool = True
    generate_username: bool = False
    notes: str | None = Field(default=None, max_length=500)


class VaultMarkRequest(BaseModel):
    status: str | None = None
    notes: str | None = Field(default=None, max_length=500)


def create_router(profile_exists: Callable[[str], bool]) -> APIRouter:
    router = APIRouter()

    def guard(profile_id: str) -> JSONResponse | None:
        return None if profile_exists(profile_id) else _fail("not_found", "Profile not found")

    def over_quota() -> JSONResponse | None:
        since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).isoformat()
        if db.count_vault_entries_since(since) >= MAX_NEW_PER_DAY:
            return _fail("quota_exceeded", f"24 小时内最多新建 {MAX_NEW_PER_DAY} 个保险库条目。")
        return None

    # ── agent side (profile scoped) ──────────────────────────────────────────

    @router.post("/api/profiles/{profile_id}/vault")
    async def create_entry(profile_id: str, body: VaultCreateRequest):
        if (bad := guard(profile_id)) is not None:
            return bad
        if (bad := over_quota()) is not None:
            return bad
        try:
            entry = db.create_vault_entry(
                profile_id=profile_id, site=vault.site_key(body.site),
                username=body.username or (vault.new_username() if body.generate_username else None), email=body.email,
                password=vault.generate_password(body.password_length, symbols=body.symbols), notes=body.notes,
            )
        except vault.VaultError as exc:
            return _fail(exc.reason, exc.detail)
        return {"ok": True, "entry": vault.entry_view(entry)}

    @router.get("/api/profiles/{profile_id}/vault")
    async def list_entries(profile_id: str):
        if (bad := guard(profile_id)) is not None:
            return bad
        return {"ok": True, "entries": [vault.entry_view(e) for e in db.list_vault_entries(profile_id)]}

    @router.patch("/api/profiles/{profile_id}/vault/{entry_id}")
    async def mark_entry(profile_id: str, entry_id: str, body: VaultMarkRequest):
        if (bad := guard(profile_id)) is not None:
            return bad
        entry = db.get_vault_entry(entry_id)
        if entry is None or entry["profile_id"] != profile_id:
            return _fail("not_found", f"这个画像下没有保险库条目 {entry_id}。")
        if body.status is not None and body.status not in vault.STATUSES:
            return _fail("invalid_argument", f"status 只能是 {'/'.join(vault.STATUSES)}。")
        return {"ok": True, "entry": vault.entry_view(db.update_vault_entry(entry_id, status=body.status, notes=body.notes))}

    # ── panel side (a person) ────────────────────────────────────────────────

    @router.get("/api/vault")
    async def all_entries():
        return {"entries": [vault.entry_view(e) for e in db.list_vault_entries()]}

    @router.post("/api/vault/{entry_id}/reveal")
    async def reveal(entry_id: str, body: dict[str, Any] = Body(default_factory=dict)):
        entry = db.get_vault_entry(entry_id, with_password=True)
        if entry is None:
            return _fail("not_found", "没有这个条目。")
        logger.info("vault entry %s (%s) revealed from the panel", entry_id, entry["site"])
        return {"ok": True, "password": entry["password"], "username": entry.get("username"), "email": entry.get("email")}

    @router.delete("/api/vault/{entry_id}")
    async def delete_entry(entry_id: str):
        return {"ok": db.delete_vault_entry(entry_id)}

    return router


def install(app: Any, profile_exists: Callable[[str], bool]) -> None:
    app.include_router(create_router(profile_exists))
