"""Tests for authenticated SOCKS5 to loopback HTTP proxy bridging."""

from __future__ import annotations

import asyncio

import pytest

from backend.proxy_bridge import HttpProxyBridge, Socks5ProxySwitch


async def _echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def _authenticated_socks5(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    target_port: int,
) -> None:
    try:
        greeting = await reader.readexactly(4)
        assert greeting[:3] == b"\x05\x02\x00"
        assert greeting[3] == 2
        writer.write(b"\x05\x02")
        await writer.drain()

        auth_header = await reader.readexactly(2)
        assert auth_header == b"\x01\x04"
        assert await reader.readexactly(4) == b"user"
        assert await reader.readexactly(1) == b"\x04"
        assert await reader.readexactly(4) == b"pass"
        writer.write(b"\x01\x00")
        await writer.drain()

        request = await reader.readexactly(4)
        assert request == b"\x05\x01\x00\x01"
        target_host = await reader.readexactly(4)
        assert target_host == b"\x7f\x00\x00\x01"
        requested_port = int.from_bytes(await reader.readexactly(2), "big")
        assert requested_port == target_port

        target_reader, target_writer = await asyncio.open_connection("127.0.0.1", target_port)
        writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
        await writer.drain()
        tasks = {
            asyncio.create_task(_pipe(reader, target_writer)),
            asyncio.create_task(_pipe(target_reader, writer)),
        }
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        target_writer.close()
        await target_writer.wait_closed()
    finally:
        writer.close()
        await writer.wait_closed()


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass


@pytest.mark.asyncio
async def test_authenticated_socks5_bridge_forwards_connect() -> None:
    echo_server = await asyncio.start_server(_echo, "127.0.0.1", 0)
    echo_port = int(echo_server.sockets[0].getsockname()[1])
    socks_server = await asyncio.start_server(
        lambda reader, writer: _authenticated_socks5(reader, writer, echo_port),
        "127.0.0.1",
        0,
    )
    socks_port = int(socks_server.sockets[0].getsockname()[1])
    bridge = HttpProxyBridge(f"socks5://user:pass@127.0.0.1:{socks_port}")

    try:
        await bridge.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", bridge.port)
        # The browser embeds the one-time bridge token as the HTTP-proxy
        # username, which Chromium presents as Proxy-Authorization.
        import base64 as _base64

        token_auth = "Basic " + _base64.b64encode(f"{bridge._token}:".encode()).decode()
        writer.write(
            f"CONNECT 127.0.0.1:{echo_port} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{echo_port}\r\n"
            f"Proxy-Authorization: {token_auth}\r\n\r\n".encode("ascii")
        )
        await writer.drain()
        response = await reader.readuntil(b"\r\n\r\n")
        assert response.startswith(b"HTTP/1.1 200")

        writer.write(b"bridge-ok")
        await writer.drain()
        assert await reader.readexactly(len(b"bridge-ok")) == b"bridge-ok"
        writer.close()
        await writer.wait_closed()
    finally:
        await bridge.close()
        socks_server.close()
        await socks_server.wait_closed()
        echo_server.close()
        await echo_server.wait_closed()


