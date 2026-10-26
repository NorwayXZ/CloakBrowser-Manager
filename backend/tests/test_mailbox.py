"""Tests for the domain mailbox, the credential vault and their HTTP surface."""

from __future__ import annotations

import asyncio
import datetime
import json
import re
from unittest.mock import MagicMock

import httpx
import pytest

from backend import database as db
from backend import mailbox, vault
from backend.mailbox import MailError, MailService, RawMessage, WorkerProvider

DOMAIN = "mail.test"


# ── a stand-in for the Cloudflare Worker ─────────────────────────────────────


class FakeProvider:
    """In-memory version of the Worker's contract (mail-worker/src/index.ts)."""

    def __init__(self) -> None:
        self.addresses: set[str] = set()
        self.messages: list[RawMessage] = []
        self.seq = 0
        self.fetches = 0
        self.fail_next = 0

    def deliver(self, address: str, subject: str, text: str, sender: str = "noreply@acme.example",
                sender_name: str | None = "Acme", html: str | None = None) -> bool:
        """What the Email Worker does: store the mail only if the recipient was registered."""
        if address.lower() not in self.addresses:
            return False
        self.seq += 1
        self.messages.append(RawMessage(
            seq=self.seq, address=address.lower(), sender=sender, sender_name=sender_name, subject=subject,
            text=text, html=html, received_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        ))
        return True

    async def register(self, address: str) -> None:
        self.addresses.add(address.lower())

    async def forget(self, address: str) -> None:
        self.addresses.discard(address.lower())
        self.messages = [m for m in self.messages if m.address != address.lower()]

    async def fetch(self, after_seq: int, limit: int = 50):
        self.fetches += 1
        if self.fail_next:
            self.fail_next -= 1
            raise MailError("mail_provider_unreachable", "boom")
        return [m for m in self.messages if m.seq > after_seq][:limit], self.seq

    async def health(self) -> dict:
        return {"ok": True}


@pytest.fixture()
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture()
def service(tmp_db, provider) -> MailService:
    async def no_sleep(_: float) -> None:
        await asyncio.sleep(0)

    svc = MailService(provider_factory=lambda cfg: provider, sleep=no_sleep)
    svc.save_config(domain=DOMAIN, worker_url="https://mail.example.workers.dev", token="tok-123")
    return svc


@pytest.fixture()
def profile(tmp_db) -> str:
    return db.create_profile(name="Mail Test", fingerprint_seed=7)["id"]


# ── extracting codes and links ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "subject,text,expected",
    [
        ("Your verification code", "Hi,\n\nYour code is 483920. It expires in 10 minutes.\nSent 2024", ["483920"]),
        ("123456 is your Acme code", "Do not share it.", ["123456"]),
        ("Confirm your email", "Enter this security code: 123 456 to continue.", ["123456"]),
        ("Welcome", "Your order #123456 shipped in 2025", []),
        ("Welcome", "Hello\n\n8421\n\nThanks", ["8421"]),
        ("验证码", "您的验证码是 902341，5 分钟内有效。", ["902341"]),
        ("Confirm", "Use OTP A1B2C3 to sign in", ["A1B2C3"]),
        ("Hi", "Call 555-1234 or visit us in 1999", []),
    ],
)
def test_extract_codes(subject, text, expected):
    assert mailbox.extract_codes(subject, text) == expected


def test_extract_links_prefers_verification_links_and_drops_noise():
    text = "Click https://acme.com/verify?token=abc123. Unsubscribe: https://acme.com/unsubscribe/9"
    html = '<img src="https://cdn.acme.com/logo.png"><a href="https://acme.com/home?a=1&amp;b=2">Home</a>'
    links = mailbox.extract_links(text, html)
    assert links[0] == {"url": "https://acme.com/verify?token=abc123", "likely_verification": True}
    assert {"url": "https://acme.com/home?a=1&b=2", "likely_verification": False} in links
    assert not any("unsubscribe" in l["url"] or l["url"].endswith(".png") for l in links)
    assert mailbox.extract_links(None, None) == []


