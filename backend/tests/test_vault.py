"""Tests for the credential vault: generated passwords agents never see, references,
echo redaction and the HTTP surface."""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock

import pytest

from backend import agent_auth, vault, vault_api
from backend import database as db


@pytest.fixture()
def profile(tmp_db) -> str:
    return db.create_profile(name="Vault Test", fingerprint_seed=7)["id"]


# ── generating ───────────────────────────────────────────────────────────────


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


def test_usernames_are_plausible_and_varied():
    names = {vault.new_username() for _ in range(200)}
    assert len(names) > 150
    assert all(re.fullmatch(r"[a-z0-9._]{3,30}", n) for n in names)


def test_site_key_normalises_and_rejects_nonsense():
    assert vault.site_key("https://www.Example.com/signup?x=1") == "example.com"
    assert vault.site_key("example.com") == "example.com"
    for bad in ("", "   ", "localhost", "not a site", "http://"):
        with pytest.raises(vault.VaultError):
            vault.site_key(bad)


# ── storing and referencing ──────────────────────────────────────────────────


def test_entry_view_never_contains_the_password_and_it_is_encrypted_at_rest(tmp_db, profile):
    entry = db.create_vault_entry(profile_id=profile, site="example.com", username="u", email="u@mail.test", password="Sup3r-secret-pw!")
    view = vault.entry_view(db.get_vault_entry(entry["id"]))
    assert "Sup3r-secret-pw!" not in json.dumps(view) and "password" not in {k for k in view if k != "refs"}
    assert view["refs"]["password"] == "{{vault:%s.password}}" % entry["id"]
    with db.get_db() as conn:
        stored = conn.execute("SELECT password_enc FROM vault_entries").fetchone()[0]
    assert stored.startswith("enc::") and "Sup3r-secret-pw!" not in stored


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
def pid(app_client) -> str:
    return app_client.post("/api/profiles", json={"name": "Signup"}).json()["id"]


def test_vault_flow_over_http(app_client, pid):
    created = app_client.post(f"/api/profiles/{pid}/vault", json={"site": "https://www.acme.example/join", "email": "a@mail.test", "generate_username": True}).json()
    assert created["ok"] is True
    entry = created["entry"]
    assert entry["site"] == "acme.example" and set(entry["refs"]) == {"password", "username", "email"}
    assert entry["username"] and "password" not in {k for k in entry if k != "refs"}

    marked = app_client.patch(f"/api/profiles/{pid}/vault/{entry['id']}", json={"status": "verified", "notes": "ok"}).json()
    assert marked["entry"]["status"] == "verified" and marked["entry"]["notes"] == "ok"
    assert app_client.patch(f"/api/profiles/{pid}/vault/{entry['id']}", json={"status": "bogus"}).json()["reason"] == "invalid_argument"
    assert [e["id"] for e in app_client.get(f"/api/profiles/{pid}/vault").json()["entries"]] == [entry["id"]]
    assert [e["id"] for e in app_client.get("/api/vault").json()["entries"]] == [entry["id"]]

    # a person can read the password back; the agent-facing views never include it
    revealed = app_client.post(f"/api/vault/{entry['id']}/reveal").json()
    assert len(revealed["password"]) == 20 and revealed["email"] == "a@mail.test"
    assert revealed["password"] not in json.dumps([created, marked])
    assert app_client.delete(f"/api/vault/{entry['id']}").json() == {"ok": True}
    assert app_client.get("/api/vault").json()["entries"] == []


def test_vault_errors_and_quota(app_client, pid, monkeypatch):
    assert app_client.post("/api/profiles/nope/vault", json={"site": "a.example"}).status_code == 404
    bad = app_client.post(f"/api/profiles/{pid}/vault", json={"site": "not a site"})
    assert bad.status_code == 400 and bad.json()["reason"] == "invalid_argument"
    other = app_client.post("/api/profiles", json={"name": "Other"}).json()["id"]
    entry = app_client.post(f"/api/profiles/{pid}/vault", json={"site": "a.example"}).json()["entry"]
    assert app_client.patch(f"/api/profiles/{other}/vault/{entry['id']}", json={"status": "failed"}).status_code == 404
    monkeypatch.setattr(vault_api, "MAX_NEW_PER_DAY", 1)
    again = app_client.post(f"/api/profiles/{pid}/vault", json={"site": "b.example"})
    assert again.status_code == 429 and again.json()["reason"] == "quota_exceeded"
    assert app_client.post("/api/vault/missing/reveal").json()["reason"] == "not_found"


def test_agent_tokens_cannot_reach_the_vault():
    for path in ("/api/vault", "/api/vault/abc/reveal", "/api/profiles/p1/vault"):
        for scope in agent_auth.SCOPES:
            for method in ("GET", "POST", "DELETE", "PATCH"):
                assert not agent_auth.path_allowed(scope, method, path), (scope, method, path)


# ── typing a reference into a real page, and never echoing the password back ──


def test_browser_type_resolves_references_and_page_output_is_redacted(app_client, pid, monkeypatch):
    from backend import main
    from backend.tests.test_agent_api import FakeContext, FakeElement, FakeSnapshotHandle, SelectorPage

    entry = app_client.post(f"/api/profiles/{pid}/vault", json={"site": "acme.example", "email": "a@mail.test"}).json()["entry"]
    password = app_client.post(f"/api/vault/{entry['id']}/reveal").json()["password"]
    ref = "{{vault:%s.password}}" % entry["id"]

    page, box = SelectorPage(), FakeElement("input")
    page.table = {"label:Password": [box]}
    context = FakeContext()
    context.pages.append(page)
    monkeypatch.setitem(main.browser_mgr.running, pid, MagicMock(cdp_port=9222, context=context))

    typed = app_client.post(f"/api/profiles/{pid}/page/type", json={"ref": "label=Password", "text": ref})
    assert typed.status_code == 200
    assert box.filled == password  # the page got the real value...
    assert password not in typed.text  # ...the agent's answer never carries it

    # a "show password" toggle makes the page echo it into a snapshot: rewritten on the way out
    page.snapshot_handle = FakeSnapshotHandle([f'[e0] textbox "Password" value="{password}"'], [FakeElement("input")])
    snapshot = app_client.post(f"/api/profiles/{pid}/page/snapshot", json={})
    assert password not in snapshot.text and ref in snapshot.text

    # references work inside a batch, too
    batch = app_client.post(
        f"/api/profiles/{pid}/page/batch",
        json={"steps": [{"do": "type", "ref": "label=Password", "text": ref}], "snapshot_after": False},
    )
    assert batch.json()["completed"] == 1 and password not in batch.text

    # ...and only for the profile that owns the entry
    other = app_client.post("/api/profiles", json={"name": "Other"}).json()["id"]
    monkeypatch.setitem(main.browser_mgr.running, other, MagicMock(cdp_port=9222, context=context))
    box.filled = None
    stolen = app_client.post(f"/api/profiles/{other}/page/type", json={"ref": "label=Password", "text": ref})
    assert stolen.json()["reason"] == "vault_ref_invalid" and box.filled is None
