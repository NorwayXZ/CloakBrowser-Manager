"""A few-second health check of a proxy, with a plain answer when it is down.

The geo lookup only learns that a proxy is broken after its requests time
out, and a SOCKS5 proxy whose own uplink is down accepts the connection and
then never answers CONNECT, so "检查代理" and launches used to wait 30 s or
more before saying anything. This probe walks the same path a browser takes
and stops at the first step that fails:

1. TCP connect to the proxy;
2. the proxy handshake (SOCKS5 greeting and login, or an HTTP CONNECT);
3. the proxy's connection to a public host;
4. a TLS handshake with that host through the tunnel — some proxies confirm
   CONNECT before dialling out, so only real bytes prove the exit works.

It is blocking code (run it in a thread) built on plain sockets, so it works
the same on the Python the desktop apps ship.
"""

from __future__ import annotations

import base64
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

PROBE_HOST = "ipinfo.io"
PROBE_PORT = 443
CONNECT_SECONDS = 4.0
STEP_SECONDS = 6.0

_SOCKS_REPLIES = {
    1: "代理服务器内部错误",
    2: "代理规则不允许这个连接",
    3: "代理那一端网络不可达",
    4: "代理那一端连不到目标主机",
    5: "目标拒绝了代理的连接",
    6: "代理那一端连接超时",
    7: "代理不支持这种连接",
    8: "代理不支持这种地址",
}


@dataclass
class ProbeResult:
    ok: bool
    message: str
    stage: str  # "connect" | "handshake" | "forward" | "tls" | "done" | "skipped"
    seconds: float


class _Failed(Exception):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


def _recv_exact(sock: socket.socket, size: int, stage: str, what: str) -> bytes:
    data = b""
    while len(data) < size:
        try:
            chunk = sock.recv(size - len(data))
        except socket.timeout as exc:
            raise _Failed(stage, what) from exc
        if not chunk:
            raise _Failed(stage, what)
        data += chunk
    return data


def _socks5(sock: socket.socket, username: str | None, password: str | None) -> None:
    methods = b"\x00\x02" if username else b"\x00"
    sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
    reply = _recv_exact(sock, 2, "handshake", "代理没有回应 SOCKS5 握手：它可能不是 SOCKS5 代理，或代理程序卡住了")
    if reply[0] != 5:
        raise _Failed("handshake", "这个端口不是 SOCKS5 代理（握手回应不对）")
    if reply[1] == 0xFF:
        raise _Failed("handshake", "代理要求账号密码，但没有填写，或不接受这种登录方式")
    if reply[1] == 0x02:
        if not username:
            raise _Failed("handshake", "代理要求账号密码，但没有填写")
        user = username.encode()
        pwd = (password or "").encode()
        sock.sendall(b"\x01" + bytes([len(user)]) + user + bytes([len(pwd)]) + pwd)
        auth = _recv_exact(sock, 2, "handshake", "代理没有回应登录请求")
        if auth[1] != 0:
            raise _Failed("handshake", "代理账号或密码错误")
    host = PROBE_HOST.encode()
    sock.sendall(b"\x05\x01\x00\x03" + bytes([len(host)]) + host + PROBE_PORT.to_bytes(2, "big"))
    head = _recv_exact(
        sock, 4, "forward",
        f"代理能连上，但 {STEP_SECONDS:.0f} 秒内没有转发请求：通常是代理那一端的出口断了",
    )
    if head[1] != 0:
        reason = _SOCKS_REPLIES.get(head[1], f"错误码 {head[1]}")
        raise _Failed("forward", f"代理拒绝转发：{reason}")
    address_size = {1: 4, 4: 16}.get(head[3])
    if address_size is None:
        address_size = _recv_exact(sock, 1, "forward", "代理的转发回应不完整")[0]
    _recv_exact(sock, address_size + 2, "forward", "代理的转发回应不完整")


