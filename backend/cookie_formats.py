"""Read cookies pasted as JSON, Netscape cookies.txt or a Name=Value header.

Profiles keep cookies as a JSON list; everything pasted into the panel is
converted to that shape first, and merges replace cookies that share
domain, path and name.
"""

from __future__ import annotations

import json
from typing import Any

NETSCAPE_HTTPONLY_PREFIX = "#HttpOnly_"


class CookieFormatError(ValueError):
    """Pasted text is not a cookie list the panel can read."""


def _clean_domain(domain: str) -> str:
    domain = domain.strip()
    if "://" in domain:
        domain = domain.split("://", 1)[1]
    return domain.split("/", 1)[0].split(":", 1)[0].strip()


def _from_json(text: str) -> list[dict[str, Any]]:
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("cookies", [data] if "name" in data else [])
    if not isinstance(data, list):
        raise CookieFormatError("JSON 里没有 Cookie 列表")
    cookies = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name, value, domain = item.get("name"), item.get("value"), item.get("domain")
        if not isinstance(name, str) or not name or not isinstance(value, str) or not isinstance(domain, str) or not domain:
            continue
        cookies.append(dict(item))
    return cookies


def _looks_like_netscape(lines: list[str]) -> bool:
    data_lines = [
        line for line in lines
        if line.strip() and (not line.startswith("#") or line.startswith(NETSCAPE_HTTPONLY_PREFIX))
    ]
    return bool(data_lines) and all(len(line.split("\t")) >= 7 for line in data_lines)


def _from_netscape(lines: list[str]) -> list[dict[str, Any]]:
    cookies = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        http_only = line.startswith(NETSCAPE_HTTPONLY_PREFIX)
        if http_only:
            line = line[len(NETSCAPE_HTTPONLY_PREFIX):]
        elif not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        domain, include_subdomains, path, secure, expires, name, value = fields[:7]
        if not domain or not name:
            continue
        cookie: dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path or "/",
            "secure": secure.upper() == "TRUE",
            "httpOnly": http_only,
            "hostOnly": include_subdomains.upper() != "TRUE" and not domain.startswith("."),
        }
        try:
            expiry = int(float(expires))
        except ValueError:
            expiry = 0
        if expiry > 0:
            cookie["expirationDate"] = expiry
        cookies.append(cookie)
    return cookies


def _from_header(text: str, domain: str | None) -> list[dict[str, Any]]:
    host = _clean_domain(domain or "")
    if not host:
        raise CookieFormatError("Name=Value 格式不带域名，请先填写这些 Cookie 属于哪个网站，例如 example.com")
    header = text.strip()
    if header.lower().startswith("cookie:"):
        header = header[len("cookie:"):]
    cookies = []
    for part in header.replace("\n", ";").split(";"):
        name, sep, value = part.strip().partition("=")
        if not sep or not name.strip():
            continue
        cookies.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": "." + host.lstrip("."),
            "path": "/",
        })
    return cookies


