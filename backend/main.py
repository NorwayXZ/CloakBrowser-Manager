"""CloakBrowser Manager — FastAPI application.

Serves the React dashboard (static files) and provides a REST API
for browser profile management with live VNC viewing.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import struct
import shutil
import time
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import Body, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import starlette.requests
from starlette.types import ASGIApp, Receive, Scope, Send

from . import database as db
from .browser_manager import BrowserManager, _normalize_proxy, _validate_proxy
from .fingerprint_report import DIAGNOSTIC_SCRIPT
from .proxy_bridge import HttpProxyBridge
from .proxy_geo import fetch_proxy_geo
from .updater import UpdateError, update_from_git
from .xray_runtime import is_xray_link, start_xray_proxy
from .models import (
    AuthAccountUpdate,
    BrowserUpdateResponse,
    ClipboardRequest,
    GroupCreate,
    GroupResponse,
    LaunchRequest,
    LaunchResponse,
    LoginRequest,
    ManagerUpdateResponse,
    ProfileCreate,
    ProfileResponse,
    ProfileStatusResponse,
    PreflightResponse,
    ProxyPresetBulkCreate,
    ProxyPresetCreate,
    ProxyPresetResponse,
    ProxyTestRequest,
    ProxyTestResponse,
    ProfileUpdate,
    StatusResponse,
    TagResponse,
)

logger = logging.getLogger("cloakbrowser.manager")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

# Optional authentication. Local installs can run without auth. Hosted installs
# can set ADMIN_USERNAME + ADMIN_PASSWORD for browser login, and/or AUTH_TOKEN
# for API/Bearer-token compatibility.
AUTH_TOKEN: str | None = os.environ.get("AUTH_TOKEN") or None
ADMIN_USERNAME_ENV: str | None = os.environ.get("ADMIN_USERNAME") or None
ADMIN_PASSWORD_ENV: str | None = os.environ.get("ADMIN_PASSWORD") or None

_AUTH_USERNAME_KEY = "auth.username"
_AUTH_PASSWORD_KEY = "auth.password_hash"
_AUTH_COOKIE_NAME = "auth_token"
_AUTH_SESSION_TTL = 30 * 24 * 60 * 60
_PBKDF2_ITERATIONS = 260_000

# Paths that bypass authentication even when AUTH_TOKEN is set
_AUTH_EXEMPT = frozenset({"/api/auth/status", "/api/auth/login", "/api/status"})


def _setting(key: str) -> str | None:
    try:
        return db.get_setting(key)
    except Exception as exc:
        logger.debug("Auth setting read skipped for %s: %s", key, exc)
        return None


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), _PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def _verify_password(password: str, stored: str | None) -> bool:
    if not password or not stored:
        return False
    try:
        algo, rounds_raw, salt, expected = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        rounds = int(rounds_raw)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), rounds
        ).hex()
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def _auth_username() -> str:
    return _setting(_AUTH_USERNAME_KEY) or ADMIN_USERNAME_ENV or "admin"


def _auth_required() -> bool:
    return bool(AUTH_TOKEN or _setting(_AUTH_PASSWORD_KEY))


def _ensure_auth_bootstrap() -> None:
    """Create the first admin account from env vars, without overwriting edits."""
    if _setting(_AUTH_PASSWORD_KEY):
        if not _setting(_AUTH_USERNAME_KEY):
            db.set_setting(_AUTH_USERNAME_KEY, ADMIN_USERNAME_ENV or "admin")
        return

    password = ADMIN_PASSWORD_ENV or AUTH_TOKEN
    if not password:
        return

    db.set_setting(_AUTH_USERNAME_KEY, ADMIN_USERNAME_ENV or "admin")
    db.set_setting(_AUTH_PASSWORD_KEY, _hash_password(password))


def _verify_admin_password(password: str) -> bool:
    if _verify_password(password, _setting(_AUTH_PASSWORD_KEY)):
        return True
    return bool(AUTH_TOKEN and hmac.compare_digest(password or "", AUTH_TOKEN))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _session_secret() -> bytes:
    seed = "\0".join((
        os.environ.get("SESSION_SECRET", ""),
        _setting(_AUTH_PASSWORD_KEY) or "",
        AUTH_TOKEN or "",
    ))
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _make_session_cookie(username: str) -> str:
    payload = _b64url(json.dumps(
        {"u": username, "iat": int(time.time())},
        separators=(",", ":"),
    ).encode("utf-8"))
    sig = _b64url(hmac.new(_session_secret(), payload.encode("ascii"), hashlib.sha256).digest())
    return f"v1.{payload}.{sig}"


def _verify_session_cookie(value: str) -> bool:
    if AUTH_TOKEN and hmac.compare_digest(value, AUTH_TOKEN):
        return True
    try:
        version, payload, sig = value.split(".", 2)
        if version != "v1":
            return False
        expected = _b64url(hmac.new(
            _session_secret(), payload.encode("ascii"), hashlib.sha256
        ).digest())
        if not hmac.compare_digest(sig, expected):
            return False
        data = json.loads(_b64url_decode(payload))
        if not isinstance(data, dict):
            return False
        issued_at = int(data.get("iat", 0))
        if issued_at <= 0 or time.time() - issued_at > _AUTH_SESSION_TTL:
            return False
        return data.get("u") == _auth_username()
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return False


def _check_auth(scope: Scope) -> bool:
    """Check if the request has a valid auth token (header or cookie)."""
    if not _auth_required():
        return True

    # Check Authorization: Bearer <token> header
    for key, val in scope.get("headers", []):
        if key == b"authorization":
            auth_value = val.decode()
            if auth_value.startswith("Bearer "):
                token = auth_value[7:]
                if AUTH_TOKEN and token and hmac.compare_digest(token, AUTH_TOKEN):
                    return True
            break

    # Check signed session cookie, or legacy AUTH_TOKEN cookie
    for key, val in scope.get("headers", []):
        if key == b"cookie":
            cookies = SimpleCookie()
            cookies.load(val.decode())
            if _AUTH_COOKIE_NAME in cookies:
                cookie_val = cookies[_AUTH_COOKIE_NAME].value
                if cookie_val and _verify_session_cookie(cookie_val):
                    return True
            break

    return False


def _is_https(request: Request) -> bool:
    """Check if the original client connection was HTTPS (via reverse proxy header)."""
    proto = request.headers.get("x-forwarded-proto", "")
    return "https" in proto


async def _check_websocket_origin(websocket: WebSocket) -> bool:
    """Reject cross-origin WebSocket connections (CSWSH protection).

    Browsers always send an Origin header on WebSocket upgrades.
    Non-browser clients (Playwright, curl) typically don't — those are allowed.
    If Origin is present, its host must match the request Host header.
    """
    origin = None
    host = None
    for key, val in websocket.scope.get("headers", []):
        if key == b"origin":
            origin = val.decode("latin-1")
        elif key == b"host":
            host = val.decode("latin-1")

    # No Origin header → non-browser client (Playwright, Puppeteer) → allow
    if not origin:
        return True

    # Parse origin to extract host:port
    try:
        parsed = urlparse(origin)
        origin_host = parsed.hostname or ""
        origin_port = parsed.port
    except ValueError:
        logger.warning("WebSocket origin malformed: %s", origin)
        await websocket.close(code=4403, reason="Origin not allowed")
        return False
    # Build origin netloc (host:port or just host if default port)
    if origin_port and origin_port not in (80, 443):
        origin_netloc = f"{origin_host}:{origin_port}"
    else:
        origin_netloc = origin_host

    if not host:
        return True  # no Host header to compare against

    # Strip default port from Host too (some proxies send "example.com:443")
    host_normalized = host
    if host.endswith(":80") or host.endswith(":443"):
        host_normalized = host.rsplit(":", 1)[0]

    if origin_netloc == host_normalized:
        return True

    logger.warning("WebSocket origin mismatch: origin=%s host=%s", origin, host)
    await websocket.close(code=4403, reason="Origin not allowed")
    return False


class AuthMiddleware:
    """Raw ASGI middleware for optional token auth.

    Uses raw ASGI instead of BaseHTTPMiddleware because the latter
    breaks WebSocket routes (wraps request body, preventing WS upgrade).
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        # Pass through non-HTTP/WS scopes (e.g. lifespan)
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        # Skip auth for exempt endpoints and non-API paths (static frontend)
        if path in _AUTH_EXEMPT or not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        if not _auth_required():
            await self.app(scope, receive, send)
            return

        if _check_auth(scope):
            await self.app(scope, receive, send)
            return

        # Reject — unauthenticated
        if scope["type"] == "websocket":
            # ASGI requires receiving websocket.connect before sending close
            await receive()
            await send({"type": "websocket.close", "code": 4401, "reason": "Unauthorized"})
        else:
            response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)


