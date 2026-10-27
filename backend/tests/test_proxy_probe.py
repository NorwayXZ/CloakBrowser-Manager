"""The few-second proxy health check, against local fake proxies."""

from __future__ import annotations

import datetime
import socket
import ssl
import threading
from pathlib import Path

import pytest

from backend import proxy_probe
from backend.proxy_probe import probe_proxy


@pytest.fixture(autouse=True)
def quick_steps(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(proxy_probe, "STEP_SECONDS", 0.5)
    monkeypatch.setattr(proxy_probe, "CONNECT_SECONDS", 0.5)


def _serve(handler) -> int:
    """A one-connection-at-a-time fake proxy on a free port."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(4)

    def loop():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=handler, args=(conn,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return server.getsockname()[1]


def _read_socks_connect(conn: socket.socket) -> None:
    head = conn.recv(5)  # VER CMD RSV ATYP LEN (domain)
    conn.recv(head[4] + 2)


def _tls_server(tmp_path: Path) -> ssl.SSLContext:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ipinfo.io")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context


def test_a_closed_port_fails_at_once(monkeypatch):
    # Windows retries a refused connection for about 2 s before reporting it,
    # so this test keeps the real connect timeout, not the quick one.
    monkeypatch.setattr(proxy_probe, "CONNECT_SECONDS", 4.0)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    result = probe_proxy(f"socks5://127.0.0.1:{port}")

    assert (result.ok, result.stage) == (False, "connect")
    assert "拒绝连接" in result.message


def test_a_proxy_that_never_forwards_is_reported_quickly():
    def handler(conn):
        conn.recv(3)
        conn.sendall(b"\x05\x00")
        _read_socks_connect(conn)
        threading.Event().wait(5)  # never answers CONNECT

    result = probe_proxy(f"socks5://127.0.0.1:{_serve(handler)}")

    assert (result.ok, result.stage) == (False, "forward")
    assert "没有转发" in result.message
    assert result.seconds < 2


def test_a_wrong_password_is_named():
    def handler(conn):
        conn.recv(4)
        conn.sendall(b"\x05\x02")
        conn.recv(64)
        conn.sendall(b"\x01\x01")

    result = probe_proxy(f"socks5://user:bad@127.0.0.1:{_serve(handler)}")

    assert (result.ok, result.stage) == (False, "handshake")
    assert "账号或密码错误" in result.message


def test_a_refused_forward_gives_the_reason():
    def handler(conn):
        conn.recv(3)
        conn.sendall(b"\x05\x00")
        _read_socks_connect(conn)
        conn.sendall(b"\x05\x05\x00\x01" + b"\x00" * 6)

    result = probe_proxy(f"socks5://127.0.0.1:{_serve(handler)}")

    assert (result.ok, result.stage) == (False, "forward")
    assert "拒绝转发" in result.message


def test_a_forward_that_goes_nowhere_fails_the_tls_step():
    def handler(conn):
        conn.recv(3)
        conn.sendall(b"\x05\x00")
        _read_socks_connect(conn)
        conn.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)
        threading.Event().wait(5)  # said yes, but no bytes ever come back

    result = probe_proxy(f"socks5://127.0.0.1:{_serve(handler)}")

    assert (result.ok, result.stage) == (False, "tls")
    assert "没有连通外网" in result.message


def test_a_working_socks5_proxy_passes(tmp_path: Path):
    tls = _tls_server(tmp_path)

    def handler(conn):
        conn.recv(3)
        conn.sendall(b"\x05\x00")
        _read_socks_connect(conn)
        conn.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)
        with tls.wrap_socket(conn, server_side=True) as wrapped:
            wrapped.recv(1)

    result = probe_proxy(f"socks5://127.0.0.1:{_serve(handler)}")

    assert (result.ok, result.stage) == (True, "done")


def test_http_proxy_auth_failure_and_success(tmp_path: Path):
    tls = _tls_server(tmp_path)

    def needs_auth(conn):
        conn.recv(1024)
        conn.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")

    def works(conn):
        request = conn.recv(1024)
        assert request.startswith(b"CONNECT ipinfo.io:443 ")
        conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        with tls.wrap_socket(conn, server_side=True) as wrapped:
            wrapped.recv(1)

    denied = probe_proxy(f"http://127.0.0.1:{_serve(needs_auth)}")
    passed = probe_proxy(f"http://u:p@127.0.0.1:{_serve(works)}")

    assert (denied.ok, denied.stage) == (False, "handshake") and "账号密码" in denied.message
    assert (passed.ok, passed.stage) == (True, "done")


def test_unknown_schemes_are_not_probed():
    assert probe_proxy("vmess://abc").stage == "skipped"