def parse_cookie_text(text: str | None, domain: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Detect the format and return (format, cookies)."""
    content = (text or "").strip()
    if not content:
        return "empty", []
    if content[0] in "[{":
        try:
            return "json", _from_json(content)
        except json.JSONDecodeError as exc:
            raise CookieFormatError(f"JSON 格式不对：{exc.msg}（第 {exc.lineno} 行）") from exc
    lines = content.splitlines()
    if _looks_like_netscape(lines):
        return "netscape", _from_netscape(lines)
    if "=" in content:
        return "header", _from_header(content, domain)
    raise CookieFormatError("认不出 Cookie 格式：支持 JSON、Netscape（cookies.txt）和 Name=Value")


def _cookie_key(cookie: dict[str, Any]) -> tuple[str, str, str]:
    return (str(cookie.get("domain") or "").lower(), str(cookie.get("path") or "/"), str(cookie.get("name")))


def merge_cookies(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Existing cookies plus incoming ones; an incoming cookie replaces its twin."""
    merged = {_cookie_key(cookie): cookie for cookie in existing}
    for cookie in incoming:
        merged[_cookie_key(cookie)] = cookie
    return list(merged.values())


def normalize_cookie_text(text: str | None, domain: str | None = None) -> str | None:
    """Stored form of pasted cookies: a JSON list, or None when empty."""
    fmt, cookies = parse_cookie_text(text, domain)
    if fmt == "empty":
        return None
    if fmt == "json":
        # Keep the user's JSON as written so nothing they set is reformatted away.
        return (text or "").strip()
    if not cookies:
        raise CookieFormatError("没有读到任何 Cookie")
    return json.dumps(cookies, ensure_ascii=False, indent=2)


# --- Cookies read back from a live browser, and export serializers ---------
#
# A cookie pulled from a running browser starts out in Playwright's shape
# (``expires`` as unix seconds, -1 for session cookies; capitalised
# ``sameSite``). Everything is normalised to the stored profile shape first
# (Cookie-Editor style ``expirationDate`` / ``session``), so the pull result
# can be saved as ``cookies_json`` as-is and the exporters share one input.

_LIVE_SAMESITE = {"strict": "strict", "lax": "lax", "none": "none"}
_EDITOR_SAMESITE = {
    "strict": "strict",
    "lax": "lax",
    "none": "no_restriction",
    "no_restriction": "no_restriction",
}


def _valid_cookie(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    name, value, domain = item.get("name"), item.get("value"), item.get("domain")
    if not isinstance(name, str) or not name or not isinstance(value, str) or not isinstance(domain, str) or not domain:
        return None
    return item


def _expiry_of(item: dict[str, Any]) -> int | None:
    """Positive unix expiry from a stored-shape cookie, else None (session)."""
    if item.get("session"):
        return None
    expiry = item.get("expirationDate", item.get("expires"))
    if isinstance(expiry, (int, float)) and expiry > 0:
        return int(expiry)
    return None


def live_cookies_to_profile(raw_cookies: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Playwright ``BrowserContext.cookies()`` output in the stored shape."""
    cookies: list[dict[str, Any]] = []
    for item in raw_cookies or []:
        if _valid_cookie(item) is None:
            continue
        domain = str(item["domain"])
        cookie: dict[str, Any] = {
            "name": item["name"],
            "value": item["value"],
            "domain": domain,
            "path": str(item.get("path") or "/"),
            "secure": bool(item.get("secure", False)),
            "httpOnly": bool(item.get("httpOnly", False)),
            "hostOnly": not domain.startswith("."),
        }
        same_site = str(item.get("sameSite") or "").strip().lower()
        if same_site in _LIVE_SAMESITE:
            cookie["sameSite"] = same_site
        expires = item.get("expires")
        if isinstance(expires, (int, float)) and expires > 0:
            cookie["expirationDate"] = int(expires)
        else:
            cookie["session"] = True
        cookies.append(cookie)
    return cookies


def cookie_editor_cookies(cookies: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Stored-shape cookies as the array the Cookie-Editor extension imports."""
    exported: list[dict[str, Any]] = []
    for raw in cookies or []:
        item = _valid_cookie(raw)
        if item is None:
            continue
        domain = str(item["domain"])
        expiry = _expiry_of(item)
        entry: dict[str, Any] = {
            "name": item["name"],
            "value": item["value"],
            "domain": domain,
            "path": str(item.get("path") or "/"),
        }
        if expiry is not None:
            entry["expirationDate"] = expiry
        entry["httpOnly"] = bool(item.get("httpOnly", False))
        entry["secure"] = bool(item.get("secure", False))
        entry["hostOnly"] = bool(item.get("hostOnly", not domain.startswith(".")))
        same_site = str(item.get("sameSite") or "").strip().lower()
        entry["sameSite"] = _EDITOR_SAMESITE.get(same_site, "unspecified")
        entry["session"] = expiry is None
        exported.append(entry)
    return exported


def to_cookie_editor_json(cookies: list[dict[str, Any]] | None) -> str:
    """Export document Cookie-Editor can import directly."""
    return json.dumps(cookie_editor_cookies(cookies), ensure_ascii=False, indent=2)


def _netscape_field(value: Any) -> str:
    # The tab-separated format cannot carry tabs or line breaks in values.
    return str(value or "").replace("\t", " ").replace("\r", "").replace("\n", "")


def to_netscape(cookies: list[dict[str, Any]] | None) -> str:
    """Stored-shape cookies as a Netscape cookies.txt document."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# Exported by CloakBrowser Manager",
        "",
    ]
    for raw in cookies or []:
        item = _valid_cookie(raw)
        if item is None:
            continue
        domain = str(item["domain"])
        line = "\t".join([
            _netscape_field(domain),
            "TRUE" if domain.startswith(".") else "FALSE",
            _netscape_field(item.get("path") or "/"),
            "TRUE" if item.get("secure") else "FALSE",
            str(_expiry_of(item) or 0),
            _netscape_field(item["name"]),
            _netscape_field(item["value"]),
        ])
        if item.get("httpOnly"):
            line = NETSCAPE_HTTPONLY_PREFIX + line
        lines.append(line)
    return "\n".join(lines) + "\n"