def test_html_to_text_keeps_the_readable_part():
    text = mailbox.html_to_text("<style>p{}</style><p>Your code is <b>483920</b></p><script>x()</script><div>Bye</div>")
    assert "483920" in text and "Bye" in text and "x()" not in text and "p{}" not in text


def test_new_local_part_is_mailbox_safe_and_varied():
    parts = {mailbox.new_local_part() for _ in range(200)}
    assert len(parts) > 150
    assert all(re.fullmatch(r"[a-z0-9._]{3,30}", p) for p in parts)


# ── configuration ────────────────────────────────────────────────────────────


def test_config_validation_and_token_never_leaks(tmp_db):
    svc = MailService()
    assert svc.public_config()["configured"] is False
    with pytest.raises(MailError):
        svc.save_config(domain="not a domain")
    with pytest.raises(MailError):
        svc.save_config(worker_url="ftp://x")
    public = svc.save_config(domain="@Mail.Test", worker_url="https://w.example.dev/", token="s3cret-token")
    assert public["domain"] == "mail.test" and public["worker_url"] == "https://w.example.dev"
    assert public["has_token"] is True and "s3cret-token" not in json.dumps(public)
    assert "s3cret-token" not in (db.get_setting(mailbox.SETTING_TOKEN) or "")  # encrypted at rest
    assert svc.config().token == "s3cret-token"
    assert svc.save_config(clear_token=True)["has_token"] is False


async def test_unconfigured_service_says_what_is_missing(tmp_db, profile):
    with pytest.raises(MailError) as err:
        await MailService().new_address(profile)
    assert err.value.reason == "mail_not_configured"


# ── addresses, sync and waiting ──────────────────────────────────────────────


async def test_new_address_registers_with_the_provider_and_belongs_to_the_profile(service, provider, profile):
    entry = await service.new_address(profile, "example.com", "sign-up")
    assert entry["address"].endswith(f"@{DOMAIN}") and entry["profile_id"] == profile
    assert entry["address"] in provider.addresses
    assert db.get_mail_address(entry["address"].upper())["site"] == "example.com"


async def test_daily_quota(service, profile):
    service.save_config(max_new_per_day=2)
    await service.new_address(profile)
    await service.new_address(profile)
    with pytest.raises(MailError) as err:
        await service.new_address(profile)
    assert err.value.reason == "quota_exceeded"


async def test_wait_returns_the_mail_with_codes_and_links_and_marks_it_read(service, provider, profile):
    address = (await service.new_address(profile, "acme.example"))["address"]
    provider.deliver(address, "Your Acme code", "Your code is 483920\nOr open https://acme.example/verify?t=1",
                     html='<a href="https://acme.example/verify?t=1">Verify</a>')
    message = await service.wait(profile, address, timeout_s=5)
    assert message["codes"] == ["483920"] and message["subject"] == "Your Acme code"
    assert message["links"][0]["likely_verification"] is True
    assert message["from"] == "noreply@acme.example" and message["untrusted_content"] is True
    assert "html" not in message  # raw HTML never reaches the agent
    # read now: a second wait does not return the same mail
    assert await service.wait(profile, address, timeout_s=1) is None


async def test_wait_picks_up_mail_that_arrives_while_waiting(service, provider, profile):
    address = (await service.new_address(profile))["address"]
    calls = {"n": 0}
    original = provider.fetch

    async def fetch_then_deliver(after, limit=50):
        calls["n"] += 1
        if calls["n"] == 3:
            provider.deliver(address, "Late", "code: 112233")
        return await original(after, limit)

    provider.fetch = fetch_then_deliver
    message = await service.wait(profile, address, timeout_s=30)
    assert message["codes"] == ["112233"] and calls["n"] >= 3


