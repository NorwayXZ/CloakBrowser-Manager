"""Mailboxes for agents: hand out an address, then wait for the code sent to it.

An agent signing up somewhere needs an inbox it can read on its own. The user
runs a Cloud Mail server (github.com/maillab/cloud-mail, on Cloudflare Email
Routing) whose admin account can create any address on its domains and read
every message; the Manager talks to its web API with that account.

* Settings: server URL, admin email and its password. The password is stored
  Fernet-encrypted through :mod:`secrets_crypto` and no read path returns it.
* Addresses are created on the server (so the server's own UI shows them) and
  remembered here with the profile they belong to.
* Messages are read through the admin "all mail" list filtered by address;
  verification codes and links are pulled out here, so the agent gets the
  code itself instead of a whole HTML mail.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from .secrets_crypto import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)

SETTING_BASE_URL = "mail_base_url"
SETTING_ADMIN_EMAIL = "mail_admin_email"
SETTING_ADMIN_PASSWORD = "mail_admin_password"
# JSON list of the domains new addresses use; empty means every server domain.
SETTING_DOMAINS = "mail_domains"

REQUEST_SECONDS = 20.0
POLL_SECONDS = 3.0
WAIT_MAX_SECONDS = 170.0  # below the agent tools' 180 s action timeout
MESSAGE_TEXT_LIMIT = 4000

GetSetting = Callable[[str], "str | None"]
SetSetting = Callable[[str, str], None]


class MailError(Exception):
    """A mail operation failed; ``reason`` is a stable code for agents."""

    reason = "mail_error"


class MailNotConfiguredError(MailError):
    reason = "mail_not_configured"


class MailServerError(MailError):
    reason = "mail_server_error"


# ── Configuration ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MailConfig:
    base_url: str
    admin_email: str
    password: str
    domains: tuple[str, ...]


def _domains_setting(get_setting: GetSetting) -> list[str]:
    try:
        raw = json.loads(get_setting(SETTING_DOMAINS) or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [normalize_domain(d) for d in raw if isinstance(d, str) and normalize_domain(d)]


def normalize_domain(value: str) -> str:
    return value.strip().lstrip("@").lower()


def normalize_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if url and "://" not in url:
        url = f"https://{url}"
    return url


def read_config(get_setting: GetSetting) -> MailConfig | None:
    """Full config including the password, or None when incomplete. Internal only."""
    base_url = normalize_base_url(get_setting(SETTING_BASE_URL) or "")
    admin_email = (get_setting(SETTING_ADMIN_EMAIL) or "").strip()
    password = decrypt_value(get_setting(SETTING_ADMIN_PASSWORD)) or ""
    if not base_url or not admin_email or not password:
        return None
    return MailConfig(base_url, admin_email, password, tuple(_domains_setting(get_setting)))


def config_status(get_setting: GetSetting) -> dict[str, Any]:
    """What the panel may see: never the password."""
    return {
        "configured": read_config(get_setting) is not None,
        "base_url": normalize_base_url(get_setting(SETTING_BASE_URL) or "") or None,
        "admin_email": (get_setting(SETTING_ADMIN_EMAIL) or "").strip() or None,
        "has_password": bool(decrypt_value(get_setting(SETTING_ADMIN_PASSWORD))),
        "domains": _domains_setting(get_setting),
    }


def save_config(
    set_setting: SetSetting,
    *,
    base_url: str,
    admin_email: str,
    password: str | None = None,
    clear_password: bool = False,
    domains: list[str] | None = None,
) -> None:
    """The password is write-only: set when given, deleted on ``clear_password``."""
    set_setting(SETTING_BASE_URL, normalize_base_url(base_url))
    set_setting(SETTING_ADMIN_EMAIL, admin_email.strip())
    cleaned = sorted({normalize_domain(d) for d in domains or [] if normalize_domain(d)})
    set_setting(SETTING_DOMAINS, json.dumps(cleaned))
    if clear_password:
        set_setting(SETTING_ADMIN_PASSWORD, "")
    elif password:
        set_setting(SETTING_ADMIN_PASSWORD, encrypt_value(password) or "")
    _TOKENS.clear()


# ── Cloud Mail client ────────────────────────────────────────────────────────

# Login tokens by (server, admin): one login serves every later call.
_TOKENS: dict[tuple[str, str], str] = {}


class CloudMailClient:
    """The few Cloud Mail admin endpoints the Manager uses."""

    def __init__(self, config: MailConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{self.config.base_url}/api",
            timeout=REQUEST_SECONDS,
            transport=self._transport,
            headers={"User-Agent": "CloakBrowser-Manager"},
        )

    @property
    def _key(self) -> tuple[str, str]:
        return (self.config.base_url, self.config.admin_email.lower())

    async def _login(self, client: httpx.AsyncClient) -> str:
        payload = await self._send(
            client, "POST", "/login", json={"email": self.config.admin_email, "password": self.config.password}
        )
        token = payload.get("token") if isinstance(payload, dict) else None
        if not token:
            raise MailServerError("邮箱服务器登录成功但没有返回 token")
        _TOKENS[self._key] = token
        return token

    async def _send(self, client: httpx.AsyncClient, method: str, path: str, *, token: str | None = None, **kw: Any) -> Any:
        headers = {"Authorization": token} if token else {}
        try:
            response = await client.request(method, path, headers=headers, **kw)
        except httpx.TimeoutException as exc:
            raise MailServerError(f"邮箱服务器 {REQUEST_SECONDS:.0f} 秒内没有响应") from exc
        except httpx.HTTPError as exc:
            raise MailServerError(f"连不上邮箱服务器 {self.config.base_url}：{exc}") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise MailServerError(f"邮箱服务器返回的不是 JSON（HTTP {response.status_code}），地址填对了吗？") from exc
        code = body.get("code") if isinstance(body, dict) else None
        if code == 401:
            raise _Unauthorized(str(body.get("message") or "未登录"))
        if code != 200:
            message = str(body.get("message") or f"HTTP {response.status_code}") if isinstance(body, dict) else "未知错误"
            raise MailServerError(message)
        return body.get("data")

    async def call(self, method: str, path: str, **kw: Any) -> Any:
        """One authenticated call; logs in first or again when the token expired."""
        async with self._client() as client:
            token = _TOKENS.get(self._key) or await self._login(client)
            try:
                return await self._send(client, method, path, token=token, **kw)
            except _Unauthorized:
                token = await self._login(client)
                return await self._send(client, method, path, token=token, **kw)

    async def check(self) -> dict[str, Any]:
        """Log in afresh and list the server's domains."""
        async with self._client() as client:
            try:
                await self._login(client)
            except _Unauthorized as exc:
                raise MailServerError(f"登录失败：{exc}") from exc
        return {"ok": True, "domains": await self.domains()}

    async def domains(self) -> list[str]:
        settings = await self.call("GET", "/setting/query")
        raw = settings.get("domainList") if isinstance(settings, dict) else None
        return [normalize_domain(d) for d in raw or [] if isinstance(d, str) and normalize_domain(d)]

    async def create_address(self, address: str) -> None:
        await self.call("POST", "/account/add", json={"email": address, "token": ""})

    async def messages(self, address: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Newest first; only mail sent to exactly this address."""
        data = await self.call(
            "GET",
            "/allEmail/list",
            params={"emailId": 0, "size": max(1, min(limit, 50)), "type": "receive", "timeSort": 0, "accountEmail": address},
        )
        rows = data.get("list") if isinstance(data, dict) else None
        wanted = address.lower()
        return [shape_message(row) for row in rows or [] if str(row.get("toEmail") or "").lower() == wanted]


class _Unauthorized(MailServerError):
    pass


def client_for(get_setting: GetSetting, *, transport: httpx.AsyncBaseTransport | None = None) -> CloudMailClient:
    config = read_config(get_setting)
    if config is None:
        raise MailNotConfiguredError("还没有配置邮箱服务器：请在 Manager 的「邮箱」页填写服务器地址和管理员账号。")
    return CloudMailClient(config, transport=transport)


# ── Messages, codes and links ────────────────────────────────────────────────

_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)
_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_KEYWORD_RE = re.compile(
    r"code|otp|pin|passcode|verif|confirm|one[- ]time|security|验证码|驗證碼|校验码|动态码|確認コード|認証|인증|코드",
    re.I,
)
_DIGITS_RE = re.compile(r"(?<![\w#+.:/-])(\d{4,8})(?!\w|[.:/]\d|-\d)")
_MIXED_RE = re.compile(r"(?<![\w-])([A-Z0-9]{6,8})(?![\w-])")
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)
_LINK_HINT_RE = re.compile(r"verif|confirm|activat|validat|magic|signin|sign-in|login|token|auth|email", re.I)


def html_to_text(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw or "")
    text = html.unescape(text)
    lines = [_SPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_code(subject: str, text: str) -> str | None:
    """The verification code in a mail, or None.

    Prefers a number in the subject, then one close to a word like "code" /
    验证码, then a lone 6-digit number. Years, phone numbers and prices are
    the usual false hits, so 4-digit years need a keyword next to them.
    """
    def candidates(source: str) -> list[tuple[int, str]]:
        found = [(m.start(), m.group(1)) for m in _DIGITS_RE.finditer(source)]
        found += [(m.start(), m.group(1)) for m in _MIXED_RE.finditer(source) if re.search(r"\d", m.group(1)) and re.search(r"[A-Z]", m.group(1))]
        return sorted(found)

    def looks_like_year(value: str) -> bool:
        return len(value) == 4 and value.isdigit() and 1900 <= int(value) <= 2100

    for position, value in candidates(subject or ""):
        if not looks_like_year(value) and _KEYWORD_RE.search(subject):
            return value
    best: tuple[int, str] | None = None
    for position, value in candidates(text or ""):
        window = text[max(0, position - 120): position + 40]
        if not _KEYWORD_RE.search(window):
            continue
        distance = min((abs(position - m.start()) for m in _KEYWORD_RE.finditer(window)), default=999)
        if best is None or distance < best[0]:
            best = (distance, value)
    if best:
        return best[1]
    lone = [value for _, value in candidates(text or "") if len(value) == 6 and value.isdigit()]
    return lone[0] if len(set(lone)) == 1 else None


def extract_link(raw_html: str, text: str) -> str | None:
    """The first link that looks like a verify / confirm / sign-in link."""
    for source in (raw_html or "", text or ""):
        for match in _URL_RE.finditer(html.unescape(source)):
            url = match.group(0).rstrip(".,;")
            if _LINK_HINT_RE.search(url) and not re.search(r"unsubscribe|privacy|terms|\.(png|jpe?g|gif|svg)(\?|$)", url, re.I):
                return url
    return None


def utc_iso(value: Any) -> str | None:
    """Cloud Mail answers "2026-10-27 18:20:22" in UTC; make that explicit."""
    raw = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", raw):
        return raw.replace(" ", "T") + "Z"
    return raw or None


def shape_message(row: dict[str, Any]) -> dict[str, Any]:
    subject = str(row.get("subject") or "")
    raw_html = str(row.get("content") or "")
    text = str(row.get("text") or "").strip() or html_to_text(raw_html)
    return {
        "id": int(row.get("emailId") or 0),
        "to": str(row.get("toEmail") or ""),
        "from": str(row.get("sendEmail") or ""),
        "from_name": str(row.get("name") or "") or None,
        "subject": subject,
        "received_at": utc_iso(row.get("createTime")),
        "code": extract_code(subject, text),
        "link": extract_link(raw_html, text),
        "text": text[:MESSAGE_TEXT_LIMIT],
    }


def _matches(message: dict[str, Any], from_contains: str, subject_contains: str) -> bool:
    if from_contains and from_contains.lower() not in f"{message['from']} {message.get('from_name') or ''}".lower():
        return False
    if subject_contains and subject_contains.lower() not in message["subject"].lower():
        return False
    return True


async def wait_for_message(
    client: CloudMailClient,
    address: str,
    *,
    after_id: int,
    timeout: float,
    from_contains: str = "",
    subject_contains: str = "",
    poll_seconds: float = POLL_SECONDS,
) -> dict[str, Any] | None:
    """The newest matching message with id > ``after_id``, waiting up to ``timeout``."""
    deadline = time.monotonic() + max(0.0, min(timeout, WAIT_MAX_SECONDS))
    while True:
        for message in await client.messages(address, limit=20):
            if message["id"] > after_id and _matches(message, from_contains, subject_contains):
                return message
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))


# ── Addresses ────────────────────────────────────────────────────────────────

_FIRST_NAMES = (
    "olivia", "emma", "ava", "sophia", "mia", "amelia", "harper", "evelyn", "abigail", "emily",
    "ella", "grace", "chloe", "lily", "zoe", "nora", "hannah", "lucy", "sarah", "anna",
    "liam", "noah", "oliver", "elijah", "james", "william", "benjamin", "lucas", "henry", "mason",
    "ethan", "daniel", "jacob", "logan", "jack", "owen", "samuel", "david", "leo", "ryan",
)
_LAST_NAMES = (
    "smith", "johnson", "brown", "miller", "davis", "wilson", "moore", "taylor", "anderson", "thomas",
    "martin", "lee", "walker", "hall", "allen", "young", "king", "wright", "scott", "green",
    "baker", "adams", "nelson", "carter", "mitchell", "roberts", "turner", "phillips", "parker", "evans",
    "collins", "stewart", "morris", "murphy", "cook", "rogers", "morgan", "cooper", "reed", "bailey",
)
_LOCAL_PART_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")


def random_local_part() -> str:
    return f"{secrets.choice(_FIRST_NAMES)}.{secrets.choice(_LAST_NAMES)}{secrets.randbelow(90) + 10}"


def validate_local_part(value: str) -> str:
    local = value.strip().lower()
    if not _LOCAL_PART_RE.fullmatch(local) or ".." in local:
        raise MailError("邮箱前缀只能用小写字母、数字和 . _ -，且不能以符号开头或结尾")
    return local


async def choose_domain(client: CloudMailClient, wanted: str | None) -> str:
    available = await client.domains()
    if not available:
        raise MailServerError("邮箱服务器上没有可用的域名")
    if wanted:
        domain = normalize_domain(wanted)
        if domain not in available:
            raise MailError(f"邮箱服务器没有域名 {domain}；可用的有：{'、'.join(available)}")
        return domain
    allowed = [d for d in client.config.domains if d in available] or available
    return secrets.choice(allowed)