# Singleton browser manager
browser_mgr = BrowserManager()

# Frontend build directory (React production build)
FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# RFB server message translator — KasmVNC BinaryClipboard → standard RFB
# ---------------------------------------------------------------------------


def _parse_kasmvnc_clipboard(data: bytes) -> str | None:
    """Extract text/plain from KasmVNC BinaryClipboard (type 180).

    Format: type(1) + action(1) + flags(4) + entries...
    Each entry: mime_len(u8) + mime(N) + data_len(u32 BE) + data(M)
    """
    if len(data) < 7:
        return None
    offset = 6  # skip type(1) + action(1) + flags(4)
    while offset < len(data):
        if offset + 1 > len(data):
            break
        mime_len = data[offset]
        offset += 1
        if offset + mime_len > len(data):
            break
        mime_type = data[offset:offset + mime_len]
        offset += mime_len
        if offset + 4 > len(data):
            break
        data_len = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        if mime_type == b"text/plain":
            end = min(offset + data_len, len(data))
            return data[offset:end].decode("utf-8", errors="replace")
        offset += data_len
    return None


def _build_server_cut_text(text: str) -> bytes:
    """Build standard RFB ServerCutText (type 3) message.

    RFB spec mandates Latin-1 encoding for ServerCutText.
    Characters outside Latin-1 (CJK, emoji, etc.) are replaced with '?'.
    """
    text_bytes = text.encode("latin-1", errors="replace")
    return struct.pack(">BxxxI", 3, len(text_bytes)) + text_bytes


# ---------------------------------------------------------------------------
# RFB client message filter — strip extension types KasmVNC doesn't support
# ---------------------------------------------------------------------------
# noVNC v1.4 batches multiple RFB messages into one WebSocket frame.
# KasmVNC 1.3.3 crashes on unsupported types (150, 248, etc.).
# We parse message boundaries using known sizes and keep only standard types.

# Client→server message sizes (fixed, except 2 and 6 which encode length)
_RFB_MSG_SIZE: dict[int, int | None] = {
    0: 20,    # SetPixelFormat
    2: None,  # SetEncodings — 4 + numEncodings*4 (rewritten to strip bad pseudo-encodings)
    3: 10,    # FramebufferUpdateRequest
    4: 8,     # KeyEvent
    5: 6,     # PointerEvent
    6: None,  # ClientCutText — 8 + length
}

# Extension types that noVNC sends — known sizes so we can skip past them
# instead of breaking and dropping all trailing data in the frame.
_RFB_EXTENSION_SIZE: dict[int, int] = {
    150: 10,  # EnableContinuousUpdates (1+1+2+2+2+2)
    248: 10,  # QEMU-like key event (observed from noVNC 1.4.0)
    252: 4,   # xvp (1+1+1+1)
    255: 4,   # QEMU audio control (1+1+2) — noVNC QEMUExtendedKeyEvent is actually 12
}

# Whitelist of encodings safe to send to KasmVNC.
# Instead of trying to blocklist problematic pseudo-encodings (error-prone —
# we had wrong numbers), we ONLY keep known-good encodings.
# Anything not on this list is stripped from SetEncodings.
_ALLOWED_ENCODINGS: set[int] = {
    # Framebuffer encodings (standard RFB)
    0,    # Raw
    1,    # CopyRect
    2,    # RRE
    5,    # Hextile
    7,    # Tight
    16,   # ZRLE
    # Safe pseudo-encodings
    -239,  # Cursor (0xFFFFFF11) — cursor shape
    -224,  # LastRect (0xFFFFFF20) — performance optimization
    # Tight quality/compress levels (these are just hints)
    *range(-32, -22),   # quality levels 0-9
    *range(-256, -246),  # compress levels 0-9
}


def _rfb_msg_length(data: bytes, offset: int) -> int | None:
    """Return total length of the RFB message at offset, or None if unrecognized."""
    if offset >= len(data):
        return None
    msg_type = data[offset]
    fixed = _RFB_MSG_SIZE.get(msg_type)
    if fixed is not None:
        return fixed
    remaining = len(data) - offset
    if msg_type == 2 and remaining >= 4:  # SetEncodings
        num_enc = struct.unpack_from(">H", data, offset + 2)[0]
        return 4 + num_enc * 4
    if msg_type == 6 and remaining >= 8:  # ClientCutText
        length = struct.unpack_from(">I", data, offset + 4)[0]
        return 8 + length
    # Known extension types — skip past them instead of giving up
    ext_size = _RFB_EXTENSION_SIZE.get(msg_type)
    if ext_size is not None:
        return ext_size
    return None  # truly unknown type


def _rewrite_set_encodings(data: bytes, offset: int, msg_len: int) -> bytes:
    """Keep only whitelisted encodings in a SetEncodings message."""
    _log = logging.getLogger("cloakbrowser.manager")
    num_enc = struct.unpack_from(">H", data, offset + 2)[0]
    kept = []
    stripped = []
    for i in range(num_enc):
        enc = struct.unpack_from(">i", data, offset + 4 + i * 4)[0]  # signed
        if enc in _ALLOWED_ENCODINGS:
            kept.append(enc)
        else:
            stripped.append(enc)
    if not stripped:
        return data[offset:offset + msg_len]
    _log.info("RFB filter: SetEncodings keeping %d: %s, stripped %d: %s", len(kept), kept, len(stripped), stripped)
    result = struct.pack(">BxH", 2, len(kept))
    for enc in kept:
        result += struct.pack(">i", enc)
    return result