def _http_connect(sock: socket.socket, username: str | None, password: str | None) -> None:
    request = f"CONNECT {PROBE_HOST}:{PROBE_PORT} HTTP/1.1\r\nHost: {PROBE_HOST}:{PROBE_PORT}\r\n"
    if username:
        token = base64.b64encode(f"{username}:{password or ''}".encode()).decode()
        request += f"Proxy-Authorization: Basic {token}\r\n"
    sock.sendall((request + "\r\n").encode())
    response = b""
    while b"\r\n\r\n" not in response:
        try:
            chunk = sock.recv(1024)
        except socket.timeout as exc:
            raise _Failed(
                "forward",
                f"代理能连上，但 {STEP_SECONDS:.0f} 秒内没有转发请求：通常是代理那一端的出口断了",
            ) from exc
        if not chunk:
            raise _Failed("handshake", "代理断开了连接：这个端口可能不是 HTTP 代理")
        response += chunk
        if len(response) > 16384:
            break
    status_line = response.split(b"\r\n", 1)[0].decode(errors="replace")
    parts = status_line.split()
    if len(parts) < 2 or not parts[0].startswith("HTTP/"):
        raise _Failed("handshake", "这个端口不是 HTTP 代理（回应格式不对）")
    code = parts[1]
    if code == "407":
        raise _Failed("handshake", "代理要求账号密码，或账号密码错误")
    if code != "200":
        raise _Failed("forward", f"代理拒绝转发（HTTP {code}）")


def probe_proxy(proxy: str) -> ProbeResult:
    """Check that ``proxy`` reaches the internet; say where it fails if not."""
    started = time.monotonic()

    def result(ok: bool, stage: str, message: str) -> ProbeResult:
        return ProbeResult(ok=ok, message=message, stage=stage, seconds=round(time.monotonic() - started, 2))

    parsed = urlparse(proxy)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"socks5", "socks5h", "http", "https"} or not parsed.hostname or not parsed.port:
        return result(True, "skipped", "这种代理类型不做快速体检")
    where = f"{parsed.hostname}:{parsed.port}"
    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    try:
        try:
            sock = socket.create_connection((parsed.hostname, parsed.port), timeout=CONNECT_SECONDS)
        except ConnectionRefusedError:
            raise _Failed("connect", f"代理 {where} 拒绝连接：端口没开，或代理程序没在运行")
        except socket.timeout:
            raise _Failed("connect", f"连不上代理 {where}（{CONNECT_SECONDS:.0f} 秒没有响应）：地址不通或被防火墙挡住")
        except OSError as exc:
            raise _Failed("connect", f"连不上代理 {where}：{exc.strerror or exc}")
        with sock:
            sock.settimeout(STEP_SECONDS)
            if scheme == "https":
                to_proxy = ssl.create_default_context()
                to_proxy.check_hostname = False
                to_proxy.verify_mode = ssl.CERT_NONE
                sock = to_proxy.wrap_socket(sock, server_hostname=parsed.hostname)
            if scheme.startswith("socks5"):
                _socks5(sock, username, password)
            else:
                _http_connect(sock, username, password)
            # Only reachability is in question: a finished handshake proves
            # bytes went out and came back. Certificates are not checked (the
            # desktop apps' Python may lack a CA bundle).
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            try:
                with context.wrap_socket(sock, server_hostname=PROBE_HOST) as tls:
                    tls.do_handshake()
            except (socket.timeout, TimeoutError) as exc:
                raise _Failed(
                    "tls",
                    f"代理转发了连接，但 {STEP_SECONDS:.0f} 秒内没有连通外网：代理的出口很可能断了",
                ) from exc
            except ConnectionResetError as exc:
                raise _Failed("tls", "代理转发了连接，但连接马上被断开（重置）：代理的出口有问题") from exc
            except (ssl.SSLError, OSError) as exc:
                raise _Failed("tls", f"代理转发了连接，但到外网的加密握手失败：{exc}") from exc
    except _Failed as failure:
        return result(False, failure.stage, failure.message)
    return result(True, "done", f"代理可用（{time.monotonic() - started:.1f} 秒）")