async def test_wait_filters_by_sender_and_subject_and_times_out(service, provider, profile):
    address = (await service.new_address(profile))["address"]
    provider.deliver(address, "Newsletter", "buy now", sender="promo@shop.example", sender_name="Shop")
    provider.deliver(address, "Confirm your account", "code 777888", sender="noreply@acme.example", sender_name="Acme")
    message = await service.wait(profile, address, from_contains="ACME", subject_contains="confirm", timeout_s=2)
    assert message["codes"] == ["777888"]
    assert await service.wait(profile, address, from_contains="nobody", timeout_s=1) is None


async def test_mail_to_unregistered_addresses_is_never_stored(service, provider, profile):
    address = (await service.new_address(profile))["address"]
    assert provider.deliver(f"stranger@{DOMAIN}", "hi", "hi") is False
    assert await service.sync() == 0
    assert db.list_mail_messages(address) == []


async def test_an_agent_cannot_read_another_profiles_mail(service, provider, profile):
    other = db.create_profile(name="Other", fingerprint_seed=8)["id"]
    address = (await service.new_address(profile))["address"]
    provider.deliver(address, "Secret", "code 135790")
    await service.sync()
    message_id = db.list_mail_messages(address)[0]["id"]
    for call in (service.wait(other, address, timeout_s=1),):
        with pytest.raises(MailError) as err:
            await call
        assert err.value.reason == "not_found"
    with pytest.raises(MailError):
        service.list_messages(other, address)
    with pytest.raises(MailError):
        service.read_message(other, message_id)
    assert service.read_message(profile, message_id)["codes"] == ["135790"]


async def test_sync_is_incremental_dedupes_and_survives_a_reset_worker(service, provider, profile):
    address = (await service.new_address(profile))["address"]
    for i in range(3):
        provider.deliver(address, f"m{i}", f"code 10000{i}")
    assert await service.sync() == 3
    assert await service.sync() == 0
    assert db.get_setting(mailbox.SETTING_CURSOR) == "3"
    # The Worker's database was wiped: its sequence restarts below our cursor.
    provider.messages, provider.seq = [], 0
    provider.deliver(address, "after reset", "code 999000")
    assert await service.sync() == 1
    assert db.list_mail_messages(address, limit=1)[0]["subject"] == "after reset"


async def test_wait_gives_up_after_repeated_provider_failures(service, provider, profile):
    address = (await service.new_address(profile))["address"]
    provider.fail_next = 10
    with pytest.raises(MailError) as err:
        await service.wait(profile, address, timeout_s=60)
    assert err.value.reason == "mail_provider_unreachable" and provider.fetches == 3


async def test_stored_bodies_are_encrypted_and_old_mail_is_purged(service, provider, profile):
    address = (await service.new_address(profile))["address"]
    provider.deliver(address, "Code", "your code is 424242")
    await service.sync()
    with db.get_db() as conn:
        raw = conn.execute("SELECT body_enc FROM mail_messages").fetchone()["body_enc"]
    assert raw.startswith("enc::") and "424242" not in raw
    cutoff = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).isoformat()
    assert db.purge_mail_older_than(cutoff) == 1
    assert db.list_mail_messages(address) == []


async def test_delete_address_unregisters_it(service, provider, profile):
    address = (await service.new_address(profile))["address"]
    assert await service.delete_address(address) is True
    assert address not in provider.addresses and db.get_mail_address(address) is None


# ── the real HTTP client against a mocked Worker ─────────────────────────────


