"""Tests for authenticated SOCKS5 to loopback HTTP proxy bridging."""

from __future__ import annotations

import asyncio

import pytest

from backend.proxy_bridge import HttpProxyBridge


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
        writer.write(
            f"CONNECT 127.0.0.1:{echo_port} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{echo_port}\r\n\r\n".encode("ascii")
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
