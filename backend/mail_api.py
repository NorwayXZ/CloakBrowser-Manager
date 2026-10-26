"""HTTP surface of the domain mailbox and the credential vault.

Two audiences:

* **Agent tools** (``backend/agent_tools.py``) call the profile-scoped endpoints under
  ``/api/profiles/{id}/...``. They only ever see vault *metadata and references*,
  never a password, and only mail of addresses created for that profile.
* **The panel** (a person) uses ``/api/settings/mail``, ``/api/vault`` and
  ``/api/mail/addresses``, including the one explicit way to read a password back
  (``POST /api/vault/{id}/reveal``). Agent tokens cannot reach these paths (see
  ``agent_auth.path_allowed``).

Failures answer ``{"ok": false, "reason", "detail"}`` like the page endpoints, so the
tool layer can pass them through.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import database as db
from . import vault
from .mailbox import MailError, MailService, new_local_part

logger = logging.getLogger("cloakbrowser.manager.mail_api")

_STATUS = {
    "invalid_argument": 400,
    "not_found": 404,
    "quota_exceeded": 429,
    "mail_not_configured": 409,
    "mail_provider_unreachable": 502,
    "mail_provider_error": 502,
    "vault_ref_invalid": 409,
}


def _fail(reason: str, detail: str) -> JSONResponse:
    return JSONResponse({"ok": False, "reason": reason, "detail": detail}, status_code=_STATUS.get(reason, 409))


class AddressRequest(BaseModel):
    site: str | None = Field(default=None, max_length=253)
    label: str | None = Field(default=None, max_length=120)


class WaitRequest(BaseModel):
    address: str = Field(min_length=3, max_length=320)
    from_contains: str | None = Field(default=None, max_length=200)
    subject_contains: str | None = Field(default=None, max_length=200)
    timeout_s: float = Field(default=45, ge=1, le=120)


class VaultCreateRequest(BaseModel):
    site: str = Field(min_length=3, max_length=253)
    username: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    password_length: int = Field(default=20, ge=12, le=64)
    symbols: bool = True
    notes: str | None = Field(default=None, max_length=500)


class VaultMarkRequest(BaseModel):
    status: str | None = None
    notes: str | None = Field(default=None, max_length=500)


class PrepareRequest(BaseModel):
    site: str = Field(min_length=3, max_length=253)
    username: str | None = Field(default=None, max_length=120)
    password_length: int = Field(default=20, ge=12, le=64)
    symbols: bool = True


class MailSettingsRequest(BaseModel):
    domain: str | None = None
    worker_url: str | None = None
    token: str | None = Field(default=None, max_length=500)  # write-only
    clear_token: bool = False
    max_new_per_day: int | None = Field(default=None, ge=1, le=500)
    retention_days: int | None = Field(default=None, ge=1, le=90)


def create_router(mail: MailService, profile_exists: Callable[[str], bool]) -> APIRouter:
    router = APIRouter()

    def guard(profile_id: str) -> JSONResponse | None:
        return None if profile_exists(profile_id) else _fail("not_found", "Profile not found")

    def over_daily_quota() -> JSONResponse | None:
        import datetime

        since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).isoformat()
        limit = mail.config().max_new_per_day
        if db.count_vault_entries_since(since) >= limit:
            return _fail("quota_exceeded", f"24 小时内最多新建 {limit} 个保险库条目（设置里可调）。")
        return None

    # ── agent side (profile scoped) ──────────────────────────────────────────

    @router.post("/api/profiles/{profile_id}/mail/address")
    async def new_address(profile_id: str, body: AddressRequest = Body(default_factory=AddressRequest)):
        if (bad := guard(profile_id)) is not None:
            return bad
        try:
            site = vault.site_key(body.site) if body.site else None
            entry = await mail.new_address(profile_id, site, body.label)
        except (MailError, vault.VaultError) as exc:
            return _fail(exc.reason, exc.detail)
        return {"ok": True, "address": entry["address"], "site": entry["site"], "label": entry["label"]}

    @router.post("/api/profiles/{profile_id}/mail/wait")
    async def wait_for_mail(profile_id: str, body: WaitRequest):
        if (bad := guard(profile_id)) is not None:
            return bad
        try:
            message = await mail.wait(
                profile_id, body.address, from_contains=body.from_contains,
                subject_contains=body.subject_contains, timeout_s=body.timeout_s,
            )
        except MailError as exc:
            return _fail(exc.reason, exc.detail)
        if message is None:
            return {
                "ok": False, "reason": "mail_timeout",
                "detail": f"{int(body.timeout_s)} 秒内没有收到符合条件的新邮件。",
            }
        return {"ok": True, "message": message}

    @router.get("/api/profiles/{profile_id}/mail/messages")
    async def list_messages(profile_id: str, address: str = Query(min_length=3), limit: int = Query(default=10, ge=1, le=50)):
        if (bad := guard(profile_id)) is not None:
            return bad
        try:
            return {"ok": True, "messages": mail.list_messages(profile_id, address, limit)}
        except MailError as exc:
            return _fail(exc.reason, exc.detail)

    @router.get("/api/profiles/{profile_id}/mail/messages/{message_id}")
    async def read_message(profile_id: str, message_id: str):
        if (bad := guard(profile_id)) is not None:
            return bad
        try:
            return {"ok": True, "message": mail.read_message(profile_id, message_id)}
        except MailError as exc:
            return _fail(exc.reason, exc.detail)

    @router.post("/api/profiles/{profile_id}/vault")
    async def create_entry(profile_id: str, body: VaultCreateRequest):
        if (bad := guard(profile_id)) is not None:
            return bad
        if (bad := over_daily_quota()) is not None:
            return bad
        try:
            entry = db.create_vault_entry(
                profile_id=profile_id, site=vault.site_key(body.site), username=body.username, email=body.email,
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

    @router.post("/api/profiles/{profile_id}/account/prepare")
    async def prepare_account(profile_id: str, body: PrepareRequest):
        """Everything a sign-up form asks for, in one call: an address on the domain, a
        username, and a generated password the agent never sees (references only)."""
        if (bad := guard(profile_id)) is not None:
            return bad
        if (bad := over_daily_quota()) is not None:
            return bad
        try:
            site = vault.site_key(body.site)
            address = await mail.new_address(profile_id, site, f"sign-up {site}")
            entry = db.create_vault_entry(
                profile_id=profile_id, site=site, username=body.username or new_local_part(),
                email=address["address"], password=vault.generate_password(body.password_length, symbols=body.symbols),
            )
        except (MailError, vault.VaultError) as exc:
            return _fail(exc.reason, exc.detail)
        return {"ok": True, "email": address["address"], "entry": vault.entry_view(entry)}

    # ── panel side (a person) ────────────────────────────────────────────────

    @router.get("/api/settings/mail")
    async def get_settings():
        return mail.public_config()

    @router.put("/api/settings/mail")
    async def put_settings(body: MailSettingsRequest):
        try:
            return mail.save_config(**body.model_dump())
        except MailError as exc:
            return _fail(exc.reason, exc.detail)

    @router.post("/api/settings/mail/test")
    async def test_settings():
        try:
            return await mail.test()
        except MailError as exc:
            return _fail(exc.reason, exc.detail)

    @router.get("/api/mail/addresses")
    async def all_addresses():
        return {"addresses": db.list_mail_addresses()}

    @router.delete("/api/mail/addresses/{address}")
    async def remove_address(address: str):
        try:
            removed = await mail.delete_address(address)
        except MailError as exc:
            return _fail(exc.reason, exc.detail)
        return {"ok": removed}

    @router.get("/api/vault")
    async def all_entries():
        return {"entries": [vault.entry_view(e) for e in db.list_vault_entries()]}

    @router.post("/api/vault/{entry_id}/reveal")
    async def reveal(entry_id: str):
        entry = db.get_vault_entry(entry_id, with_password=True)
        if entry is None:
            return _fail("not_found", "没有这个条目。")
        logger.info("vault entry %s (%s) revealed from the panel", entry_id, entry["site"])
        return {"ok": True, "password": entry["password"], "username": entry.get("username"), "email": entry.get("email")}

    @router.delete("/api/vault/{entry_id}")
    async def delete_entry(entry_id: str):
        return {"ok": db.delete_vault_entry(entry_id)}

    return router


def install(app: Any, mail: MailService, profile_exists: Callable[[str], bool]) -> None:
    app.include_router(create_router(mail, profile_exists))