async def test_worker_provider_speaks_the_worker_api():
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.url.params)))
        assert request.headers["authorization"] == "Bearer tok"
        if request.url.path == "/messages":
            return httpx.Response(200, json={"max_seq": 5, "messages": [{
                "seq": 5, "id": "x", "address": "A@mail.test", "from": "n@acme.example", "from_name": "Acme",
                "subject": "S", "text": "t", "html": None, "received_at": "2026-10-26T00:00:00Z",
            }]})
        return httpx.Response(200, json={"ok": True})

    provider = WorkerProvider("https://w.dev/", "tok", transport=httpx.MockTransport(handler))
    await provider.register("a@mail.test")
    await provider.forget("a@mail.test")
    messages, top = await provider.fetch(4, 10)
    assert top == 5 and messages[0].address == "a@mail.test" and messages[0].sender_name == "Acme"
    assert [(m, p) for m, p, _ in seen] == [("PUT", "/addresses"), ("DELETE", "/addresses"), ("GET", "/messages")]
    assert seen[2][2] == {"after": "4", "limit": "10"}


@pytest.mark.parametrize(
    "response,reason",
    [(httpx.Response(401, json={}), "mail_provider_error"), (httpx.Response(500, text="x"), "mail_provider_error"),
     (httpx.Response(200, text="<html>not json</html>"), "mail_provider_error")],
)
async def test_worker_provider_errors_are_structured(response, reason):
    provider = WorkerProvider("https://w.dev", "tok", transport=httpx.MockTransport(lambda r: response))
    with pytest.raises(MailError) as err:
        await provider.health()
    assert err.value.reason == reason


async def test_worker_provider_unreachable():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=request)

    with pytest.raises(MailError) as err:
        await WorkerProvider("https://w.dev", "tok", transport=httpx.MockTransport(boom)).health()
    assert err.value.reason == "mail_provider_unreachable"


# ── the vault ────────────────────────────────────────────────────────────────


def test_generated_passwords_cover_every_class_and_avoid_lookalikes():
    for _ in range(200):
        password = vault.generate_password()
        assert len(password) == 20
        assert re.search(r"[a-z]", password) and re.search(r"[A-Z]", password)
        assert re.search(r"\d", password) and re.search(r"[!@#$%^&*\-_=+]", password)
        assert not set(password) & set("lIO01")
    plain = vault.generate_password(12, symbols=False)
    assert plain.isalnum() and len(plain) == 12
    assert len(vault.generate_password(500)) == 64 and len(vault.generate_password(1)) == 12


def test_site_key_normalises_and_rejects_nonsense():
    assert vault.site_key("https://www.Example.com/signup?x=1") == "example.com"
    assert vault.site_key("example.com") == "example.com"
    for bad in ("", "   ", "localhost", "not a site", "http://"):
        with pytest.raises(vault.VaultError):
            vault.site_key(bad)


def test_entry_view_never_contains_the_password(tmp_db, profile):
    entry = db.create_vault_entry(profile_id=profile, site="example.com", username="u", email="u@mail.test", password="Sup3r-secret-pw!")
    view = vault.entry_view(db.get_vault_entry(entry["id"]))
    assert "Sup3r-secret-pw!" not in json.dumps(view) and "password" not in {k for k in view if k != "refs"}
    assert view["refs"]["password"] == "{{vault:%s.password}}" % entry["id"]
    with db.get_db() as conn:
        assert "Sup3r-secret-pw!" not in conn.execute("SELECT password_enc FROM vault_entries").fetchone()[0]


def test_references_resolve_only_on_the_owning_profile(tmp_db, profile):
    other = db.create_profile(name="Other", fingerprint_seed=9)["id"]
    entry = db.create_vault_entry(profile_id=profile, site="example.com", username="kcarter61", email="k@mail.test", password="Sup3r-secret-pw!")
    ref = lambda field: "{{vault:%s.%s}}" % (entry["id"], field)  # noqa: E731
    assert vault.resolve_refs(f"{ref('username')} / {ref('password')}", profile) == "kcarter61 / Sup3r-secret-pw!"
    assert vault.resolve_refs("no refs here", profile) == "no refs here"
    for text, who in ((ref("password"), other), ("{{vault:deadbeefdeadbeef.password}}", profile)):
        with pytest.raises(vault.VaultError) as err:
            vault.resolve_refs(text, who)
        assert err.value.reason == "vault_ref_invalid"


