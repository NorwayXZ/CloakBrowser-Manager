"""Loopback HTTP proxy bridge for authenticated SOCKS5 upstreams.

Chromium accepts username/password authentication for HTTP proxies, but
Playwright rejects authenticated SOCKS5 proxy settings before Chromium starts.
The bridge keeps the upstream credentials in Manager and exposes only an
unauthenticated HTTP proxy on 127.0.0.1 to the browser process.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import ssl
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

logger = logging.getLogger("cloakbrowser.manager.proxy")

_MAX_HEADER_BYTES = 64 * 1024
_BUFFER_SIZE = 64 * 1024


class ProxyBridgeError(RuntimeError):
    """Raised when the local proxy bridge cannot connect upstream."""


def _split_host_port(value: str) -> tuple[str, int]:
    host, separator, port = value.rpartition(":")
    if not separator or not host or not port.isdigit():
        raise ProxyBridgeError(f"Invalid proxy target: {value}")
    return host.strip("[]"), int(port)


def _target_address(host: str) -> bytes:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        encoded = host.encode("idna")
        if len(encoded) > 255:
            raise ProxyBridgeError("Proxy target hostname is too long")
        return b"\x03" + bytes([len(encoded)]) + encoded
    if address.version == 4:
        return b"\x01" + address.packed
    return b"\x04" + address.packed


async def _read_headers(reader: asyncio.StreamReader) -> bytes:
    try:
        data = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
        raise ProxyBridgeError("Proxy connection closed before headers were complete") from exc
    if len(data) > _MAX_HEADER_BYTES:
        raise ProxyBridgeError("Proxy headers are too large")
    return data


def _request_parts(data: bytes) -> tuple[str, str, str, list[tuple[str, str]]]:
    try:
        text = data.decode("latin-1")
    except UnicodeDecodeError as exc:
        raise ProxyBridgeError("Proxy request is not valid HTTP") from exc

    lines = text[:-4].split("\r\n")
    if not lines:
        raise ProxyBridgeError("Proxy request is empty")
    request_line = lines[0].split(" ", 2)
    if len(request_line) != 3:
        raise ProxyBridgeError("Proxy request line is invalid")
    method, target, version = request_line
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line:
            continue
        name, separator, value = line.partition(":")
        if not separator:
            raise ProxyBridgeError("Proxy header is invalid")
        headers.append((name.strip(), value.strip()))
    return method, target, version, headers


def _header(headers: list[tuple[str, str]], name: str) -> str | None:
    needle = name.lower()
    for key, value in headers:
        if key.lower() == needle:
            return value
    return None


def _replace_request_target(
    method: str,
    target: str,
    version: str,
    headers: list[tuple[str, str]],
) -> bytes:
    lines = [f"{method} {target} {version}"]
    lines.extend(f"{key}: {value}" for key, value in headers)
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


async def _relay(
    left: asyncio.StreamReader,
    right: asyncio.StreamWriter,
) -> None:
    try:
        while data := await left.read(_BUFFER_SIZE):
            right.write(data)
            await right.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass


async def _tunnel(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
) -> None:
    tasks = {
        asyncio.create_task(_relay(client_reader, upstream_writer)),
        asyncio.create_task(_relay(upstream_reader, client_writer)),
    }
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@dataclass(frozen=True)
class _UpstreamProxy:
    scheme: str
    host: str
    port: int
    username: str | None
    password: str | None

    @classmethod
    def parse(cls, url: str) -> "_UpstreamProxy":
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https", "socks5"}:
            raise ProxyBridgeError(f"Unsupported upstream proxy scheme: {parsed.scheme}")
        if not parsed.hostname or not parsed.port:
            raise ProxyBridgeError("Upstream proxy must include host and port")
        return cls(
            scheme=parsed.scheme,
            host=parsed.hostname,
            port=parsed.port,
            username=unquote(parsed.username) if parsed.username else None,
            password=unquote(parsed.password) if parsed.password else None,
        )

    @property
    def has_auth(self) -> bool:
        return self.username is not None or self.password is not None

    @property
    def authorization(self) -> str | None:
        if not self.has_auth:
            return None
        raw = f"{self.username or ''}:{self.password or ''}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")


async def _open_tls_connection(
    host: str,
    port: int,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    context = ssl.create_default_context()
    return await asyncio.open_connection(host, port, ssl=context, server_hostname=host)


async def _open_socks5_connection(
    proxy: _UpstreamProxy,
    target_host: str,
    target_port: int,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection(proxy.host, proxy.port)
    try:
        methods = b"\x00"
        if proxy.has_auth:
            methods += b"\x02"
        writer.write(b"\x05" + bytes([len(methods)]) + methods)
        await writer.drain()
        greeting = await reader.readexactly(2)
        if greeting[0] != 5:
            raise ProxyBridgeError("Upstream SOCKS5 returned an invalid version")
        if greeting[1] == 0xFF:
            raise ProxyBridgeError("Upstream SOCKS5 rejected all authentication methods")
        if greeting[1] == 0x02:
            username = (proxy.username or "").encode("utf-8")
            password = (proxy.password or "").encode("utf-8")
            if len(username) > 255 or len(password) > 255:
                raise ProxyBridgeError("SOCKS5 credentials are too long")
            writer.write(
                b"\x01"
                + bytes([len(username)])
                + username
                + bytes([len(password)])
                + password
            )
            await writer.drain()
            auth_response = await reader.readexactly(2)
            if auth_response != b"\x01\x00":
                raise ProxyBridgeError("Upstream SOCKS5 authentication failed")
        elif greeting[1] != 0x00:
            raise ProxyBridgeError("Upstream SOCKS5 selected an unsupported method")

        writer.write(b"\x05\x01\x00" + _target_address(target_host) + target_port.to_bytes(2, "big"))
        await writer.drain()
        response = await reader.readexactly(4)
        if response[0] != 5 or response[1] != 0:
            raise ProxyBridgeError(f"Upstream SOCKS5 CONNECT failed with code {response[1]}")
        address_type = response[3]
        if address_type == 1:
            await reader.readexactly(4)
        elif address_type == 3:
            length = (await reader.readexactly(1))[0]
            await reader.readexactly(length)
        elif address_type == 4:
            await reader.readexactly(16)
        else:
            raise ProxyBridgeError("Upstream SOCKS5 returned an invalid address type")
        await reader.readexactly(2)
        return reader, writer
    except BaseException:
        writer.close()
        await writer.wait_closed()
        raise


class HttpProxyBridge:
    """Expose a loopback HTTP proxy backed by one authenticated upstream."""

    def __init__(self, upstream_url: str):
        self.upstream = _UpstreamProxy.parse(upstream_url)
        self._server: asyncio.AbstractServer | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self._tasks: set[asyncio.Task[object]] = set()

    @property
    def port(self) -> int:
        if not self._server or not self._server.sockets:
            raise ProxyBridgeError("Proxy bridge has not started")
        return int(self._server.sockets[0].getsockname()[1])

    @property
    def browser_proxy(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> str:
        self._server = await asyncio.start_server(self._handle_client, "127.0.0.1", 0)
        logger.info(
            "Started loopback proxy bridge on %s for %s://%s:%s",
            self.browser_proxy,
            self.upstream.scheme,
            self.upstream.host,
            self.upstream.port,
        )
        return self.browser_proxy

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        for writer in list(self._writers):
            writer.close()
        current = asyncio.current_task()
        tasks = [task for task in self._tasks if task is not current and not task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._writers.clear()
        self._tasks.clear()

    async def _handle_client(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        self._writers.add(client_writer)
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            request_data = await _read_headers(client_reader)
            method, target, version, headers = _request_parts(request_data)
            if method.upper() == "CONNECT":
                target_host, target_port = _split_host_port(target)
                upstream_reader, upstream_writer = await self._open_target(
                    target_host,
                    target_port,
                    connect_only=True,
                )
                client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await client_writer.drain()
                await _tunnel(
                    client_reader,
                    client_writer,
                    upstream_reader,
                    upstream_writer,
                )
                return

            target_url = urlparse(target)
            target_host = target_url.hostname or _header(headers, "Host")
            if not target_host:
                raise ProxyBridgeError("HTTP proxy request is missing a target host")
            target_port = target_url.port or (443 if target_url.scheme == "https" else 80)
            upstream_reader, upstream_writer = await self._open_target(
                target_host,
                target_port,
                connect_only=False,
            )
            if self.upstream.scheme == "socks5":
                path = target_url.path or "/"
                if target_url.query:
                    path += "?" + target_url.query
                target = path
                request_data = _replace_request_target(method, target, version, headers)
            elif self.upstream.authorization and not _header(headers, "Proxy-Authorization"):
                request_data = _replace_request_target(
                    method,
                    target,
                    version,
                    [("Proxy-Authorization", self.upstream.authorization), *headers],
                )
            upstream_writer.write(request_data)
            await upstream_writer.drain()
            await _tunnel(
                client_reader,
                client_writer,
                upstream_reader,
                upstream_writer,
            )
        except (OSError, ValueError, asyncio.IncompleteReadError, ProxyBridgeError) as exc:
            logger.debug("Proxy bridge request failed: %s", exc)
            if not client_writer.is_closing():
                client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                try:
                    await client_writer.drain()
                except OSError:
                    pass
        finally:
            if upstream_writer is not None:
                upstream_writer.close()
                try:
                    await upstream_writer.wait_closed()
                except OSError:
                    pass
            client_writer.close()
            try:
                await client_writer.wait_closed()
            except OSError:
                pass
            self._writers.discard(client_writer)
            if task is not None:
                self._tasks.discard(task)

    async def _open_target(
        self,
        target_host: str,
        target_port: int,
        *,
        connect_only: bool,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if self.upstream.scheme == "socks5":
            return await _open_socks5_connection(self.upstream, target_host, target_port)

        if self.upstream.scheme == "https":
            reader, writer = await _open_tls_connection(self.upstream.host, self.upstream.port)
        else:
            reader, writer = await asyncio.open_connection(self.upstream.host, self.upstream.port)

        if connect_only:
            connect_headers = [
                f"CONNECT {target_host}:{target_port} HTTP/1.1",
                f"Host: {target_host}:{target_port}",
            ]
            if self.upstream.authorization:
                connect_headers.append(f"Proxy-Authorization: {self.upstream.authorization}")
            writer.write(("\r\n".join(connect_headers) + "\r\n\r\n").encode("latin-1"))
            await writer.drain()
            response = await _read_headers(reader)
            status_line = response.split(b"\r\n", 1)[0].decode("latin-1")
            if len(status_line.split(" ", 2)) < 2 or not status_line.split(" ", 2)[1].startswith("2"):
                writer.close()
                await writer.wait_closed()
                raise ProxyBridgeError(f"Upstream HTTP CONNECT failed: {status_line}")
        return reader, writer
