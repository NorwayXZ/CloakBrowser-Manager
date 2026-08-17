"""Xray link parsing and per-profile local proxy runtime.

The browser only needs a local SOCKS5 endpoint.  This module converts common
subscription links into Xray outbound configurations and owns the Xray child
process for the lifetime of one browser profile.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import socket
import ssl
import stat
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

logger = logging.getLogger("cloakbrowser.manager.xray")

XRAY_SCHEMES = frozenset({"ss", "vmess", "vless", "trojan"})
XRAY_GITHUB_API = "https://api.github.com/repos/XTLS/Xray-core/releases/latest"
XRAY_GITHUB_LATEST_DOWNLOAD = "https://github.com/XTLS/Xray-core/releases/latest/download"
XRAY_BINARY_ENV = "CLOAKBROWSER_XRAY_PATH"
XRAY_DATA_FILES = ("geoip.dat", "geosite.dat")


class XrayProxyError(ValueError):
    """Raised when an Xray link or local Xray runtime is invalid."""


def is_xray_link(value: str | None) -> bool:
    if not value:
        return False
    return urlsplit(value.strip()).scheme.lower() in XRAY_SCHEMES


def _decode_base64(value: str) -> bytes:
    value = unquote(value).strip().replace("-", "+").replace("_", "/")
    value += "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise XrayProxyError("链接中的 Base64 内容无法解析") from exc


def _first(query: dict[str, list[str]], *names: str, default: str = "") -> str:
    for name in names:
        values = query.get(name)
        if values:
            return str(values[-1])
    return default


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _int(value: Any, field: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise XrayProxyError(f"{field} 必须是数字") from exc
    if parsed < 1 or parsed > 65535:
        raise XrayProxyError(f"{field} 超出范围")
    return parsed


def _host_port(host: str | None, port: Any, *, label: str = "服务器") -> tuple[str, int]:
    if not host:
        raise XrayProxyError(f"{label}地址不能为空")
    return host, _int(port, f"{label}端口")


def _alpn(value: str) -> list[str] | None:
    values = [item.strip() for item in value.split(",") if item.strip()]
    return values or None


def _stream_settings(
    *,
    host: str,
    query: dict[str, list[str]],
    network: str = "tcp",
    security: str = "none",
    defaults: dict[str, str] | None = None,
) -> dict[str, Any]:
    defaults = defaults or {}
    network = (network or "tcp").lower()
    security = (security or "none").lower()
    if network not in {"tcp", "ws", "grpc", "http", "h2", "quic", "kcp", "xhttp"}:
        raise XrayProxyError(f"暂不支持 Xray 传输方式：{network}")
    if security not in {"none", "tls", "reality"}:
        raise XrayProxyError(f"暂不支持 Xray 安全方式：{security}")

    settings: dict[str, Any] = {
        "network": network,
        "security": security,
    }

    if security == "tls":
        tls: dict[str, Any] = {
            "serverName": _first(query, "sni", "serverName", default=defaults.get("serverName", host)),
            "allowInsecure": _bool(_first(query, "allowInsecure", "allow_insecure")),
        }
        alpn = _alpn(_first(query, "alpn"))
        if alpn:
            tls["alpn"] = alpn
        fingerprint = _first(query, "fp", "fingerprint")
        if fingerprint:
            tls["fingerprint"] = fingerprint
        settings["tlsSettings"] = tls
    elif security == "reality":
        public_key = _first(query, "pbk", "publicKey")
        if not public_key:
            raise XrayProxyError("VLESS Reality 链接缺少 pbk/publicKey")
        reality: dict[str, Any] = {
            "serverName": _first(query, "sni", "serverName", default=defaults.get("serverName", host)),
            "fingerprint": _first(query, "fp", "fingerprint", default="chrome"),
            "publicKey": public_key,
            "shortId": _first(query, "sid", "shortId"),
        }
        spider_x = _first(query, "spx", "spiderX")
        if spider_x:
            reality["spiderX"] = unquote(spider_x)
        settings["realitySettings"] = reality

    path = unquote(_first(query, "path", default="/"))
    host_header = _first(query, "host", "eh", default=host)
    if network == "ws":
        settings["wsSettings"] = {
            "path": path or "/",
            "headers": {"Host": host_header} if host_header else {},
        }
    elif network in {"http", "h2"}:
        settings["httpSettings"] = {
            "path": path or "/",
            "host": [host_header] if host_header else [],
        }
    elif network == "grpc":
        grpc: dict[str, Any] = {
            "serviceName": unquote(_first(query, "serviceName", "service_name")),
        }
        if _first(query, "mode") == "multi":
            grpc["multiMode"] = True
        settings["grpcSettings"] = grpc
    elif network == "quic":
        settings["quicSettings"] = {
            "security": _first(query, "quicSecurity", "quic_security"),
            "key": _first(query, "key"),
            "header": {"type": _first(query, "headerType", "header_type", default="none")},
        }
    elif network == "kcp":
        settings["kcpSettings"] = {
            "mtu": int(_first(query, "mtu", default="1350") or 1350),
            "tti": int(_first(query, "tti", default="50") or 50),
            "uplinkCapacity": int(_first(query, "uplinkCapacity", default="5") or 5),
            "downlinkCapacity": int(_first(query, "downlinkCapacity", default="20") or 20),
            "congestion": _bool(_first(query, "congestion")),
            "header": {"type": _first(query, "headerType", "header_type", default="none")},
            "seed": _first(query, "seed"),
        }
    elif network == "xhttp":
        settings["xhttpSettings"] = {
            "path": path or "/",
            "host": host_header,
            "mode": _first(query, "mode", default="auto"),
        }

    return settings


def _parse_vless(value: str) -> dict[str, Any]:
    parsed = urlsplit(value)
    if not parsed.hostname or not parsed.port or not parsed.username:
        raise XrayProxyError("VLESS 链接必须包含 UUID、服务器地址和端口")
    host, port = _host_port(parsed.hostname, parsed.port)
    query = parse_qs(parsed.query, keep_blank_values=True)
    network = _first(query, "type", "network", default="tcp")
    security = _first(query, "security", default="none")
    user: dict[str, Any] = {
        "id": unquote(parsed.username),
        "encryption": _first(query, "encryption", default="none"),
    }
    flow = _first(query, "flow")
    if flow:
        user["flow"] = flow
    outbound: dict[str, Any] = {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": host,
                "port": port,
                "users": [user],
            }],
        },
        "streamSettings": _stream_settings(
            host=host,
            query=query,
            network=network,
            security=security,
        ),
    }
    return {"protocol": "vless", "name": unquote(parsed.fragment), "outbound": outbound}


def _parse_trojan(value: str) -> dict[str, Any]:
    parsed = urlsplit(value)
    if not parsed.hostname or not parsed.port or not parsed.username:
        raise XrayProxyError("Trojan 链接必须包含密码、服务器地址和端口")
    host, port = _host_port(parsed.hostname, parsed.port)
    query = parse_qs(parsed.query, keep_blank_values=True)
    network = _first(query, "type", "network", default="tcp")
    security = _first(query, "security", default="tls")
    outbound: dict[str, Any] = {
        "protocol": "trojan",
        "settings": {
            "servers": [{
                "address": host,
                "port": port,
                "password": unquote(parsed.username),
            }],
        },
        "streamSettings": _stream_settings(
            host=host,
            query=query,
            network=network,
            security=security,
        ),
    }
    return {"protocol": "trojan", "name": unquote(parsed.fragment), "outbound": outbound}


def _parse_vmess(value: str) -> dict[str, Any]:
    payload = value[len("vmess://"):]
    try:
        data = json.loads(_decode_base64(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, XrayProxyError) as exc:
        raise XrayProxyError("VMess 链接不是有效的 Base64 JSON") from exc
    if not isinstance(data, dict):
        raise XrayProxyError("VMess 链接内容不是对象")
    host, port = _host_port(str(data.get("add") or ""), data.get("port"), label="VMess服务器")
    user_id = str(data.get("id") or "")
    if not user_id:
        raise XrayProxyError("VMess 链接缺少 UUID")

    query: dict[str, list[str]] = {
        key: [str(value)]
        for key, value in data.items()
        if value is not None
    }
    network = str(data.get("net") or "tcp")
    security = str(data.get("tls") or "none").lower()
    if security in {"1", "true"}:
        security = "tls"
    if security == "":
        security = "none"
    user: dict[str, Any] = {
        "id": user_id,
        "alterId": int(data.get("aid") or 0),
        "security": str(data.get("scy") or "auto"),
    }
    outbound: dict[str, Any] = {
        "protocol": "vmess",
        "settings": {
            "vnext": [{
                "address": host,
                "port": port,
                "users": [user],
            }],
        },
        "streamSettings": _stream_settings(
            host=host,
            query=query,
            network=network,
            security=security,
            defaults={"serverName": str(data.get("sni") or host)},
        ),
    }
    return {
        "protocol": "vmess",
        "name": str(data.get("ps") or ""),
        "outbound": outbound,
    }


def _parse_shadowsocks(value: str) -> dict[str, Any]:
    body = value[len("ss://"):].split("#", 1)[0]
    if not body:
        raise XrayProxyError("Shadowsocks 链接为空")

    credentials: str
    endpoint: str
    if "@" in body:
        encoded_credentials, endpoint = body.rsplit("@", 1)
        try:
            credentials = _decode_base64(encoded_credentials).decode("utf-8")
        except (UnicodeDecodeError, XrayProxyError):
            credentials = unquote(encoded_credentials)
    else:
        try:
            decoded = _decode_base64(body).decode("utf-8")
        except (UnicodeDecodeError, XrayProxyError) as exc:
            raise XrayProxyError("Shadowsocks 链接无法解析") from exc
        if "@" not in decoded:
            raise XrayProxyError("Shadowsocks 链接缺少服务器地址")
        credentials, endpoint = decoded.rsplit("@", 1)

    if ":" not in credentials:
        raise XrayProxyError("Shadowsocks 链接缺少加密方式或密码")
    method, password = credentials.split(":", 1)
    endpoint = unquote(endpoint)
    parsed_endpoint = urlsplit(f"//{endpoint}")
    if not parsed_endpoint.hostname or not parsed_endpoint.port:
        raise XrayProxyError("Shadowsocks 链接缺少服务器端口")
    host, port = _host_port(parsed_endpoint.hostname, parsed_endpoint.port, label="Shadowsocks服务器")
    outbound = {
        "protocol": "shadowsocks",
        "settings": {
            "servers": [{
                "address": host,
                "port": port,
                "method": method,
                "password": password,
            }],
        },
    }
    return {
        "protocol": "ss",
        "name": unquote(value.split("#", 1)[1]) if "#" in value else "",
        "outbound": outbound,
    }


def parse_xray_link(value: str) -> dict[str, Any]:
    """Parse a supported share link into one Xray outbound object."""
    raw = value.strip()
    scheme = urlsplit(raw).scheme.lower()
    if scheme == "ss":
        return _parse_shadowsocks(raw)
    if scheme == "vmess":
        return _parse_vmess(raw)
    if scheme == "vless":
        return _parse_vless(raw)
    if scheme == "trojan":
        return _parse_trojan(raw)
    raise XrayProxyError(
        "不支持的代理协议。支持 HTTP、HTTPS、SOCKS5、Shadowsocks、VMess、VLESS、Trojan"
    )


def build_xray_config(link: str, local_port: int) -> dict[str, Any]:
    parsed = parse_xray_link(link)
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "tag": "browser-socks",
            "listen": "127.0.0.1",
            "port": local_port,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True},
        }],
        "outbounds": [
            {**parsed["outbound"], "tag": "proxy"},
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [{
                "type": "field",
                "ip": ["geoip:private"],
                "outboundTag": "direct",
            }],
        },
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _binary_name() -> str:
    return "xray.exe" if os.name == "nt" else "xray"


def _candidate_binary_paths(data_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get(XRAY_BINARY_ENV)
    if configured:
        candidates.append(Path(configured).expanduser())
    root = Path(__file__).resolve().parent.parent
    candidates.extend([
        root / "bin" / _binary_name(),
        root / "bin" / "xray" / _binary_name(),
        data_dir / "xray" / _binary_name(),
    ])
    on_path = shutil.which("xray")
    if on_path:
        candidates.append(Path(on_path))
    return candidates


def find_xray_binary(data_dir: Path) -> Path | None:
    for candidate in _candidate_binary_paths(data_dir):
        if candidate.is_file():
            return candidate
    return None


def _candidate_data_dirs(binary: Path, data_dir: Path) -> list[Path]:
    root = Path(__file__).resolve().parent.parent
    return [
        binary.parent,
        root / "bin" / "xray",
        data_dir / "xray",
    ]


def _has_xray_data_files(path: Path) -> bool:
    return all((path / filename).is_file() for filename in XRAY_DATA_FILES)


def find_xray_data_dir(binary: Path, data_dir: Path) -> Path | None:
    for candidate in _candidate_data_dirs(binary, data_dir):
        if _has_xray_data_files(candidate):
            return candidate
    return None


def _release_asset_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arm = machine in {"arm64", "aarch64"} or "arm" in machine
    if system == "darwin":
        return "Xray-macos-arm64-v8a.zip" if arm else "Xray-macos-64.zip"
    if system == "windows":
        return "Xray-windows-arm64-v8a.zip" if arm else "Xray-windows-64.zip"
    if system == "linux":
        return "Xray-linux-arm64-v8a.zip" if arm else "Xray-linux-64.zip"
    raise XrayProxyError(f"当前系统暂不支持自动安装 Xray：{system}")


def _github_api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "CloakBrowser-Manager",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _resolve_xray_release_assets(
    asset_name: str,
    *,
    context: ssl.SSLContext,
) -> tuple[dict[str, str], str]:
    request = urllib.request.Request(XRAY_GITHUB_API, headers=_github_api_headers())
    try:
        with urllib.request.urlopen(request, context=context, timeout=30) as response:
            release = json.load(response)
        assets = {
            str(asset.get("name")): str(asset.get("browser_download_url"))
            for asset in release.get("assets", [])
            if isinstance(asset, dict)
        }
        if assets.get(asset_name):
            return assets, str(release.get("tag_name") or "unknown")
        raise XrayProxyError(f"Xray 官方版本中没有找到 {asset_name}")
    except XrayProxyError:
        raise
    except Exception as exc:
        logger.warning(
            "GitHub release API unavailable (%s); using official latest asset URLs",
            exc,
        )
        base = XRAY_GITHUB_LATEST_DOWNLOAD.rstrip("/")
        return {
            asset_name: f"{base}/{asset_name}",
            f"{asset_name}.dgst": f"{base}/{asset_name}.dgst",
        }, "latest-direct"


def _download_xray_binary_sync(data_dir: Path) -> Path:
    target_dir = data_dir / "xray"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _binary_name()
    asset_name = _release_asset_name()
    try:
        # certifi is provided by the Manager dependencies and avoids the
        # incomplete system CA bundle found in some Python installations.
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()

    assets, release_tag = _resolve_xray_release_assets(asset_name, context=context)
    download_url = assets.get(asset_name)
    if not download_url:
        raise XrayProxyError(f"Xray 官方版本中没有找到 {asset_name}")

    archive_path = target_dir / asset_name
    def download(url: str) -> bytes:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "CloakBrowser-Manager"},
        )
        with urllib.request.urlopen(request, context=context, timeout=120) as response:
            return response.read()

    try:
        archive_bytes = download(download_url)
        digest_url = assets.get(f"{asset_name}.dgst")
        if digest_url:
            digest_text = download(digest_url).decode("utf-8", errors="replace")
            match = re.search(r"SHA2-256=\s*([0-9a-fA-F]{64})", digest_text)
            if not match:
                raise XrayProxyError("Xray 摘要文件中没有 SHA2-256 校验值")
            actual_digest = hashlib.sha256(archive_bytes).hexdigest()
            if actual_digest.lower() != match.group(1).lower():
                raise XrayProxyError("Xray 下载文件校验失败")
        archive_path.write_bytes(archive_bytes)
        with zipfile.ZipFile(archive_path) as archive:
            member = next(
                (name for name in archive.namelist() if Path(name).name == _binary_name()),
                None,
            )
            if not member:
                raise XrayProxyError("Xray 压缩包中没有找到可执行文件")
            extracted = archive.read(member)
            missing_data_files: list[str] = []
            for filename in XRAY_DATA_FILES:
                data_member = next(
                    (name for name in archive.namelist() if Path(name).name == filename),
                    None,
                )
                if not data_member:
                    missing_data_files.append(filename)
                    continue
                (target_dir / filename).write_bytes(archive.read(data_member))
            if missing_data_files:
                raise XrayProxyError(
                    "Xray 压缩包中缺少数据文件："
                    + ", ".join(missing_data_files)
                )
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(extracted)
        temporary.replace(target)
        if os.name != "nt":
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    except XrayProxyError:
        raise
    except Exception as exc:
        raise XrayProxyError(f"下载或解压 Xray 失败：{exc}") from exc
    finally:
        archive_path.unlink(missing_ok=True)
    logger.info("Installed Xray core %s at %s", release_tag, target)
    return target


async def ensure_xray_binary(data_dir: Path) -> Path:
    existing = find_xray_binary(data_dir)
    if existing:
        return existing
    return await asyncio.to_thread(_download_xray_binary_sync, data_dir)


async def ensure_xray_runtime(data_dir: Path) -> tuple[Path, Path]:
    binary = await ensure_xray_binary(data_dir)
    data_files_dir = find_xray_data_dir(binary, data_dir)
    if data_files_dir is not None:
        return binary, data_files_dir

    logger.info("Xray data files are missing; downloading geoip.dat and geosite.dat")
    await asyncio.to_thread(_download_xray_binary_sync, data_dir)
    data_files_dir = find_xray_data_dir(binary, data_dir)
    if data_files_dir is None:
        installed_binary = data_dir / "xray" / _binary_name()
        data_files_dir = find_xray_data_dir(installed_binary, data_dir)
        if data_files_dir is not None and installed_binary.is_file():
            binary = installed_binary
    if data_files_dir is None:
        raise XrayProxyError(
            "Xray 数据文件缺失：geoip.dat / geosite.dat。"
            "请重新运行安装程序，或把这两个文件放到数据目录的 xray 文件夹。"
        )
    return binary, data_files_dir


@dataclass
class XrayProcess:
    process: asyncio.subprocess.Process
    binary: Path
    config_path: Path
    log_handle: Any
    local_port: int

    @property
    def browser_proxy(self) -> str:
        return f"socks5://127.0.0.1:{self.local_port}"

    async def close(self) -> None:
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        try:
            self.log_handle.close()
        except Exception:
            pass


async def _wait_for_xray(process: asyncio.subprocess.Process, port: int) -> None:
    deadline = asyncio.get_running_loop().time() + 12
    while asyncio.get_running_loop().time() < deadline:
        if process.returncode is not None:
            raise XrayProxyError(
                "Xray 启动失败，请检查代理链接或查看数据目录中的 xray.log"
            )
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.1)
    raise XrayProxyError("Xray 启动超时，请检查代理链接或查看 xray.log")


async def start_xray_proxy(
    link: str,
    *,
    user_data_dir: Path,
    data_dir: Path,
) -> XrayProcess:
    """Start one local SOCKS5 endpoint backed by an Xray outbound."""
    binary, xray_asset_dir = await ensure_xray_runtime(data_dir)
    local_port = _free_port()
    xray_dir = user_data_dir / "xray"
    xray_dir.mkdir(parents=True, exist_ok=True)
    config_path = xray_dir / "config.json"
    log_path = xray_dir / "xray.log"
    config_path.write_text(
        json.dumps(build_xray_config(link, local_port), indent=2),
        encoding="utf-8",
    )
    if os.name != "nt":
        config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    log_handle = log_path.open("ab")
    try:
        process = await asyncio.create_subprocess_exec(
            str(binary),
            "run",
            "-config",
            str(config_path),
            stdout=log_handle,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(xray_asset_dir),
            env={**os.environ, "XRAY_LOCATION_ASSET": str(xray_asset_dir)},
        )
        await _wait_for_xray(process, local_port)
    except BaseException:
        try:
            log_handle.close()
        except Exception:
            pass
        config_path.unlink(missing_ok=True)
        raise
    logger.info("Started Xray proxy on %s for %s", local_port, user_data_dir)
    return XrayProcess(
        process=process,
        binary=binary,
        config_path=config_path,
        log_handle=log_handle,
        local_port=local_port,
    )