async def _tagged_socks5_upstream(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    region_tag: bytes,
    expected_auth: tuple[bytes, bytes] | None = None,
) -> None:
    """Mock SOCKS5 server that answers any domain CONNECT with its region tag and echoes."""
    try:
        ver_nm = await reader.readexactly(2)
        assert ver_nm[0] == 0x05
        methods = await reader.readexactly(ver_nm[1])
        if expected_auth is not None:
            assert 0x02 in methods
            writer.write(b"\x05\x02")
            await writer.drain()
            ver_u = await reader.readexactly(2)
            assert ver_u[0] == 0x01
            uname = await reader.readexactly(ver_u[1])
            plen = (await reader.readexactly(1))[0]
            passwd = await reader.readexactly(plen)
            assert (uname, passwd) == expected_auth
            writer.write(b"\x01\x00")
            await writer.drain()
        else:
            assert 0x00 in methods
            writer.write(b"\x05\x00")
            await writer.drain()

        req = await reader.readexactly(4)
        assert req[:3] == b"\x05\x01\x00"
        atyp = req[3]
        if atyp == 0x03:
            dlen = (await reader.readexactly(1))[0]
            _domain = await reader.readexactly(dlen)
        elif atyp == 0x01:
            await reader.readexactly(4)
        else:
            await reader.readexactly(16)
        await reader.readexactly(2)

        writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
        await writer.drain()

        while data := await reader.read(4096):
            writer.write(region_tag + b":" + data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def _socks5_connect_domain(port: int, host: str, target_port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"\x05\x01\x00")
    await writer.drain()
    assert await reader.readexactly(2) == b"\x05\x00"
    host_bytes = host.encode("idna")
    writer.write(
        b"\x05\x01\x00\x03"
        + bytes([len(host_bytes)])
        + host_bytes
        + target_port.to_bytes(2, "big")
    )
    await writer.drain()
    reply = await reader.readexactly(10)
    assert reply[:2] == b"\x05\x00"
    return reader, writer


@pytest.mark.asyncio
async def test_socks5_proxy_switch_hot_swaps_upstream_and_drops_keepalive() -> None:
    hk_server = await asyncio.start_server(
        lambda r, w: _tagged_socks5_upstream(r, w, region_tag=b"HK", expected_auth=(b"hkuser", b"hkpass")),
        "127.0.0.1",
        0,
    )
    sg_server = await asyncio.start_server(
        lambda r, w: _tagged_socks5_upstream(r, w, region_tag=b"SG", expected_auth=(b"sguser", b"sgpass")),
        "127.0.0.1",
        0,
    )
    echo_server = await asyncio.start_server(_echo, "127.0.0.1", 0)
    hk_port = int(hk_server.sockets[0].getsockname()[1])
    sg_port = int(sg_server.sockets[0].getsockname()[1])
    echo_port = int(echo_server.sockets[0].getsockname()[1])

    switch = Socks5ProxySwitch(f"socks5://hkuser:hkpass@127.0.0.1:{hk_port}")
    try:
        browser_proxy = await switch.start()
        assert browser_proxy == f"socks5://127.0.0.1:{switch.port}"

        # 1. Initial browser connection exits via Hong Kong SOCKS5 and stays pooled (keep-alive)
        r1, w1 = await _socks5_connect_domain(switch.port, "checkip.example.test", 443)
        w1.write(b"refresh-1")
        await w1.drain()
        assert await r1.readexactly(len(b"HK:refresh-1")) == b"HK:refresh-1"

        # 2. Live switch to Singapore SOCKS5 WITHOUT restarting switch/browser
        switch.switch_upstream(f"socks5://sguser:sgpass@127.0.0.1:{sg_port}")

        # Pooled keep-alive tunnel to HK is dropped immediately so refresh reconnects
        assert await asyncio.wait_for(r1.read(64), timeout=2.0) == b""
        w1.close()

        # 3. Browser refresh on the SAME local port now exits via Singapore SOCKS5
        r2, w2 = await _socks5_connect_domain(switch.port, "checkip.example.test", 443)
        w2.write(b"refresh-2")
        await w2.drain()
        assert await r2.readexactly(len(b"SG:refresh-2")) == b"SG:refresh-2"
        w2.close()

        # 4. Switching to None routes directly
        switch.switch_upstream(None)
        r3, w3 = await _socks5_connect_domain(switch.port, "127.0.0.1", echo_port)
        w3.write(b"direct-ok")
        await w3.drain()
        assert await r3.readexactly(len(b"direct-ok")) == b"direct-ok"
        w3.close()
    finally:
        await switch.close()
        hk_server.close()
        sg_server.close()
        echo_server.close()
        await hk_server.wait_closed()
        await sg_server.wait_closed()
        await echo_server.wait_closed()


@pytest.mark.asyncio
async def test_switch_profile_proxy_api_hot_swaps_running_browser_and_keeps_old_on_dead_proxy(
    tmp_db, monkeypatch
) -> None:
    import httpx
    from unittest.mock import AsyncMock
    from backend import database as db
    from backend import main
    from backend.browser_manager import RunningProfile
    from backend.proxy_probe import ProbeResult

    hk_proxy = "socks5://hk:pass@198.51.100.10:1080"
    sg_proxy = "socks5://sg:pass@203.0.113.88:1080"
    dead_proxy = "socks5://dead:pass@192.0.2.99:1080"

    created = db.create_profile(name="Live Swap Profile", proxy=hk_proxy)
    pid = created["id"]

    switch = Socks5ProxySwitch(hk_proxy)
    await switch.start()

    def fake_probe(proxy_url: str) -> ProbeResult:
        if "192.0.2.99" in proxy_url:
            return ProbeResult(ok=False, stage="connect", message="连接超时", seconds=0.05)
        return ProbeResult(ok=True, stage="done", message="ok", seconds=0.02)

    monkeypatch.setattr("backend.browser_manager.probe_proxy", fake_probe)
    monkeypatch.setattr(
        "backend.browser_manager.fetch_proxy_geo",
        AsyncMock(return_value={"ip": "203.0.113.88", "country": "Singapore", "country_code": "SG", "timezone": "Asia/Singapore"}),
    )

    running = RunningProfile(
        profile_id=pid,
        context=None,
        cdp_port=None,
        display=None,
        ws_port=None,
        browser_engine="cloakbrowser",
        launch_mode="manual",
        proxy_switch=switch,
        proxy_geo={"ip": "198.51.100.10", "country": "Hong Kong", "country_code": "HK", "connection_mode": "proxy"},
    )
    main.browser_mgr.running[pid] = running
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://127.0.0.1:8080",
        ) as client:
            # Dead proxy fails with 400 and preserves both the live tunnel and stored profile
            bad_res = await client.post(f"/api/profiles/{pid}/switch-proxy", json={"proxy": dead_proxy})
            assert bad_res.status_code == 400
            assert switch.upstream_url == hk_proxy
            assert db.get_profile(pid)["proxy"] == hk_proxy

            # Reachable Singapore proxy hot-swaps live without closing the browser
            ok_res = await client.post(f"/api/profiles/{pid}/switch-proxy", json={"proxy": sg_proxy})
            assert ok_res.status_code == 200
            body = ok_res.json()
            assert body["applied_live"] is True
            assert body["requires_restart"] is False
            assert body["proxy_geo"]["country_code"] == "SG"
            assert body["profile"]["proxy"] == sg_proxy
            assert body["profile"]["proxy_geo"]["ip"] == "203.0.113.88"
            assert switch.upstream_url == sg_proxy
    finally:
        main.browser_mgr.running.pop(pid, None)
        await switch.close()