def _rewrite_pointer_event(data: bytes, offset: int) -> bytes:
    """Convert standard 6-byte PointerEvent to KasmVNC's 11-byte format.

    Standard RFB:  [5:u8][mask:u8][x:u16][y:u16]          = 6 bytes
    KasmVNC:       [5:u8][mask:u16][x:u16][y:u16][sx:s16][sy:s16] = 11 bytes
    """
    mask = data[offset + 1]
    x = struct.unpack_from(">H", data, offset + 2)[0]
    y = struct.unpack_from(">H", data, offset + 4)[0]
    # Expand mask from u8 to u16.  Scroll deltas (sx, sy) are zero because
    # noVNC encodes scroll as button-mask bits (3=up, 4=down, 5=left, 6=right)
    # which pass through in the mask.  KasmVNC accepts mask-bit scroll on its
    # extended 11-byte format, so explicit deltas are unnecessary.
    return struct.pack(">BHHHhh", 5, mask, x, y, 0, 0)


def _filter_rfb_client_messages(data: bytes) -> bytes:
    """Parse concatenated RFB messages, keep only standard types (0-6).

    Rewrites PointerEvents from 6-byte standard to 11-byte KasmVNC format
    and strips unsupported pseudo-encodings from SetEncodings.
    """
    _log = logging.getLogger("cloakbrowser.manager")
    result = bytearray()
    offset = 0
    msg_idx = 0
    while offset < len(data):
        msg_type = data[offset]
        msg_len = _rfb_msg_length(data, offset)
        if msg_len is None:
            _log.info("RFB filter: DROPPING unknown type=%d at offset=%d/%d, skipping %d trailing bytes, hex=%s",
                       msg_type, offset, len(data), len(data) - offset, data[offset:offset+20].hex())
            break
        if offset + msg_len > len(data):
            # Incomplete message — DO NOT forward partial data, it desynchronizes
            # the RFB stream (KasmVNC buffers partial reads across frames).
            _log.warning("RFB filter: DROPPING incomplete type=%d need=%d have=%d — would desync stream",
                         msg_type, msg_len, len(data) - offset)
            break
        msg_idx += 1
        if msg_type in _RFB_MSG_SIZE:
            # Standard RFB type — keep (with rewrites for KasmVNC compatibility)
            _log.debug("RFB filter: KEEP type=%d len=%d at offset=%d (msg #%d in frame)", msg_type, msg_len, offset, msg_idx)
            if msg_type == 2:  # SetEncodings — whitelist safe encodings
                result.extend(_rewrite_set_encodings(data, offset, msg_len))
            elif msg_type == 5:  # PointerEvent — expand to KasmVNC's 11-byte format
                result.extend(_rewrite_pointer_event(data, offset))
            else:
                result.extend(data[offset:offset + msg_len])
        else:
            # Extension type (150, 248, etc.) — skip but continue parsing
            _log.debug("RFB filter: SKIP extension type=%d len=%d at offset=%d (msg #%d in frame)", msg_type, msg_len, offset, msg_idx)
        offset += msg_len
    if len(result) != len(data):
        _log.info("RFB filter: input=%d output=%d (delta %+d bytes)", len(data), len(result), len(result) - len(data))
    return bytes(result)


@asynccontextmanager
async def lifespan(app: FastAPI):
    browser_mgr.vnc.validate_available()
    db.init_db()
    _ensure_auth_bootstrap()
    await browser_mgr.cleanup_stale()
    browser_mgr._auto_launch_task = asyncio.create_task(browser_mgr.auto_launch_all())
    logger.info("CloakBrowser Manager started")
    yield
    logger.info("Shutting down — stopping all browsers...")
    if browser_mgr._auto_launch_task and not browser_mgr._auto_launch_task.done():
        browser_mgr._auto_launch_task.cancel()
        await asyncio.gather(browser_mgr._auto_launch_task, return_exceptions=True)
    await browser_mgr.cleanup_all()


app = FastAPI(title="CloakBrowser Manager", lifespan=lifespan)
app.add_middleware(AuthMiddleware)


# ── Authentication ────────────────────────────────────────────────────────────


@app.get("/api/auth/status")
async def auth_status(request: starlette.requests.Request):
    """Check if auth is enabled and if the current request is authenticated.

    Exempt from auth middleware so the frontend can always call it.
    """
    required = _auth_required()
    authenticated = _check_auth(request.scope) if required else False
    return {
        "auth_required": required,
        "authenticated": authenticated,
        "username": _auth_username() if required else None,
    }


