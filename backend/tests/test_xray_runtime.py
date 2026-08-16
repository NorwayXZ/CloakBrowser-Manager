"""Tests for Xray share-link parsing and config generation."""

from __future__ import annotations

import base64
import json

import pytest

from backend.xray_runtime import (
    XrayProxyError,
    build_xray_config,
    is_xray_link,
    parse_xray_link,
)


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_is_xray_link():
    assert is_xray_link("ss://abc")
    assert is_xray_link("vless://uuid@example.com:443")
    assert is_xray_link("vmess://abc")
    assert is_xray_link("trojan://secret@example.com:443")
    assert not is_xray_link("socks5://127.0.0.1:1080")


def test_parse_vless_reality():
    parsed = parse_xray_link(
        "vless://11111111-1111-1111-1111-111111111111"
        "@example.com:443?security=reality&sni=example.com&fp=chrome"
        "&pbk=public-key&sid=short&type=tcp#TW"
    )

    assert parsed["protocol"] == "vless"
    outbound = parsed["outbound"]
    assert outbound["settings"]["vnext"][0]["port"] == 443
    assert outbound["streamSettings"]["security"] == "reality"
    assert outbound["streamSettings"]["realitySettings"]["publicKey"] == "public-key"
    assert outbound["streamSettings"]["realitySettings"]["shortId"] == "short"


def test_parse_trojan_websocket():
    parsed = parse_xray_link(
        "trojan://secret@example.com:443?security=tls&type=ws"
        "&path=%2Fedge&host=cdn.example.com#demo"
    )

    outbound = parsed["outbound"]
    assert outbound["settings"]["servers"][0]["password"] == "secret"
    assert outbound["streamSettings"]["wsSettings"]["path"] == "/edge"
    assert outbound["streamSettings"]["wsSettings"]["headers"]["Host"] == "cdn.example.com"


def test_parse_shadowsocks_full_base64():
    parsed = parse_xray_link(
        "ss://" + _b64("chacha20-ietf-poly1305:secret@example.com:8388") + "#demo"
    )

    server = parsed["outbound"]["settings"]["servers"][0]
    assert server == {
        "address": "example.com",
        "port": 8388,
        "method": "chacha20-ietf-poly1305",
        "password": "secret",
    }


def test_parse_shadowsocks_split_base64():
    parsed = parse_xray_link(
        "ss://" + _b64("chacha20-ietf-poly1305:secret") + "@example.com:8388"
    )
    assert parsed["outbound"]["settings"]["servers"][0]["port"] == 8388


def test_parse_vmess_json():
    link = "vmess://" + _b64(json.dumps({
        "ps": "demo",
        "add": "example.com",
        "port": "443",
        "id": "11111111-1111-1111-1111-111111111111",
        "aid": "0",
        "scy": "auto",
        "net": "ws",
        "host": "cdn.example.com",
        "path": "/ws",
        "tls": "tls",
    }))

    parsed = parse_xray_link(link)
    outbound = parsed["outbound"]
    assert outbound["protocol"] == "vmess"
    assert outbound["streamSettings"]["network"] == "ws"
    assert outbound["streamSettings"]["security"] == "tls"


def test_build_config_has_local_socks_inbound():
    config = build_xray_config(
        "vless://11111111-1111-1111-1111-111111111111@example.com:443",
        34567,
    )

    inbound = config["inbounds"][0]
    assert inbound["listen"] == "127.0.0.1"
    assert inbound["port"] == 34567
    assert inbound["protocol"] == "socks"
    assert config["outbounds"][0]["tag"] == "proxy"


@pytest.mark.parametrize("link", [
    "vless://example.com:443",
    "trojan://example.com:443",
    "ss://not-valid",
    "vmess://not-valid",
])
def test_invalid_xray_link_has_actionable_error(link: str):
    with pytest.raises(XrayProxyError):
        parse_xray_link(link)
