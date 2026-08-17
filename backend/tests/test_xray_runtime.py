"""Tests for Xray share-link parsing and config generation."""

from __future__ import annotations

import base64
import json

import pytest

from backend import xray_runtime
from backend.xray_runtime import (
    XrayProxyError,
    build_xray_config,
    ensure_xray_runtime,
    is_xray_link,
    find_xray_data_dir,
    _binary_name,
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


def test_find_xray_data_dir_requires_both_dat_files(tmp_path):
    binary_dir = tmp_path / "bundle"
    binary_dir.mkdir()
    binary = binary_dir / _binary_name()
    binary.write_text("xray")

    assert find_xray_data_dir(binary, tmp_path) is None

    (binary_dir / "geoip.dat").write_bytes(b"geoip")
    assert find_xray_data_dir(binary, tmp_path) is None

    (binary_dir / "geosite.dat").write_bytes(b"geosite")
    assert find_xray_data_dir(binary, tmp_path) == binary_dir


@pytest.mark.asyncio
async def test_ensure_xray_runtime_reuses_existing_bundle_with_data(tmp_path):
    xray_dir = tmp_path / "xray"
    xray_dir.mkdir()
    binary = xray_dir / _binary_name()
    binary.write_text("xray")
    (xray_dir / "geoip.dat").write_bytes(b"geoip")
    (xray_dir / "geosite.dat").write_bytes(b"geosite")

    result_binary, result_assets = await ensure_xray_runtime(tmp_path)

    assert result_binary == binary
    assert result_assets == xray_dir


@pytest.mark.asyncio
async def test_start_xray_proxy_sets_working_directory_and_asset_env(tmp_path, monkeypatch):
    xray_dir = tmp_path / "xray"
    xray_dir.mkdir()
    binary = xray_dir / _binary_name()
    binary.write_text("xray")
    (xray_dir / "geoip.dat").write_bytes(b"geoip")
    (xray_dir / "geosite.dat").write_bytes(b"geosite")

    async def fake_ensure_xray_runtime(data_dir):
        return binary, xray_dir

    class DummyProcess:
        def __init__(self):
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = 0

        async def wait(self):
            self.returncode = 0
            return 0

    recorded: dict[str, object] = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        recorded["args"] = args
        recorded["kwargs"] = kwargs
        return DummyProcess()

    async def fake_wait_for_xray(process, port):
        return None

    monkeypatch.setattr(xray_runtime, "ensure_xray_runtime", fake_ensure_xray_runtime)
    monkeypatch.setattr(xray_runtime.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(xray_runtime, "_wait_for_xray", fake_wait_for_xray)
    monkeypatch.setattr(xray_runtime, "_free_port", lambda: 34567)

    process = await xray_runtime.start_xray_proxy(
        "vless://11111111-1111-1111-1111-111111111111@example.com:443",
        user_data_dir=tmp_path / "profile",
        data_dir=tmp_path,
    )

    assert recorded["kwargs"]["cwd"] == str(xray_dir)
    assert recorded["kwargs"]["env"]["XRAY_LOCATION_ASSET"] == str(xray_dir)
    await process.close()


@pytest.mark.parametrize("link", [
    "vless://example.com:443",
    "trojan://example.com:443",
    "ss://not-valid",
    "vmess://not-valid",
])
def test_invalid_xray_link_has_actionable_error(link: str):
    with pytest.raises(XrayProxyError):
        parse_xray_link(link)