def test_redaction_rewrites_plaintext_passwords_everywhere(tmp_db, profile):
    entry = db.create_vault_entry(profile_id=profile, site="example.com", username="u", email=None, password="Sup3r-secret-pw!")
    db.create_vault_entry(profile_id=profile, site="b.com", username="u", email=None, password="short")  # too short to redact
    mapping = vault.redaction_map(profile)
    assert list(mapping.values()) == ["{{vault:%s.password}}" % entry["id"]]
    out = vault.redact({"snapshot": 'textbox "Password" value="Sup3r-secret-pw!"', "n": 3, "list": ["x Sup3r-secret-pw! y"]}, mapping)
    assert "Sup3r-secret-pw!" not in json.dumps(out) and out["n"] == 3
    assert vault.redact("untouched", {}) == "untouched"


# ── over HTTP ────────────────────────────────────────────────────────────────


@pytest.fixture()
def mail_client(app_client, provider, monkeypatch):
    from backend import main

    monkeypatch.setattr(main.agent_mail, "_provider_factory", lambda cfg: provider)
    resp = app_client.put(
        "/api/settings/mail", json={"domain": DOMAIN, "worker_url": "https://w.example.dev", "token": "tok-123"}
    )
    assert resp.status_code == 200 and resp.json()["configured"] is True
    return app_client


@pytest.fixture()
def pid(mail_client) -> str:
    return mail_client.post("/api/profiles", json={"name": "Signup"}).json()["id"]


def test_settings_endpoint_hides_the_token_and_can_test_the_connection(mail_client):
    body = mail_client.get("/api/settings/mail").json()
    assert body["domain"] == DOMAIN and body["has_token"] is True and "tok-123" not in json.dumps(body)
    assert mail_client.post("/api/settings/mail/test").json() == {"ok": True, "domain": DOMAIN}
    assert mail_client.put("/api/settings/mail", json={"domain": "nope"}).json()["reason"] == "invalid_argument"


def test_sign_up_flow_over_http(mail_client, provider, pid):
    prepared = mail_client.post(f"/api/profiles/{pid}/account/prepare", json={"site": "https://www.acme.example/join"}).json()
    assert prepared["ok"] is True and prepared["email"].endswith(f"@{DOMAIN}")
    entry = prepared["entry"]
    assert entry["site"] == "acme.example" and set(entry["refs"]) == {"password", "username", "email"}
    assert "password" not in {k for k in entry if k != "refs"}

    provider.deliver(prepared["email"], "Your Acme code", "Your code is 482910")
    got = mail_client.post(f"/api/profiles/{pid}/mail/wait", json={"address": prepared["email"], "timeout_s": 5}).json()
    assert got["ok"] is True and got["message"]["codes"] == ["482910"]
    timeout = mail_client.post(f"/api/profiles/{pid}/mail/wait", json={"address": prepared["email"], "timeout_s": 1}).json()
    assert timeout["reason"] == "mail_timeout"

    marked = mail_client.patch(f"/api/profiles/{pid}/vault/{entry['id']}", json={"status": "verified", "notes": "ok"}).json()
    assert marked["entry"]["status"] == "verified"
    assert mail_client.patch(f"/api/profiles/{pid}/vault/{entry['id']}", json={"status": "bogus"}).json()["reason"] == "invalid_argument"
    listed = mail_client.get(f"/api/profiles/{pid}/vault").json()["entries"]
    assert [e["id"] for e in listed] == [entry["id"]]

    # a person can read the password back; the agent-facing views never include it
    revealed = mail_client.post(f"/api/vault/{entry['id']}/reveal").json()
    assert len(revealed["password"]) == 20 and revealed["email"] == prepared["email"]
    assert revealed["password"] not in json.dumps([prepared, got, marked, listed])
    assert mail_client.delete(f"/api/vault/{entry['id']}").json() == {"ok": True}