@app.post("/api/auth/login")
async def auth_login(body: LoginRequest, request: Request, response: Response):
    if not _auth_required():
        return {"ok": True}

    is_https = _is_https(request)

    if body.token and AUTH_TOKEN and hmac.compare_digest(body.token, AUTH_TOKEN):
        response.set_cookie(
            key=_AUTH_COOKIE_NAME,
            value=AUTH_TOKEN,
            httponly=True,
            samesite="strict",
            secure=is_https,
            path="/",
            max_age=_AUTH_SESSION_TTL,
        )
        return {"ok": True, "username": _auth_username()}

    username = (body.username or "").strip()
    password = body.password or ""
    if username != _auth_username() or not _verify_admin_password(password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    response.set_cookie(
        key=_AUTH_COOKIE_NAME,
        value=_make_session_cookie(username),
        httponly=True,
        samesite="strict",
        secure=is_https,
        path="/",
        max_age=_AUTH_SESSION_TTL,
    )
    return {"ok": True, "username": username}


@app.get("/api/auth/account")
async def auth_account():
    if not _auth_required():
        return {"username": None}
    return {"username": _auth_username()}


@app.put("/api/auth/account")
async def auth_account_update(body: AuthAccountUpdate, request: Request, response: Response):
    if not _auth_required():
        raise HTTPException(status_code=400, detail="当前没有开启登录保护")
    if not _verify_admin_password(body.current_password):
        raise HTTPException(status_code=401, detail="当前密码错误")

    username = (body.username or _auth_username()).strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")

    db.set_setting(_AUTH_USERNAME_KEY, username)
    if body.new_password:
        db.set_setting(_AUTH_PASSWORD_KEY, _hash_password(body.new_password))

    is_https = _is_https(request)
    response.set_cookie(
        key=_AUTH_COOKIE_NAME,
        value=_make_session_cookie(username),
        httponly=True,
        samesite="strict",
        secure=is_https,
        path="/",
        max_age=_AUTH_SESSION_TTL,
    )
    return {"ok": True, "username": username}


@app.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    is_https = _is_https(request)
    response.delete_cookie(
        key=_AUTH_COOKIE_NAME, path="/", secure=is_https, samesite="strict",
    )
    return {"ok": True}


# ── Profile CRUD ──────────────────────────────────────────────────────────────


def _profile_response(profile: dict) -> ProfileResponse:
    status = browser_mgr.get_status(profile["id"], profile)
    if not status.get("proxy_geo") and profile.get("proxy_geo"):
        status["proxy_geo"] = profile.get("proxy_geo")
    payload = {**profile, **status}
    payload["tags"] = [TagResponse(**tag) for tag in profile.get("tags", [])]
    return ProfileResponse(**payload)


@app.get("/api/profiles", response_model=list[ProfileResponse])
async def list_profiles():
    return [_profile_response(profile) for profile in db.list_profiles()]


@app.get("/api/profiles/trash", response_model=list[ProfileResponse])
async def list_deleted_profiles():
    return [_profile_response(profile) for profile in db.list_deleted_profiles()]


@app.post("/api/profiles", response_model=ProfileResponse, status_code=201)
async def create_profile(req: ProfileCreate):
    data = req.model_dump()
    tags = data.pop("tags", None)
    if tags:
        data["tags"] = [t.model_dump() if hasattr(t, "model_dump") else t for t in tags]
    else:
        data["tags"] = []
    return _profile_response(db.create_profile(**data))


@app.get("/api/profiles/{profile_id}", response_model=ProfileResponse)
async def get_profile(profile_id: str):
    profile = db.get_profile(profile_id)
    if not profile or profile.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Profile not found")
    return _profile_response(profile)


@app.put("/api/profiles/{profile_id}", response_model=ProfileResponse)
async def update_profile(profile_id: str, req: ProfileUpdate):
    # Only pass fields that were explicitly set
    data = req.model_dump(exclude_unset=True)
    tags = data.pop("tags", None)
    if tags is not None:
        data["tags"] = [t.model_dump() if hasattr(t, "model_dump") else t for t in tags]
    profile = db.update_profile(profile_id, **data)
    if not profile or profile.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Profile not found")
    return _profile_response(profile)


@app.delete("/api/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    # Stop browser if running
    if profile_id in browser_mgr.running:
        await browser_mgr.stop(profile_id)

    profile = db.get_profile(profile_id)
    if not profile or profile.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Profile not found")

    if not db.delete_profile(profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")

    return {"ok": True}


@app.post("/api/profiles/{profile_id}/restore", response_model=ProfileResponse)
async def restore_profile(profile_id: str):
    profile = db.restore_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _profile_response(profile)


@app.delete("/api/profiles/{profile_id}/purge")
async def purge_profile(profile_id: str):
    profile = db.get_profile(profile_id)
    if not profile or profile.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile_id in browser_mgr.running:
        await browser_mgr.stop(profile_id)

    user_data_dir = Path(profile["user_data_dir"])
    if not db.purge_profile(profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    if user_data_dir.exists():
        shutil.rmtree(user_data_dir, ignore_errors=True)
    return {"ok": True}


@app.get("/api/groups", response_model=list[GroupResponse])
async def list_groups():
    return [GroupResponse(**group) for group in db.list_groups()]


@app.post("/api/groups", response_model=GroupResponse, status_code=201)
async def create_group(req: GroupCreate):
    try:
        group = db.create_group(req.name.strip(), req.color)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GroupResponse(**group)


@app.delete("/api/groups/{group_id}")
async def delete_group(group_id: str):
    if not db.delete_group(group_id):
        raise HTTPException(status_code=404, detail="Group not found")
    return {"ok": True}


@app.get("/api/proxy-presets", response_model=list[ProxyPresetResponse])
async def list_proxy_presets():
    return [ProxyPresetResponse(**preset) for preset in db.list_proxy_presets()]


def _normalize_proxy_preset(raw_proxy: str, mode: str) -> str:
    raw = raw_proxy.strip()
    selected_mode = mode.strip().lower()
    if "://" in raw:
        return _normalize_proxy(raw)
    if selected_mode in {"http", "https", "socks5"}:
        parts = raw.split(":")
        if len(parts) == 4:
            host, port, user, passwd = parts
            return f"{selected_mode}://{user}:{passwd}@{host}:{port}"
        if len(parts) == 2:
            return f"{selected_mode}://{raw}"
    return _normalize_proxy(raw)


@app.post("/api/proxy-presets", response_model=ProxyPresetResponse, status_code=201)
async def create_proxy_preset(req: ProxyPresetCreate):
    proxy = _normalize_proxy_preset(req.proxy, req.mode)
    _validate_proxy(proxy)
    try:
        preset = db.create_proxy_preset(req.name.strip(), proxy, req.mode.strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProxyPresetResponse(**preset)


@app.post("/api/proxy-presets/bulk", response_model=list[ProxyPresetResponse], status_code=201)
async def create_proxy_presets_bulk(req: ProxyPresetBulkCreate):
    created: list[ProxyPresetResponse] = []
    for item in req.items:
        proxy = _normalize_proxy_preset(item.proxy, item.mode)
        _validate_proxy(proxy)
        try:
            preset = db.create_proxy_preset(item.name.strip(), proxy, item.mode.strip())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        created.append(ProxyPresetResponse(**preset))
    return created


@app.delete("/api/proxy-presets/{preset_id}")
async def delete_proxy_preset(preset_id: str):
    if not db.delete_proxy_preset(preset_id):
        raise HTTPException(status_code=404, detail="Proxy preset not found")
    return {"ok": True}


# ── Launch / Stop ─────────────────────────────────────────────────────────────


@app.get("/api/profiles/{profile_id}/preflight", response_model=PreflightResponse)
async def profile_preflight(profile_id: str, launch_mode: str = "manual"):
    profile = db.get_profile(profile_id)
    if not profile or profile.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Profile not found")
    mode = "debug" if launch_mode == "debug" else "manual"
    return PreflightResponse(**browser_mgr.preflight(profile, mode))


@app.post("/api/profiles/{profile_id}/launch", response_model=LaunchResponse)
async def launch_profile(
    profile_id: str,
    req: LaunchRequest | None = Body(default=None),
):
    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile_id in browser_mgr.running:
        raise HTTPException(status_code=409, detail="Profile is already running")

    try:
        preflight = browser_mgr.preflight(profile, req.launch_mode if req else "manual")
        if not preflight["can_launch"]:
            messages = "\n".join(issue["message"] for issue in preflight["issues"] if issue["severity"] == "error")
            raise HTTPException(status_code=409, detail=f"启动前检查未通过：{messages}")
        running = await browser_mgr.launch(
            profile,
            launch_mode=(req.launch_mode if req else "manual"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to launch profile %s: %s", profile_id, exc)
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=500, detail="Failed to launch browser")

    db.mark_profile_opened(profile_id, running.proxy_geo)

    return LaunchResponse(
        profile_id=profile_id,
        status="running",
        runtime_mode=browser_mgr.runtime.runtime_mode,
        viewer_mode=browser_mgr.runtime.viewer_mode,
        vnc_ws_port=running.ws_port,
        display=f":{running.display}" if running.display is not None else None,
        cdp_url=(
            f"/api/profiles/{profile_id}/cdp"
            if running.cdp_port is not None
            else None
        ),
        browser_engine=running.browser_engine,
        launch_mode=running.launch_mode,
    )


@app.post("/api/profiles/{profile_id}/stop")
async def stop_profile(profile_id: str):
    if profile_id not in browser_mgr.running:
        raise HTTPException(status_code=404, detail="Profile is not running")
    await browser_mgr.stop(profile_id)
    return {"ok": True}


@app.get("/api/profiles/{profile_id}/status", response_model=ProfileStatusResponse)
async def get_profile_status(profile_id: str):
    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    status = browser_mgr.get_status(profile_id, profile)
    return ProfileStatusResponse(**status)


@app.get("/api/profiles/{profile_id}/fingerprint-report")
async def get_fingerprint_report(profile_id: str):
    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile_id not in browser_mgr.running:
        raise HTTPException(status_code=409, detail="请先启动浏览器，再运行指纹自检")
    try:
        return await browser_mgr.fingerprint_report(profile)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Fingerprint report failed for %s: %s", profile_id, exc)
        raise HTTPException(status_code=500, detail="指纹自检失败") from exc


@app.post("/profile/{profile_id}/fingerprint-report", include_in_schema=False)
async def receive_passive_fingerprint_report(
    profile_id: str,
    raw: dict = Body(...),
):
    """Receive a same-origin report from a browser launched without CDP."""
    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile_id not in browser_mgr.running:
        raise HTTPException(status_code=409, detail="Profile is not running")
    try:
        return browser_mgr.record_fingerprint_report(profile, raw, collection="passive")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/profile/{profile_id}/start", response_class=HTMLResponse, include_in_schema=False)
async def profile_start_page(profile_id: str):
    """Show proxy and browser time details when a native profile opens."""
    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    running = browser_mgr.running.get(profile_id)
    geo = running.proxy_geo if running and running.proxy_geo else {}
    effective_timezone = (
        running.effective_timezone if running else None
    ) or profile.get("timezone") or geo.get("timezone") or "未设置"
    effective_locale = (
        running.effective_locale if running else None
    ) or profile.get("locale") or geo.get("suggested_locale") or "未设置"

    profile_name = html.escape(str(profile.get("name") or "未命名画像"))
    ip = html.escape(str(geo.get("ip") or "未获取"))
    location = html.escape(
        " / ".join(
            str(value)
            for value in (geo.get("country"), geo.get("region"), geo.get("city"))
            if value
        )
        or "地区信息未获取"
    )
    ip_timezone = html.escape(str(geo.get("timezone") or "未获取"))
    browser_timezone = html.escape(str(effective_timezone))
    browser_locale = html.escape(str(effective_locale))
    browser_engine = html.escape(
        str(running.browser_engine if running else profile.get("browser_engine") or "auto")
    )
    proxy_state = "已配置" if profile.get("proxy") else "未配置"
    status = "运行中" if running else "未启动"
    source = html.escape(str(geo.get("source") or "Manager"))
    diagnostic_script = DIAGNOSTIC_SCRIPT.strip()
    report_url = json.dumps(f"/profile/{profile_id}/fingerprint-report")

    return HTMLResponse(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{profile_name} · CloakBrowser 起始页</title>
  <style>
    :root {{
      color-scheme: dark;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #101417;
      color: #edf2f4;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-width: 320px;
      background: #101417;
    }}
    main {{ width: min(1120px, calc(100% - 40px)); margin: 0 auto; padding: 48px 0 64px; }}
    header {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 28px; }}
    .eyebrow {{ color: #76e4a3; font-size: 13px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }}
    h1 {{ margin: 8px 0 0; font-size: clamp(30px, 5vw, 56px); line-height: 1; }}
    .subtitle {{ margin: 12px 0 0; color: #9aa8ad; }}
    .status {{ border: 1px solid rgba(118, 228, 163, .32); border-radius: 999px; color: #76e4a3; padding: 8px 12px; white-space: nowrap; font-size: 13px; }}
    .hero, .panel {{ border: 1px solid #293338; background: #192023; border-radius: 10px; }}
    .hero {{ padding: 28px; margin-bottom: 16px; }}
    .label {{ color: #9aa8ad; font-size: 13px; }}
    .ip {{ margin: 8px 0; color: #76e4a3; font-size: clamp(34px, 7vw, 72px); font-weight: 750; }}
    .location {{ color: #dce5e8; font-size: 16px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
    .panel {{ padding: 20px; }}
    .panel h2 {{ margin: 0 0 16px; font-size: 16px; }}
    dl {{ display: grid; grid-template-columns: minmax(120px, .7fr) minmax(0, 1.3fr); gap: 12px 16px; margin: 0; }}
    dt {{ color: #8c9aa0; font-size: 13px; }}
    dd {{ margin: 0; color: #f2f6f7; overflow-wrap: anywhere; }}
    .muted {{ color: #8c9aa0; font-size: 12px; margin-top: 12px; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 24px; }}
    a {{ border: 1px solid #3a494f; border-radius: 7px; color: #dce5e8; padding: 10px 14px; text-decoration: none; font-size: 13px; }}
    a:hover {{ border-color: #76e4a3; color: #76e4a3; }}
    @media (max-width: 700px) {{
      main {{ width: min(100% - 24px, 1120px); padding-top: 28px; }}
      header {{ align-items: flex-start; flex-direction: column; }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <div class="eyebrow">CloakBrowser Manager</div>
        <h1>{profile_name}</h1>
        <p class="subtitle">启动信息页：先确认代理出口、浏览器时区和语言是否和代理地区一致。System 时区不会被修改。</p>
      </div>
      <div class="status">{html.escape(status)}</div>
    </header>

    <section class="hero">
      <div class="label">代理出口 IP</div>
      <div class="ip">{ip}</div>
      <div class="location">{location}</div>
      <div class="muted">IP 信息来源：{source}</div>
    </section>

    <div class="grid">
      <section class="panel">
        <h2>IP 地区与浏览器设置</h2>
        <dl>
          <dt>IP 时区</dt><dd>{ip_timezone}</dd>
          <dt>浏览器时区</dt><dd id="browser-timezone">{browser_timezone}</dd>
          <dt>浏览器语言</dt><dd id="browser-locale">{browser_locale}</dd>
          <dt>浏览器引擎</dt><dd>{browser_engine}</dd>
          <dt>代理状态</dt><dd>{proxy_state}</dd>
        </dl>
      </section>

      <section class="panel">
        <h2>当前浏览器实际信息</h2>
        <dl>
          <dt>浏览器时间</dt><dd id="browser-time">读取中...</dd>
          <dt>语言列表</dt><dd id="browser-languages">读取中...</dd>
          <dt>屏幕尺寸</dt><dd id="screen-size">读取中...</dd>
          <dt>页面视口</dt><dd id="viewport-size">读取中...</dd>
          <dt>设备像素比</dt><dd id="device-scale">读取中...</dd>
          <dt>启动自检</dt><dd id="fingerprint-check">采集中...</dd>
        </dl>
      </section>
    </div>

    <div class="actions">
      <a href="https://whoer.net/" target="_blank" rel="noreferrer">打开 Whoer 检查</a>
      <a href="https://pixelscan.net/fingerprint-check" target="_blank" rel="noreferrer">打开 Pixelscan 检查</a>
      <a href="/">返回 Manager</a>
    </div>
  </main>
  <script>
    const updateBrowserValues = () => {{
      document.querySelector("#browser-time").textContent = new Date().toString();
      document.querySelector("#browser-timezone").textContent =
        Intl.DateTimeFormat().resolvedOptions().timeZone || "未读取";
      document.querySelector("#browser-locale").textContent =
        navigator.language || "未读取";
      document.querySelector("#browser-languages").textContent =
        (navigator.languages || []).join(", ") || "未读取";
      document.querySelector("#screen-size").textContent =
        `${{screen.width}} × ${{screen.height}}`;
      document.querySelector("#viewport-size").textContent =
        `${{window.innerWidth}} × ${{window.innerHeight}}`;
      document.querySelector("#device-scale").textContent =
        String(window.devicePixelRatio || 1);
    }};
    updateBrowserValues();
    window.setInterval(updateBrowserValues, 1000);

    const collectFingerprint = {diagnostic_script};
    const submitFingerprintReport = async () => {{
      const statusNode = document.querySelector("#fingerprint-check");
      try {{
        const raw = await collectFingerprint();
        const response = await fetch({report_url}, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(raw),
        }});
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "自检提交失败");
        const analysis = result.analysis;
        statusNode.textContent = analysis.status === "pass"
          ? `通过 · ${{analysis.score}} 分`
          : `${{analysis.status === "fail" ? "未通过" : "有警告"}} · ${{analysis.score}} 分`;
        statusNode.style.color = analysis.status === "pass" ? "#76e4a3" : "#f6c177";
      }} catch (error) {{
        statusNode.textContent = `采集失败：${{String(error)}}`;
        statusNode.style.color = "#ff8a8a";
      }}
    }};
    void submitFingerprintReport();
  </script>
</body>
</html>"""
    )


# ── System Status ─────────────────────────────────────────────────────────────


@app.get("/api/status", response_model=StatusResponse)
async def get_system_status():
    try:
        from cloakbrowser.config import get_chromium_version

        binary_version = get_chromium_version()
    except ImportError:
        from cloakbrowser.config import CHROMIUM_VERSION

        binary_version = CHROMIUM_VERSION

    profiles = db.list_profiles()
    return StatusResponse(
        running_count=len(browser_mgr.running),
        binary_version=binary_version,
        profiles_total=len(profiles),
        host_os=browser_mgr.runtime.host_os,
        runtime_mode=browser_mgr.runtime.runtime_mode,
        viewer_mode=browser_mgr.runtime.viewer_mode,
    )


@app.post("/api/update", response_model=ManagerUpdateResponse)
async def update_manager():
    try:
        result = await asyncio.to_thread(update_from_git, PROJECT_ROOT)
        return ManagerUpdateResponse(**result.__dict__)
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Manager update failed")
        raise HTTPException(status_code=500, detail=f"升级失败：{exc}") from exc


@app.post("/api/browser/update", response_model=BrowserUpdateResponse)
async def update_browser_binary():
    """Check/download the official CloakBrowser binary for this platform."""
    try:
        import cloakbrowser
        from cloakbrowser.config import get_chromium_version

        before = get_chromium_version()
        latest = await asyncio.to_thread(cloakbrowser.check_for_update)
        after = get_chromium_version()
        platform = None
        try:
            from cloakbrowser.config import get_platform_tag
            platform = get_platform_tag()
        except (ImportError, AttributeError):
            pass
        wrapper = getattr(cloakbrowser, "__version__", None)
        if latest or after != before:
            message = f"CloakBrowser 内核已更新到 {after}，关闭运行中的浏览器后重新启动画像。"
        else:
            message = f"当前平台已经是可用的最新内核 {after}；免费渠道没有发现更高版本。"
        return BrowserUpdateResponse(
            ok=True,
            updated=bool(latest or after != before),
            wrapper_version=str(wrapper) if wrapper else None,
            current_version=before,
            available_version=after,
            platform=platform,
            restart_required=bool(latest or after != before),
            message=message,
        )
    except Exception as exc:
        logger.exception("CloakBrowser binary update failed")
        raise HTTPException(status_code=502, detail=f"浏览器内核检查失败：{exc}") from exc


@app.post("/api/proxy/test", response_model=ProxyTestResponse)
async def test_proxy(req: ProxyTestRequest):
    raw_proxy = req.proxy.strip()
    if not raw_proxy:
        raise HTTPException(status_code=400, detail="请先填写代理")

    try:
        proxy = _normalize_proxy(raw_proxy)
        _validate_proxy(proxy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"代理格式无效：{exc}") from exc

    xray_process = None
    proxy_bridge = None
    effective_proxy = proxy
    test_dir = db.DATA_DIR / "proxy-tests" / secrets.token_hex(8)
    try:
        if is_xray_link(proxy):
            xray_process = await start_xray_proxy(
                proxy,
                user_data_dir=test_dir,
                data_dir=browser_mgr.runtime.data_dir,
            )
            effective_proxy = xray_process.browser_proxy
        elif urlparse(proxy).scheme == "socks5" and (
            urlparse(proxy).username or urlparse(proxy).password
        ):
            proxy_bridge = HttpProxyBridge(proxy)
            effective_proxy = await proxy_bridge.start()
        data = await fetch_proxy_geo(effective_proxy)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"代理测试失败：{exc}") from exc
    finally:
        if proxy_bridge is not None:
            await proxy_bridge.close()
        if xray_process is not None:
            await xray_process.close()

    return ProxyTestResponse(**data)


# ── Clipboard Relay ──────────────────────────────────────────────────────────

_CLIPBOARD_MAX_READ = 1_048_576  # 1MB cap on GET response

# Track xclip processes per display so we can kill the old one before spawning new
_xclip_procs: dict[int, asyncio.subprocess.Process] = {}


@app.post("/api/profiles/{profile_id}/clipboard")
async def set_clipboard(profile_id: str, body: ClipboardRequest):
    """Push text into the VNC session's X clipboard via xclip."""
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")
    if browser_mgr.runtime.viewer_mode != "vnc" or running.display is None:
        raise HTTPException(
            status_code=409,
            detail="Clipboard relay is available only in Docker/VNC mode",
        )

    import os

    # Kill previous xclip for this display (it stays alive to serve paste)
    old = _xclip_procs.pop(running.display, None)
    if old and old.returncode is None:
        old.kill()
        await old.wait()

    env = {**os.environ, "DISPLAY": f":{running.display}"}
    proc = await asyncio.create_subprocess_exec(
        "xclip", "-selection", "clipboard",
        stdin=asyncio.subprocess.PIPE,
        env=env,
    )
    # xclip reads stdin then stays alive to serve paste requests.
    proc.stdin.write(body.text.encode())  # type: ignore[union-attr]
    await proc.stdin.drain()  # type: ignore[union-attr]
    proc.stdin.close()  # type: ignore[union-attr]

    _xclip_procs[running.display] = proc

    return {"ok": True}


@app.get("/api/profiles/{profile_id}/clipboard")
async def get_clipboard(profile_id: str):
    """Read the VNC session's clipboard.

    Chrome doesn't write to X11 clipboard under KasmVNC, so xclip can't read it.
    Instead, read via Playwright's CDP connection to Chrome (navigator.clipboard.readText).
    Falls back to xclip for non-Chrome clipboard owners.
    """
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")
    if browser_mgr.runtime.viewer_mode != "vnc" or running.display is None:
        raise HTTPException(
            status_code=409,
            detail="Clipboard relay is available only in Docker/VNC mode",
        )

    # Read Chrome's current text selection via Playwright.
    # Chrome's native copy (via VNC Ctrl+C) doesn't write to X11 clipboard
    # and doesn't fire DOM events, so we read the visible selection instead.
    # The init script also captures copy events when they do fire.
    # Check all pages — user may have copied in any tab
    try:
        for page in running.context.pages:
            try:
                text = await page.evaluate("window.__clipboardText || ''")
                if text:
                    return {"text": text[:_CLIPBOARD_MAX_READ]}
            except Exception as exc:
                logger.debug("Clipboard read failed on page: %s", exc)
                continue
    except Exception as exc:
        logger.debug("Playwright clipboard read failed: %s", exc)

    # Fallback: xclip for non-Chrome clipboard owners
    import os

    env = {**os.environ, "DISPLAY": f":{running.display}"}
    proc = await asyncio.create_subprocess_exec(
        "xclip", "-selection", "clipboard", "-o",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"text": ""}

    if proc.returncode != 0:
        return {"text": ""}

    text = stdout[:_CLIPBOARD_MAX_READ].decode("utf-8", errors="replace")
    return {"text": text}


# ── VNC WebSocket Proxy ──────────────────────────────────────────────────────


@app.websocket("/api/profiles/{profile_id}/vnc")
async def vnc_proxy(websocket: WebSocket, profile_id: str):
    """Proxy WebSocket frames between the frontend and a profile's KasmVNC."""
    if not await _check_websocket_origin(websocket):
        return

    running = browser_mgr.running.get(profile_id)
    if not running:
        await websocket.close(code=4004, reason="Profile not running")
        return
    if (
        browser_mgr.runtime.viewer_mode != "vnc"
        or running.display is None
        or running.ws_port is None
    ):
        await websocket.close(code=4005, reason="VNC unavailable in native-window mode")
        return

    # Accept with client's requested subprotocol (if any) — RFC 6455 requires
    # the server must not respond with a subprotocol the client didn't request.
    requested = websocket.scope.get("subprotocols", [])
    subprotocol = "binary" if "binary" in requested else None
    await websocket.accept(subprotocol=subprotocol)

    import websockets

    vnc_url = f"ws://127.0.0.1:{running.ws_port}/websockify"

    try:
        async with websockets.connect(
            vnc_url,
            subprotocols=["binary"],
            origin=f"http://127.0.0.1:{running.ws_port}",
            max_size=None,  # VNC frames can be large (1920x1080 framebuffer)
            ping_interval=None,  # KasmVNC doesn't respond to WS pings
            ping_timeout=None,
            compression=None,  # KasmVNC can't handle permessage-deflate
        ) as vnc_ws:
            logger.info(
                "VNC proxy: connected to KasmVNC for %s (subprotocol=%s)",
                profile_id, vnc_ws.subprotocol,
            )

            # noVNC v1.4 sends extension message types (150=ContinuousUpdates,
            # 248=QEMUKey, etc.) that KasmVNC 1.3.3 doesn't support, causing
            # "unknown message type" → disconnect.
            #
            # noVNC batches multiple RFB messages into a single WebSocket frame,
            # so we must parse the RFB stream to find message boundaries and strip
            # unsupported types before forwarding. Standard client→server types
            # have known fixed sizes (except SetEncodings and ClientCutText which
            # encode their length).

            async def client_to_vnc():
                count = 0
                handshake = 0  # first 3 messages are RFB handshake
                dropped = 0
                try:
                    while True:
                        msg = await websocket.receive()
                        msg_type = msg.get("type", "")
                        if msg_type == "websocket.disconnect":
                            logger.info("VNC proxy [c->v]: client disconnect (code=%s) after %d msgs (%d dropped)", msg.get("code"), count, dropped)
                            break
                        if "bytes" in msg and msg["bytes"]:
                            count += 1
                            data = msg["bytes"]
                            handshake += 1

                            # First 3 messages are RFB handshake — forward as-is
                            if handshake <= 3:
                                logger.debug("VNC handshake #%d: %d bytes hex=%s", handshake, len(data), data[:20].hex())
                                await vnc_ws.send(data)
                                continue

                            # Parse RFB messages and strip unsupported types
                            filtered = _filter_rfb_client_messages(data)
                            if filtered:
                                # Safety: verify first byte is a valid RFB client type
                                if filtered[0] not in _RFB_MSG_SIZE:
                                    logger.error("RFB SAFETY: refusing to send data with invalid first byte=%d hex=%s",
                                                 filtered[0], filtered[:20].hex())
                                    dropped += 1
                                    continue
                                logger.debug("VNC send: %d bytes first_type=%d hex=%s", len(filtered), filtered[0], filtered[:100].hex())
                                await vnc_ws.send(filtered)
                            else:
                                dropped += 1

                        elif "text" in msg and msg["text"]:
                            # noVNC only sends binary frames — text frames are unexpected
                            # and would bypass the RFB filter, so drop them.
                            count += 1
                            logger.warning("VNC proxy [c->v]: DROPPING text frame len=%d (noVNC should only send binary)", len(msg["text"]))
                            dropped += 1
                        else:
                            logger.warning("VNC proxy [c->v]: unhandled msg keys=%s type=%s", list(msg.keys()), msg_type)
                except WebSocketDisconnect as exc:
                    logger.info("VNC proxy [c->v]: WebSocketDisconnect code=%s after %d msgs (%d dropped)", exc.code, count, dropped)
                except Exception as exc:
                    logger.warning("VNC proxy [c->v]: %s: %s (after %d msgs)", type(exc).__name__, exc, count)

            async def vnc_to_client():
                count = 0
                try:
                    async for msg in vnc_ws:
                        count += 1
                        if isinstance(msg, bytes) and len(msg) > 0:
                            msg_type = msg[0]
                            if msg_type == 180:
                                # KasmVNC BinaryClipboard → convert to standard
                                # ServerCutText (type 3) so noVNC can handle it
                                text = _parse_kasmvnc_clipboard(msg)
                                if text:
                                    logger.info("VNC proxy [v->c]: clipboard %d chars", len(text))
                                    await websocket.send_bytes(_build_server_cut_text(text))
                                else:
                                    logger.info("VNC proxy [v->c]: dropped type 180 (no text/plain)")
                                continue
                            await websocket.send_bytes(msg)
                        elif isinstance(msg, bytes):
                            await websocket.send_bytes(msg)
                        else:
                            await websocket.send_text(msg)
                    logger.info("VNC proxy [v->c]: KasmVNC stream ended after %d msgs (close_code=%s)", count, vnc_ws.close_code)
                except WebSocketDisconnect as exc:
                    logger.info("VNC proxy [v->c]: client disconnect code=%s after %d msgs", exc.code, count)
                except Exception as exc:
                    logger.warning("VNC proxy [v->c]: %s: %s (after %d msgs)", type(exc).__name__, exc, count)

            c2v = asyncio.create_task(client_to_vnc(), name="c2v")
            v2c = asyncio.create_task(vnc_to_client(), name="v2c")

            done, pending = await asyncio.wait(
                [c2v, v2c],
                return_when=asyncio.FIRST_COMPLETED,
            )
            finished = [t.get_name() for t in done]
            still_running = [t.get_name() for t in pending]

            # Check if Xvnc is still alive
            vnc_instance = browser_mgr.vnc._allocated.get(running.display)
            xvnc_alive = vnc_instance and vnc_instance.process and vnc_instance.process.poll() is None
            logger.info(
                "VNC proxy: finished=%s pending=%s xvnc_alive=%s display=:%d for %s",
                finished, still_running, xvnc_alive, running.display, profile_id,
            )

            # Dump Xvnc log on disconnect
            import os
            xvnc_log = f"/tmp/xvnc-{running.display}.log"
            if os.path.exists(xvnc_log):
                with open(xvnc_log) as f:
                    log_content = f.read()
                if log_content.strip():
                    for line in log_content.strip().split("\n")[-20:]:
                        logger.info("Xvnc[:%d] %s", running.display, line)

            for task in pending:
                task.cancel()

    except Exception as exc:
        logger.error("VNC proxy connect error for %s: %s: %s", profile_id, type(exc).__name__, exc)
    finally:
        try:
            await websocket.close()
        except Exception as exc:
            logger.debug("VNC proxy: websocket.close() failed: %s", exc)


# ── CDP WebSocket Proxy ──────────────────────────────────────────────────────
# Simple bidirectional passthrough — CDP is standard JSON over WebSocket,
# no protocol translation needed (unlike VNC which requires RFB filtering).


@app.get("/api/profiles/{profile_id}/cdp")
async def cdp_info(profile_id: str):
    """Return CDP connection info. Prevents SPA catch-all from serving index.html."""
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")
    if running.cdp_port is None:
        raise HTTPException(status_code=409, detail="CDP unavailable in manual launch mode")
    return {
        "cdp_url": f"/api/profiles/{profile_id}/cdp",
        "usage": "playwright.chromium.connect_over_cdp('http://<host>/api/profiles/"
        + profile_id + "/cdp')",
    }


@app.get("/api/profiles/{profile_id}/cdp/json/version/")
@app.get("/api/profiles/{profile_id}/cdp/json/version")
async def cdp_json_version(profile_id: str, request: Request):
    """Proxy Chrome's /json/version, rewriting WS URLs to go through our proxy."""
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")
    if running.cdp_port is None:
        raise HTTPException(status_code=409, detail="CDP unavailable in manual launch mode")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{running.cdp_port}/json/version", timeout=5
            )
            data = resp.json()
    except Exception as exc:
        logger.error("CDP proxy: failed to reach Chrome CDP for %s: %s", profile_id, exc)
        raise HTTPException(status_code=502, detail="CDP endpoint unreachable")

    # Rewrite webSocketDebuggerUrl to point through our proxy
    host = request.headers.get("host", "localhost:8080")
    ws_scheme = "wss" if _is_https(request) else "ws"
    data["webSocketDebuggerUrl"] = f"{ws_scheme}://{host}/api/profiles/{profile_id}/cdp"
    return data


@app.get("/api/profiles/{profile_id}/cdp/json/list/")
@app.get("/api/profiles/{profile_id}/cdp/json/list")
@app.get("/api/profiles/{profile_id}/cdp/json/")
@app.get("/api/profiles/{profile_id}/cdp/json")
async def cdp_json_list(profile_id: str, request: Request):
    """Proxy Chrome's /json/list, rewriting WS URLs."""
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")
    if running.cdp_port is None:
        raise HTTPException(status_code=409, detail="CDP unavailable in manual launch mode")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{running.cdp_port}/json/list", timeout=5
            )
            data = resp.json()
    except Exception as exc:
        logger.error("CDP proxy: failed to reach Chrome CDP for %s: %s", profile_id, exc)
        raise HTTPException(status_code=502, detail="CDP endpoint unreachable")

    host = request.headers.get("host", "localhost:8080")
    ws_scheme = "wss" if _is_https(request) else "ws"
    for entry in data:
        if "webSocketDebuggerUrl" in entry:
            ws_path = entry["webSocketDebuggerUrl"].split("/devtools/")[-1]
            entry["webSocketDebuggerUrl"] = (
                f"{ws_scheme}://{host}/api/profiles/{profile_id}/cdp/devtools/{ws_path}"
            )
    return data


async def _proxy_cdp_websocket(
    websocket: WebSocket, target_url: str, label: str,
) -> None:
    """Bidirectional WebSocket proxy between a FastAPI client and a CDP target.

    Used by both browser-level and page-level CDP proxy endpoints.
    """
    import websockets

    try:
        async with websockets.connect(
            target_url, max_size=None, ping_interval=None, ping_timeout=None
        ) as cdp_ws:
            logger.info("%s: connected to %s", label, target_url)

            async def client_to_cdp():
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if "text" in msg and msg["text"]:
                            await cdp_ws.send(msg["text"])
                        elif "bytes" in msg and msg["bytes"]:
                            await cdp_ws.send(msg["bytes"])
                except WebSocketDisconnect:
                    pass
                except Exception as exc:
                    logger.warning("%s [c->cdp]: %s: %s", label, type(exc).__name__, exc)

            async def cdp_to_client():
                try:
                    async for msg in cdp_ws:
                        if isinstance(msg, str):
                            await websocket.send_text(msg)
                        else:
                            await websocket.send_bytes(msg)
                except WebSocketDisconnect:
                    pass
                except Exception as exc:
                    logger.warning("%s [cdp->c]: %s: %s", label, type(exc).__name__, exc)

            c2d = asyncio.create_task(client_to_cdp(), name="c2d")
            d2c = asyncio.create_task(cdp_to_client(), name="d2c")
            done, pending = await asyncio.wait(
                [c2d, d2c], return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            logger.info("%s: disconnected", label)

    except Exception as exc:
        logger.error("%s error: %s", label, exc)
    finally:
        try:
            await websocket.close()
        except Exception as exc:
            logger.debug("%s: websocket.close() failed: %s", label, exc)


@app.websocket("/api/profiles/{profile_id}/cdp")
async def cdp_proxy(websocket: WebSocket, profile_id: str):
    """Proxy WebSocket frames between external tools and Chrome's CDP."""
    if not await _check_websocket_origin(websocket):
        return

    running = browser_mgr.running.get(profile_id)
    if not running:
        await websocket.close(code=4004, reason="Profile not running")
        return
    if running.cdp_port is None:
        await websocket.close(code=4005, reason="CDP unavailable in manual launch mode")
        return

    await websocket.accept()

    # Get browser-level CDP WebSocket URL from Chrome
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{running.cdp_port}/json/version", timeout=5
            )
            ws_url = resp.json()["webSocketDebuggerUrl"]
    except Exception as exc:
        logger.error("CDP proxy: failed to get WS URL for %s: %s", profile_id, exc)
        await websocket.close(code=4005, reason="CDP not available")
        return

    await _proxy_cdp_websocket(websocket, ws_url, f"CDP proxy [{profile_id}]")


@app.websocket("/api/profiles/{profile_id}/cdp/devtools/{path:path}")
async def cdp_page_proxy(websocket: WebSocket, profile_id: str, path: str):
    """Proxy page-specific CDP WebSocket connections (e.g. /devtools/page/GUID)."""
    if not await _check_websocket_origin(websocket):
        return

    running = browser_mgr.running.get(profile_id)
    if not running:
        await websocket.close(code=4004, reason="Profile not running")
        return
    if running.cdp_port is None:
        await websocket.close(code=4005, reason="CDP unavailable in manual launch mode")
        return

    await websocket.accept()

    target_url = f"ws://127.0.0.1:{running.cdp_port}/devtools/{path}"
    await _proxy_cdp_websocket(websocket, target_url, f"CDP page proxy [{profile_id}]")


# ── Static Frontend ───────────────────────────────────────────────────────────

# Serve React build. Must be AFTER API routes so /api/* isn't caught by the SPA.
if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve React SPA — all non-API routes return index.html."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        file_path = FRONTEND_DIR / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")
