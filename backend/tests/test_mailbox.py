"""Mail for agents: addresses on the user's Cloud Mail server, codes pulled out of mail."""

from __future__ import annotations

import json
import time

import httpx
import pytest
from starlette.testclient import TestClient

from backend import agent_tools, mailbox
from backend import database as db

# ── Code and link extraction ─────────────────────────────────────────────────


@pytest.mark.parametrize(("subject", "text", "code"), [
    ("Your verification code", "Hello, your verification code is 905172. It expires in 10 minutes. © 2026", "905172"),
    ("482913 is your GitHub launch code", "Enter it to sign in.", "482913"),
    ("验证码通知", "您的验证码为：3829，5 分钟内有效。客服电话 400-123-4567", "3829"),
    ("確認コード", "あなたの確認コードは 771204 です。", "771204"),
    ("Welcome", "Thanks for joining in 2026! Order #123456 ships soon.", None),
    ("Sign in", "Use code AB12CD to finish signing in.", "AB12CD"),
    ("Your receipt", "Total $1299.00, card ending 4242", None),
    ("Confirm your email", "Your code: 615 284 is not one block; your code is 615284", "615284"),
])
def test_extract_code(subject, text, code):
    assert mailbox.extract_code(subject, text) == code


def test_extract_link_skips_unsubscribe_and_images():
    raw = (
        '<img src="https://cdn.example.com/verify-banner.png">'
        '<a href="https://example.com/unsubscribe?u=1">Unsubscribe</a>'
        '<a href="https://example.com/email/verify?token=abc&amp;u=2">Verify</a>'
    )
    assert mailbox.extract_link(raw, "") == "https://example.com/email/verify?token=abc&u=2"
    assert mailbox.extract_link("", "Just text, no links") is None


def test_html_mail_without_text_part_is_readable():
    message = mailbox.shape_message({
        "emailId": 7, "toEmail": "a@x.site", "sendEmail": "no-reply@x.com", "subject": "Hi",
        "content": "<style>p{}</style><p>Your code is <b>123456</b></p>", "text": "", "createTime": "2026-10-27 18:20:22",
    })
    assert message["text"] == "Your code is 123456"
    assert message["code"] == "123456"
    assert message["received_at"] == "2026-10-27T18:20:22Z"


# ── A fake Cloud Mail server ─────────────────────────────────────────────────


class FakeCloudMail:
    """Login, settings, account/add and the admin all-mail list, as the real API answers."""

    def __init__(self) -> None:
        self.password = "secret"
        self.tokens: set[str] = set()
        self.logins = 0
        self.accounts: set[str] = {"taken@anyeco.site"}
        self.mail: list[dict] = []
        self.next_id = 100
        self.transport = httpx.MockTransport(self.handle)

    def deliver(self, to: str, subject: str, text: str, sender: str = "no-reply@service.com") -> int:
        self.next_id += 1
        self.mail.insert(0, {"emailId": self.next_id, "toEmail": to, "sendEmail": sender, "name": "Service",
                             "subject": subject, "text": text, "content": "", "createTime": "2026-10-27 18:20:22"})
        return self.next_id

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api")
        ok = lambda data=None: httpx.Response(200, json={"code": 200, "message": "success", "data": data})  # noqa: E731
        if path == "/login":
            body = json.loads(request.content)
            if body["password"] != self.password:
                return httpx.Response(200, json={"code": 500, "message": "账号或密码错误"})
            self.logins += 1
            token = f"t{self.logins}"
            self.tokens.add(token)
            return ok({"token": token})
        if request.headers.get("Authorization") not in self.tokens:
            return httpx.Response(200, json={"code": 401, "message": "身份认证失效,请重新登录"})
        if path == "/setting/query":
            return ok({"domainList": ["@anyeco.site", "@koocoo.site"]})
        if path == "/account/add":
            email = json.loads(request.content)["email"]
            if email in self.accounts:
                return httpx.Response(200, json={"code": 500, "message": "该邮箱已存在"})
            self.accounts.add(email)
            return ok({"email": email})
        if path == "/allEmail/list":
            wanted = request.url.params.get("accountEmail", "")
            size = int(request.url.params.get("size", 20))
            rows = [m for m in self.mail if wanted.lower() in m["toEmail"].lower()][:size]
            return ok({"list": rows, "total": len(rows)})
        return httpx.Response(404)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeCloudMail:
    server = FakeCloudMail()
    mailbox._TOKENS.clear()
    monkeypatch.setattr(
        mailbox.CloudMailClient,
        "_client",
        lambda self: httpx.AsyncClient(base_url=f"{self.config.base_url}/api", transport=server.transport),
    )
    monkeypatch.setattr(mailbox, "POLL_SECONDS", 0.01)
    return server