def test_unknown_profile_unconfigured_mail_and_quota(app_client, mail_client, pid):
    assert mail_client.post("/api/profiles/nope/account/prepare", json={"site": "a.example"}).status_code == 404
    mail_client.put("/api/settings/mail", json={"max_new_per_day": 1})
    assert mail_client.post(f"/api/profiles/{pid}/account/prepare", json={"site": "a.example"}).json()["ok"] is True
    again = mail_client.post(f"/api/profiles/{pid}/account/prepare", json={"site": "b.example"})
    assert again.status_code == 429 and again.json()["reason"] == "quota_exceeded"
    mail_client.put("/api/settings/mail", json={"clear_token": True})
    off = mail_client.post(f"/api/profiles/{pid}/mail/address", json={})
    assert off.json()["reason"] == "mail_not_configured"


def test_agent_tokens_cannot_reach_the_vault_or_mail_settings():
    from backend import agent_auth

    for path in ("/api/vault", "/api/vault/abc/reveal", "/api/settings/mail", "/api/mail/addresses",
                 "/api/profiles/p1/vault", "/api/profiles/p1/account/prepare"):
        for scope in agent_auth.SCOPES:
            assert not agent_auth.path_allowed(scope, "GET", path), (scope, path)
            assert not agent_auth.path_allowed(scope, "POST", path), (scope, path)


# ── typing a reference into a real page, and never echoing the password back ──


def test_browser_type_resolves_vault_references_and_snapshots_are_redacted(mail_client, provider, pid, monkeypatch):
    from backend import main
    from backend.tests.test_agent_api import FakeContext, FakeElement, FakeSnapshotHandle, SelectorPage

    prepared = mail_client.post(f"/api/profiles/{pid}/account/prepare", json={"site": "acme.example"}).json()
    entry_id = prepared["entry"]["id"]
    password = mail_client.post(f"/api/vault/{entry_id}/reveal").json()["password"]

    page, box = SelectorPage(), FakeElement("input")
    page.table = {"label:Password": [box]}
    context = FakeContext()
    context.pages.append(page)
    monkeypatch.setitem(main.browser_mgr.running, pid, MagicMock(cdp_port=9222, context=context))

    typed = mail_client.post(f"/api/profiles/{pid}/page/type", json={"ref": "label=Password", "text": "{{vault:%s.password}}" % entry_id})
    assert typed.status_code == 200
    assert box.filled == password  # the page got the real value...
    assert password not in typed.text  # ...the agent's answer never carries it

    # a "show password" toggle makes the page echo it into a snapshot: it is rewritten on the way out
    page.snapshot_handle = FakeSnapshotHandle([f'[e0] textbox "Password" value="{password}"'], [FakeElement("input")])
    snapshot = mail_client.post(f"/api/profiles/{pid}/page/snapshot", json={})
    assert password not in snapshot.text and "{{vault:%s.password}}" % entry_id in snapshot.text

    # references work inside a batch, too, and only for the owning profile
    batch = mail_client.post(
        f"/api/profiles/{pid}/page/batch",
        json={"steps": [{"do": "type", "ref": "label=Password", "text": "{{vault:%s.password}}" % entry_id}], "snapshot_after": False},
    )
    assert batch.json()["completed"] == 1 and password not in batch.text
    other = mail_client.post("/api/profiles", json={"name": "Other"}).json()["id"]
    monkeypatch.setitem(main.browser_mgr.running, other, MagicMock(cdp_port=9222, context=context))
    stolen = mail_client.post(f"/api/profiles/{other}/page/type", json={"ref": "label=Password", "text": "{{vault:%s.password}}" % entry_id})
    assert stolen.json()["reason"] == "vault_ref_invalid" and box.filled == password
