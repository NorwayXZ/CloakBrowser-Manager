"""Cookies pasted as JSON, Netscape cookies.txt or Name=Value."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from backend.cookie_formats import (
    CookieFormatError,
    cookie_editor_cookies,
    live_cookies_to_profile,
    merge_cookies,
    normalize_cookie_text,
    parse_cookie_text,
    to_cookie_editor_json,
    to_netscape,
)

NETSCAPE = (
    "# Netscape HTTP Cookie File\n"
    ".example.com\tTRUE\t/\tTRUE\t1893456000\tsid\tabc123\n"
    "#HttpOnly_shop.example.com\tFALSE\t/cart\tFALSE\t0\ttoken\txyz\n"
)


def test_json_list_and_wrapped_object_are_read():
    cookies = [{"name": "sid", "value": "1", "domain": ".example.com"}]
    assert parse_cookie_text(json.dumps(cookies)) == ("json", cookies)
    assert parse_cookie_text(json.dumps({"cookies": cookies}))[1] == cookies


def test_netscape_lines_become_cookie_objects():
    fmt, cookies = parse_cookie_text(NETSCAPE)

    assert fmt == "netscape"
    assert cookies == [
        {
            "name": "sid", "value": "abc123", "domain": ".example.com", "path": "/",
            "secure": True, "httpOnly": False, "hostOnly": False, "expirationDate": 1893456000,
        },
        {
            "name": "token", "value": "xyz", "domain": "shop.example.com", "path": "/cart",
            "secure": False, "httpOnly": True, "hostOnly": True,
        },
    ]


def test_name_value_header_needs_a_domain():
    with pytest.raises(CookieFormatError, match="域名"):
        parse_cookie_text("sid=abc; theme=dark")

    fmt, cookies = parse_cookie_text("Cookie: sid=abc; theme=dark", "https://www.example.com/login")
    assert fmt == "header"
    assert cookies == [
        {"name": "sid", "value": "abc", "domain": ".www.example.com", "path": "/"},
        {"name": "theme", "value": "dark", "domain": ".www.example.com", "path": "/"},
    ]


def test_broken_json_reports_where():
    with pytest.raises(CookieFormatError, match="JSON 格式不对"):
        parse_cookie_text('[{"name": "sid",')


def test_unknown_text_is_rejected():
    with pytest.raises(CookieFormatError, match="认不出"):
        parse_cookie_text("just some words")


def test_merge_replaces_cookies_with_the_same_domain_path_and_name():
    existing = [
        {"name": "sid", "value": "old", "domain": ".example.com", "path": "/"},
        {"name": "keep", "value": "1", "domain": ".example.com", "path": "/"},
    ]
    incoming = [
        {"name": "sid", "value": "new", "domain": ".EXAMPLE.com", "path": "/"},
        {"name": "sid", "value": "other", "domain": ".example.com", "path": "/app"},
    ]

    merged = merge_cookies(existing, incoming)

    assert [(c["name"], c["value"], c["path"]) for c in merged] == [
        ("sid", "new", "/"), ("keep", "1", "/"), ("sid", "other", "/app"),
    ]


def test_normalize_keeps_json_as_written_and_converts_netscape():
    raw = '[{"name":"sid","value":"1","domain":".example.com","sameSite":"lax"}]'
    assert normalize_cookie_text(raw) == raw
    assert normalize_cookie_text("  ") is None
    assert json.loads(normalize_cookie_text(NETSCAPE))[0]["name"] == "sid"


# ── API ──────────────────────────────────────────────────────────────────────


def test_profile_save_converts_netscape_cookies(app_client: TestClient):
    resp = app_client.post("/api/profiles", json={"name": "Netscape", "cookies_json": NETSCAPE})

    assert resp.status_code == 201
    stored = json.loads(resp.json()["cookies_json"])
    assert [c["name"] for c in stored] == ["sid", "token"]


def test_profile_save_explains_a_header_without_domain(app_client: TestClient):
    resp = app_client.post("/api/profiles", json={"name": "Header", "cookies_json": "sid=abc"})

    assert resp.status_code == 422
    assert "域名" in resp.json()["detail"]


def test_merge_endpoint_adds_to_existing_cookies(app_client: TestClient):
    existing = json.dumps([{"name": "sid", "value": "old", "domain": ".example.com", "path": "/"}])

    resp = app_client.post("/api/cookies/merge", json={
        "text": "sid=new; lang=zh", "domain": "example.com", "existing": existing,
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "header"
    assert body["added"] == 2
    assert body["total"] == 2
    assert {c["name"]: c["value"] for c in json.loads(body["cookies_json"])} == {"sid": "new", "lang": "zh"}


def test_merge_endpoint_rejects_empty_text(app_client: TestClient):
    resp = app_client.post("/api/cookies/merge", json={"text": "   "})
    assert resp.status_code == 422


# --- Reading cookies back from a live browser, and exporting them ----------

LIVE_COOKIES = [
    {
        "name": "sid", "value": "abc123", "domain": ".example.com", "path": "/",
        "expires": 1893456000.0, "httpOnly": True, "secure": True, "sameSite": "Lax",
    },
    {
        "name": "pref", "value": "zh", "domain": "shop.example.com", "path": "/cart",
        "expires": -1, "httpOnly": False, "secure": False, "sameSite": "None",
    },
]


def test_live_cookies_become_the_stored_shape():
    cookies = live_cookies_to_profile(LIVE_COOKIES)

    assert cookies[0] == {
        "name": "sid", "value": "abc123", "domain": ".example.com", "path": "/",
        "secure": True, "httpOnly": True, "hostOnly": False,
        "sameSite": "lax", "expirationDate": 1893456000,
    }
    # A session cookie (expires -1) carries the flag instead of a date.
    assert cookies[1]["session"] is True
    assert "expirationDate" not in cookies[1]
    assert cookies[1]["hostOnly"] is True
    assert cookies[1]["sameSite"] == "none"


def test_live_cookies_skip_malformed_entries():
    raw = [
        {"name": "ok", "value": "1", "domain": "example.com"},
        {"name": "", "value": "1", "domain": "example.com"},
        {"value": "1", "domain": "example.com"},
        "not-a-dict",
    ]
    assert [c["name"] for c in live_cookies_to_profile(raw)] == ["ok"]


def test_cookie_editor_export_fields():
    exported = cookie_editor_cookies(live_cookies_to_profile(LIVE_COOKIES))

    persistent, session = exported
    assert persistent["expirationDate"] == 1893456000
    assert persistent["session"] is False
    assert persistent["httpOnly"] is True and persistent["secure"] is True
    assert persistent["sameSite"] == "lax"
    # Session cookies omit the date and map SameSite=None to Cookie-Editor's
    # "no_restriction" spelling.
    assert "expirationDate" not in session
    assert session["session"] is True
    assert session["sameSite"] == "no_restriction"

    parsed = json.loads(to_cookie_editor_json(live_cookies_to_profile(LIVE_COOKIES)))
    assert [c["name"] for c in parsed] == ["sid", "pref"]


def test_netscape_export_parses_back_to_the_same_cookies():
    profile_cookies = live_cookies_to_profile(LIVE_COOKIES)
    document = to_netscape(profile_cookies)

    lines = [
        line for line in document.splitlines()
        if line and (not line.startswith("#") or line.startswith("#HttpOnly_"))
    ]
    assert lines[0].startswith("#HttpOnly_.example.com\tTRUE\t/\tTRUE\t1893456000\tsid\tabc123")
    assert lines[1] == "shop.example.com\tFALSE\t/cart\tFALSE\t0\tpref\tzh"

    fmt, parsed = parse_cookie_text(document)
    assert fmt == "netscape"

    def key(cookie):
        return (
            cookie["domain"], cookie["path"], cookie["name"], cookie["value"],
            cookie["secure"], cookie["httpOnly"], cookie.get("expirationDate"),
        )

    assert sorted(map(key, parsed)) == sorted(map(key, profile_cookies))