def _config(password: str = "secret") -> mailbox.MailConfig:
    return mailbox.MailConfig("https://mail.anyeco.site", "admin@anyeco.site", password, ())


@pytest.mark.asyncio
async def test_client_logs_in_once_and_again_when_the_token_expires(fake: FakeCloudMail):
    client = mailbox.CloudMailClient(_config())
    assert await client.domains() == ["anyeco.site", "koocoo.site"]
    assert await client.domains() == ["anyeco.site", "koocoo.site"]
    assert fake.logins == 1
    fake.tokens.clear()  # the server forgot the session
    assert await client.domains() == ["anyeco.site", "koocoo.site"]
    assert fake.logins == 2


@pytest.mark.asyncio
async def test_wrong_password_is_reported(fake: FakeCloudMail):
    with pytest.raises(mailbox.MailServerError, match="账号或密码错误"):
        await mailbox.CloudMailClient(_config("nope")).check()


@pytest.mark.asyncio
async def test_messages_only_for_exactly_that_address(fake: FakeCloudMail):
    fake.deliver("mia.kang58@anyeco.site", "code", "your code is 111111")
    fake.deliver("mia.kang581@anyeco.site", "code", "your code is 222222")  # matches the server's fuzzy filter
    messages = await mailbox.CloudMailClient(_config()).messages("MIA.KANG58@anyeco.site")
    assert [m["code"] for m in messages] == ["111111"]


@pytest.mark.asyncio
async def test_wait_returns_only_newer_matching_mail(fake: FakeCloudMail):
    client = mailbox.CloudMailClient(_config())
    old = fake.deliver("a@anyeco.site", "Your code", "your code is 111111")
    assert await mailbox.wait_for_message(client, "a@anyeco.site", after_id=old, timeout=0.05) is None
    fake.deliver("a@anyeco.site", "Newsletter", "nothing", sender="news@shop.com")
    fake.deliver("a@anyeco.site", "Your GitHub code", "your code is 333333", sender="noreply@github.com")
    found = await mailbox.wait_for_message(client, "a@anyeco.site", after_id=old, timeout=1, from_contains="github")
    assert found["code"] == "333333"


# ── REST routes ──────────────────────────────────────────────────────────────


def _configure(app_client: TestClient) -> dict:
    resp = app_client.put("/api/settings/mail", json={
        "base_url": "mail.anyeco.site", "admin_email": "admin@anyeco.site", "password": "secret", "domains": ["@anyeco.site"],
    })
    assert resp.status_code == 200
    return resp.json()


def test_settings_never_return_the_password(app_client: TestClient, fake: FakeCloudMail):
    status = _configure(app_client)
    assert status == {"configured": True, "base_url": "https://mail.anyeco.site", "admin_email": "admin@anyeco.site",
                      "has_password": True, "domains": ["anyeco.site"]}
    assert "secret" not in json.dumps(app_client.get("/api/settings/mail").json())
    assert "secret" not in (db.get_setting(mailbox.SETTING_ADMIN_PASSWORD) or "")  # stored encrypted
    # An empty password keeps the stored one.
    kept = app_client.put("/api/settings/mail", json={"base_url": "mail.anyeco.site", "admin_email": "admin@anyeco.site"}).json()
    assert kept["has_password"] is True
    assert app_client.post("/api/mail/check").json() == {"ok": True, "domains": ["anyeco.site", "koocoo.site"]}


def test_unconfigured_mail_answers_409(app_client: TestClient):
    resp = app_client.post("/api/mail/addresses", json={})
    assert resp.status_code == 409
    assert "邮箱" in resp.json()["detail"]


def test_address_for_a_profile_then_wait_for_its_code(app_client: TestClient, fake: FakeCloudMail):
    _configure(app_client)
    profile_id = app_client.post("/api/profiles", json={"name": "Signup"}).json()["id"]
    created = app_client.post("/api/mail/addresses", json={"profile_id": profile_id})
    assert created.status_code == 201
    address = created.json()["address"]
    assert address.endswith("@anyeco.site") and address in fake.accounts
    assert created.json()["profile_name"] == "Signup"
    assert [a["address"] for a in app_client.get(f"/api/mail/addresses?profile_id={profile_id}").json()] == [address]

    fake.deliver(address, "Verify your email", "Your verification code is 482913.")
    first = app_client.post("/api/mail/wait", json={"address": address, "timeout_s": 1}).json()
    assert first["found"] is True and first["message"]["code"] == "482913"
    # The same mail is not handed out twice...
    assert app_client.post("/api/mail/wait", json={"address": address, "timeout_s": 0}).json()["found"] is False
    # ...unless asked for.
    again = app_client.post("/api/mail/wait", json={"address": address, "timeout_s": 0, "include_delivered": True}).json()
    assert again["message"]["code"] == "482913"
    listed = app_client.get(f"/api/mail/messages?address={address}").json()
    assert listed["last_delivered_id"] == first["message"]["id"]
    assert app_client.delete(f"/api/mail/addresses/{address}").json() == {"ok": True}


