"""Reject requests that a malicious web page could forge against the local API.

Two attacks matter for a Manager listening on 127.0.0.1 without a password:

* DNS rebinding: attacker.example re-resolves to 127.0.0.1, so its page can
  read API responses same-origin. The request still carries
  ``Host: attacker.example``, so native installs only accept loopback Host
  names (plus any listed in CLOAKBROWSER_MANAGER_ALLOWED_HOSTS).
* Cross-site requests: any page can POST to http://127.0.0.1:8080 without
  reading the answer. Browsers attach an Origin header to those, so state
  changing requests and WebSocket upgrades must come from the Manager's own
  origin. Clients without Origin (curl, Playwright, scripts) are unaffected.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Mapping
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("cloakbrowser.manager.guard")

ALLOWED_HOSTS_ENV = "CLOAKBROWSER_MANAGER_ALLOWED_HOSTS"
LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def allowed_hostnames(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    env = os.environ if environ is None else environ
    extra = (env.get(ALLOWED_HOSTS_ENV) or "").split(",")
    return LOOPBACK_HOSTNAMES | {item.strip().lower().strip("[]") for item in extra if item.strip()}


def _split_netloc(netloc: str, scheme: str = "http") -> tuple[str, int] | None:
    try:
        parsed = urlsplit(f"{scheme}://{netloc}")
        hostname = (parsed.hostname or "").lower()
        port = parsed.port or _DEFAULT_PORTS.get(scheme, 80)
    except ValueError:
        return None
    if not hostname:
        return None
    return hostname, port


def host_is_allowed(host_header: str | None, allowed: Iterable[str]) -> bool:
    if not host_header:
        return False
    split = _split_netloc(host_header)
    return split is not None and split[0] in set(allowed)


def origin_matches_host(origin: str | None, host_header: str | None) -> bool:
    """A browser Origin must name the same host and port the request was sent to."""
    if origin is None:
        return True
    if not host_header or origin.strip().lower() == "null":
        return False
    try:
        parsed = urlsplit(origin.strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    origin_split = _split_netloc(parsed.netloc, parsed.scheme)
    # Behind a TLS reverse proxy the Host header has no scheme; assume the
    # origin's scheme for its default port.
    host_split = _split_netloc(host_header, parsed.scheme)
    return origin_split is not None and origin_split == host_split


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


class RequestGuardMiddleware:
    """Raw ASGI middleware (BaseHTTPMiddleware would break WebSocket routes)."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        local_only: Callable[[], bool],
        allowed_hosts: Callable[[], Iterable[str]] = allowed_hostnames,
    ) -> None:
        self.app = app
        self.local_only = local_only
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        host = _header(scope, b"host")
        origin = _header(scope, b"origin")
        reason: str | None = None
        if self.local_only() and not host_is_allowed(host, self.allowed_hosts()):
            reason = "Host not allowed"
        elif (
            scope["type"] == "websocket" or scope.get("method", "GET").upper() in UNSAFE_METHODS
        ) and not origin_matches_host(origin, host):
            reason = "Cross-site request blocked"

        if reason is None:
            await self.app(scope, receive, send)
            return

        logger.warning("%s: %s %s host=%s origin=%s", reason, scope.get("method", "WS"), scope["path"], host, origin)
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 4403, "reason": reason})
            return
        response = JSONResponse({"detail": f"已拒绝来自其他网站的请求（{reason}）"}, status_code=403)
        await response(scope, receive, send)
