"""Real Xray TCP -> TLS relay -> authenticated SOCKS5, entirely on loopback.

Set CLOAKBROWSER_RELAY_TEST_XRAY to an Xray binary to run this test. Normal
unit tests never download a runtime or use the user's proxy accounts.
"""
import asyncio
import datetime
import ipaddress
import json
import os
import socket
import subprocess
from pathlib import Path

import pytest

from backend.xray_runtime import _xray_env, build_xray_config


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_supported_encrypted_relay_configs_load_in_real_xray(tmp_path):
    binary = os.environ.get("CLOAKBROWSER_RELAY_TEST_XRAY")
    if not binary or not Path(binary).is_file():
        pytest.skip("An explicit Xray test binary is required")
    import base64
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    public = X25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key = base64.urlsafe_b64encode(public).decode().rstrip("=")
    links = [
        "vmess://" + base64.b64encode(json.dumps({"add": "relay.example", "port": "443", "id": "11111111-1111-1111-1111-111111111111", "net": "tcp", "tls": "tls", "sni": "relay.example"}).encode()).decode(),
        f"vless://11111111-1111-1111-1111-111111111111@relay.example:443?security=reality&pbk={key}&sid=abcd&sni=example.com&flow=xtls-rprx-vision",
        "vless://11111111-1111-1111-1111-111111111111@relay.example:443?security=tls&sni=relay.example",
        "trojan://password@relay.example:443?sni=relay.example",
        "ss://" + base64.urlsafe_b64encode(b"aes-128-gcm:password").decode() + "@relay.example:8388",
    ]
    for i, link in enumerate(links):
        path = tmp_path/f"relay-config-{i}.json"
        path.write_text(json.dumps(build_xray_config("socks5://u:p@exit.example:1080", free_port(), relay_link=link)), encoding="utf-8")
        result = subprocess.run([binary, "run", "-test", "-config", str(path)], env=_xray_env(tmp_path), capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_real_relay_routes_authentication_and_never_falls_back(tmp_path):
    binary = os.environ.get("CLOAKBROWSER_RELAY_TEST_XRAY")
    if not binary or not Path(binary).is_file():
        pytest.skip("An explicit Xray test binary is required")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
            .not_valid_after(now+datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path/"cert.pem", tmp_path/"key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    seen = []
    tasks = set()

    async def final_socks(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            version, count = await reader.readexactly(2)
            assert version == 5 and 2 in await reader.readexactly(count)
            writer.write(b"\x05\x02"); await writer.drain()
            version, count = await reader.readexactly(2)
            user = await reader.readexactly(count)
            password = await reader.readexactly((await reader.readexactly(1))[0])
            assert version == 1 and user == b"alice" and password == b"p@ss:word"
            writer.write(b"\x01\x00"); await writer.drain()
            header = await reader.readexactly(4)
            assert header[:3] == b"\x05\x01\x00" and header[3] == 3
            host = await reader.readexactly((await reader.readexactly(1))[0])
            port = int.from_bytes(await reader.readexactly(2), "big")
            assert host == b"destination.invalid" and port == 80
            seen.append(host)
            writer.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00"); await writer.drain()
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\n\r\nCHAIN_OK")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    server = await asyncio.start_server(final_socks, "127.0.0.1", 0)
    final_port = server.sockets[0].getsockname()[1]
    relay_port, client_port = free_port(), free_port()
    processes = []

    async def start(config, filename, port):
        path = tmp_path/filename
        path.write_text(json.dumps(config), encoding="utf-8")
        process = await asyncio.create_subprocess_exec(binary, "run", "-config", str(path),
            env=_xray_env(tmp_path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        processes.append(process)
        for _ in range(100):
            if process.returncode is not None:
                output, _ = await process.communicate()
                raise AssertionError(f"Xray rejected {filename}: {output.decode(errors='replace')}")
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close(); await writer.wait_closed()
                return process
            except OSError:
                await asyncio.sleep(.05)
        raise AssertionError("Xray test listener did not start")

    async def request():
        reader, writer = await asyncio.open_connection("127.0.0.1", client_port)
        try:
            writer.write(b"\x05\x01\x00"); await writer.drain()
            assert await reader.readexactly(2) == b"\x05\x00"
            host = b"destination.invalid"
            writer.write(b"\x05\x01\x00\x03"+bytes([len(host)])+host+b"\x00\x50"); await writer.drain()
            header = await reader.readexactly(4)
            assert header[1] == 0
            if header[3] == 1: await reader.readexactly(6)
            elif header[3] == 4: await reader.readexactly(18)
            else: await reader.readexactly((await reader.readexactly(1))[0]+2)
            writer.write(b"GET / HTTP/1.1\r\nHost: destination.invalid\r\n\r\n"); await writer.drain()
            return await reader.readuntil(b"CHAIN_OK")
        finally:
            writer.close()
            await writer.wait_closed()

    try:
        relay = await start({"log": {"loglevel": "debug"}, "inbounds": [{"listen": "127.0.0.1", "port": relay_port,
            "protocol": "trojan", "settings": {"clients": [{"password": "relay-secret"}]}, "streamSettings": {"security": "tls",
            "tlsSettings": {"certificates": [{"certificateFile": str(cert_path), "keyFile": str(key_path)}]}}}],
            "outbounds": [{"protocol": "freedom", "settings": {"finalRules": [
                {"action": "allow", "network": "tcp", "ip": ["127.0.0.1"], "port": str(final_port)},
            ]}}]}, "relay.json", relay_port)
        config = build_xray_config(f"socks5://alice:p%40ss%3Aword@127.0.0.1:{final_port}", client_port,
            relay_link=f"trojan://relay-secret@127.0.0.1:{relay_port}?sni=localhost")
        config["log"]["loglevel"] = "debug"
        # Trust only this test CA; the real TLS handshake remains verified.
        tls = config["outbounds"][1]["streamSettings"]["tlsSettings"]
        tls.pop("allowInsecure", None)
        tls["certificates"] = [{"certificateFile": str(cert_path), "usage": "verify"}]
        await start(config, "client.json", client_port)
        assert b"CHAIN_OK" in await asyncio.wait_for(request(), 6)
        assert seen == [b"destination.invalid"]
        relay.terminate(); await asyncio.wait_for(relay.wait(), 3)
        with pytest.raises((AssertionError, OSError, asyncio.IncompleteReadError, asyncio.TimeoutError)):
            await asyncio.wait_for(request(), 4)
        assert len(seen) == 1, "The dead relay was bypassed by a direct SOCKS5 connection"
    finally:
        for process in processes:
            if process.returncode is None:
                process.terminate()
                try: await asyncio.wait_for(process.wait(), 3)
                except asyncio.TimeoutError: process.kill(); await process.wait()
            if process.stdout:
                print((await process.stdout.read()).decode(errors="replace")[-8000:])
        server.close(); await server.wait_closed()
        for task in list(tasks): task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