def test_a_chosen_prefix_that_is_taken_is_refused(app_client: TestClient, fake: FakeCloudMail):
    _configure(app_client)
    resp = app_client.post("/api/mail/addresses", json={"local_part": "taken", "domain": "anyeco.site"})
    assert resp.status_code == 502
    assert "已存在" in resp.json()["detail"]
    bad = app_client.post("/api/mail/addresses", json={"local_part": "-bad", "domain": "anyeco.site"})
    assert bad.status_code == 400
    unknown = app_client.post("/api/mail/addresses", json={"domain": "other.com"})
    assert unknown.status_code == 400 and "anyeco.site" in unknown.json()["detail"]


def test_random_prefix_retries_when_taken(app_client: TestClient, fake: FakeCloudMail, monkeypatch: pytest.MonkeyPatch):
    _configure(app_client)
    names = iter(["taken", "fresh.name10"])
    monkeypatch.setattr(mailbox, "random_local_part", lambda: next(names))
    resp = app_client.post("/api/mail/addresses", json={"domain": "anyeco.site"})
    assert resp.json()["address"] == "fresh.name10@anyeco.site"


def test_unknown_address_is_404(app_client: TestClient, fake: FakeCloudMail):
    _configure(app_client)
    assert app_client.post("/api/mail/wait", json={"address": "nobody@anyeco.site", "timeout_s": 0}).status_code == 404


# ── Agent tools ──────────────────────────────────────────────────────────────


def _rest(app_client: TestClient) -> agent_tools.RestClient:
    """An agent RestClient that reaches the test app in-process."""
    from backend import main

    return agent_tools.RestClient("http://127.0.0.1:8080", transport=httpx.ASGITransport(app=main.app), token="")


@pytest.mark.asyncio
async def test_agent_gets_one_address_per_profile_and_its_code(app_client: TestClient, fake: FakeCloudMail):
    _configure(app_client)
    app_client.post("/api/profiles", json={"name": "Signup"})
    rest = _rest(app_client)
    tool = lambda name: agent_tools.TOOLS[name].handler  # noqa: E731

    first = await tool("mail_get_address")(rest, {"profile": "Signup"})
    assert first["ok"] and first["created"] is True
    same = await tool("mail_get_address")(rest, {"profile": "Signup"})
    assert same["address"] == first["address"] and same["created"] is False
    other = await tool("mail_get_address")(rest, {"profile": "Signup", "new": True})
    assert other["address"] != first["address"]

    started = time.monotonic()
    timeout = await tool("mail_wait_code")(rest, {"address": first["address"], "timeout_s": 0})
    assert timeout["ok"] is False and timeout["reason"] == "mail_timeout"
    assert time.monotonic() - started < 5  # timeout_s=0 means no waiting, not the 120 s default
    fake.deliver(first["address"], "Your code", "your code is 246810", sender="noreply@github.com")
    got = await tool("mail_wait_code")(rest, {"address": first["address"], "timeout_s": 1})
    assert (got["ok"], got["code"], got["from"]) == (True, "246810", "noreply@github.com")
    listed = await tool("mail_list_messages")(rest, {"address": first["address"]})
    assert listed["count"] == 1 and listed["messages"][0]["code"] == "246810"


@pytest.mark.asyncio
async def test_agent_is_told_when_mail_is_not_set_up(app_client: TestClient):
    app_client.post("/api/profiles", json={"name": "Signup"})
    result = await agent_tools.TOOLS["mail_get_address"].handler(_rest(app_client), {"profile": "Signup"})
    assert result["reason"] == "mail_not_configured"
    assert "mail_not_configured" in agent_tools.NEXT_STEPS


def test_mail_tools_need_full_mode():
    names = {t.name for t in agent_tools.visible_tools("read-only")}
    assert not names & {"mail_get_address", "mail_wait_code", "mail_list_messages"}
    assert {"mail_get_address", "mail_wait_code"} <= {t.name for t in agent_tools.visible_tools("full")}
