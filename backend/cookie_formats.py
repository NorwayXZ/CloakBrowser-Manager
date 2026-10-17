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
