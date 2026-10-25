"""The Manager's agent surface: tool API, HTTP MCP, leases, page control, tokens.

Everything here is SDK-free except the optional HTTP MCP endpoint, which is
skipped (with a log line) when the ``mcp`` package is not installed, so the
panel runs unchanged without it.

Endpoints
---------
* ``GET  /api/agent/tools``            tools visible to the caller (raw / OpenAI / Anthropic format)
* ``POST /api/agent/tools/{name}``     run one tool; the same gate, field policy and audit as MCP
* ``GET  /api/agent/guide``            the agent usage guide (markdown)
* ``/api/agent/mcp``                   streamable-HTTP MCP endpoint (same tools)
* ``/api/agent/tokens``                admin only: mint / list / revoke scoped agent tokens
* ``/api/profiles/{id}/lease``         who is driving a profile; ``/takeover`` is the person's override
* ``POST /api/profiles/{id}/page/{action}``  page control over the profile's Playwright context

Tool calls run through an in-process client (ASGI transport) carrying a
per-process internal token, so they work whichever authentication the Manager
has, while a *caller's* agent-token scope still caps what the tools may do.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from dataclasses import dataclass
from typing import Any, Callable

import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import agent_lease
from .agent_auth import SCOPES, TokenStore, clamp_mode
from .agent_tools import (
    SERVER_NAME,
    TOOLS,
    LocalBackend,
    RestClient,
    dispatch,
    guide_text,
    tool_specs,
)
from .page_control import PageController, PageControlError
from .runtime import server_port

logger = logging.getLogger("cloakbrowser.manager.agent")

_REASON_STATUS = {
    "invalid_argument": 400,
    "unknown_ref": 409,
    "stale_ref": 409,
    "no_page": 409,
    "page_navigating": 409,
    "timeout": 504,
    "navigation_failed": 502,
    "action_failed": 502,
}


class CdpConnections:
    """Live CDP proxy sockets per profile, so a takeover can cut them off."""

    def __init__(self) -> None:
        self._conns: dict[str, set[Any]] = {}

    def add(self, profile_id: str, websocket: Any) -> None:
        self._conns.setdefault(profile_id, set()).add(websocket)

    def remove(self, profile_id: str, websocket: Any) -> None:
        conns = self._conns.get(profile_id)
        if conns is not None:
            conns.discard(websocket)
            if not conns:
                del self._conns[profile_id]

    async def close_all(self, profile_id: str, code: int = 4010, reason: str = "Taken over by user") -> int:
        closed = 0
        for websocket in list(self._conns.get(profile_id, ())):
            try:
                await websocket.close(code=code, reason=reason)
                closed += 1
            except Exception as exc:  # already gone
                logger.debug("closing CDP socket for %s: %s", profile_id, exc)
        return closed


@dataclass
class AgentDeps:
    app: Any
    browser_mgr: Any
    get_profile: Callable[[str], dict | None]
    get_mode: Callable[[], str]
    token_store: TokenStore
    leases: agent_lease.LeaseRegistry
    pages: PageController
    cdp: CdpConnections
    internal_token: str
    auth_required: Callable[[], bool]


def agent_scope_of(scope_or_request: Any) -> tuple[str | None, str | None]:
    """(token scope, token name) of the agent token a request authenticated with."""
    scope = getattr(scope_or_request, "scope", scope_or_request)
    state = scope.get("state") or {}
    return state.get("agent_scope"), state.get("agent_name")


def _public_base(headers: Any) -> str:
    host = headers.get("host") or f"127.0.0.1:{server_port()}"
    scheme = "https" if "https" in (headers.get("x-forwarded-proto") or "") else "http"
    return f"{scheme}://{host}"


def inproc_client(deps: AgentDeps, headers: Any) -> RestClient:
    return RestClient(
        f"http://127.0.0.1:{server_port()}",
        transport=httpx.ASGITransport(app=deps.app),
        token=deps.internal_token if deps.auth_required() else "",
        public_base_url=_public_base(headers),
    )


class LeaseRequest(BaseModel):
    holder: str = Field(min_length=1, max_length=120)
    ttl_seconds: int | None = Field(default=None, ge=1, le=agent_lease.MAX_TTL_S)


class TakeoverRequest(BaseModel):
    ttl_seconds: int = Field(default=agent_lease.HUMAN_TTL_S, ge=1, le=agent_lease.MAX_TTL_S)


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    client: dict[str, Any] | None = None
    holder: str | None = Field(default=None, max_length=120)


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: str


def create_router(deps: AgentDeps) -> APIRouter:
    router = APIRouter()

    def _profile_or_404(profile_id: str) -> dict:
        profile = deps.get_profile(profile_id)
        if not profile or profile.get("deleted_at"):
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile

    # ── leases ─────────────────────────────────────────────────────────────

    @router.get("/api/profiles/{profile_id}/lease")
    async def get_lease(profile_id: str):
        _profile_or_404(profile_id)
        return {"lease": deps.leases.describe(profile_id)}

    @router.post("/api/profiles/{profile_id}/lease")
    async def acquire_lease(profile_id: str, body: LeaseRequest):
        _profile_or_404(profile_id)
        ok, lease = deps.leases.acquire(
            profile_id, body.holder, body.ttl_seconds or agent_lease.DEFAULT_TTL_S
        )
        described = deps.leases.describe(profile_id)
        if not ok:
            who = "用户" if lease.kind == agent_lease.KIND_HUMAN else lease.holder
            return JSONResponse(
                {
                    "detail": f"[profile_leased] 画像正被 {who} 控制（还剩约 {described['seconds_left']} 秒）。",
                    "lease": described,
                },
                status_code=409,
            )
        return {"ok": True, "lease": described}

    @router.delete("/api/profiles/{profile_id}/lease")
    async def release_lease(profile_id: str, holder: str | None = Query(default=None)):
        """``holder`` given: that holder lets go. Omitted: the person hands the profile back."""
        _profile_or_404(profile_id)
        return {"released": deps.leases.release(profile_id, holder)}

    @router.post("/api/profiles/{profile_id}/lease/takeover")
    async def takeover_lease(profile_id: str, body: TakeoverRequest | None = Body(default=None)):
        """The person takes over: park the lease on ``human`` and cut live CDP sockets."""
        _profile_or_404(profile_id)
        ttl = body.ttl_seconds if body else agent_lease.HUMAN_TTL_S
        deps.leases.takeover(profile_id, ttl)
        closed = await deps.cdp.close_all(profile_id)
        return {"lease": deps.leases.describe(profile_id), "cdp_connections_closed": closed}

    # ── page control ───────────────────────────────────────────────────────

    @router.post("/api/profiles/{profile_id}/page/{action}")
    async def page_action(profile_id: str, action: str, body: dict[str, Any] = Body(default_factory=dict)):
        def fail(status: int, reason: str, detail: str):
            return JSONResponse({"ok": False, "reason": reason, "detail": detail}, status_code=status)

        _profile_or_404(profile_id)
        running = deps.browser_mgr.running.get(profile_id)
        if running is None:
            return fail(404, "not_running", "这个画像没在运行。先 open_browser。")
        context = getattr(running, "context", None)
        if context is None or getattr(running, "cdp_port", None) is None:
            return fail(409, "cdp_unavailable", "这个画像是 manual 模式启动的，页面控制不可用。stop 后用 open_browser 重新启动。")
        pages = deps.pages
        try:
            if action == "navigate":
                result = await pages.navigate(context, profile_id, str(body.get("url") or ""))
            elif action == "snapshot":
                result = await pages.snapshot(context, profile_id, viewport_only=bool(body.get("viewport_only")))
            elif action == "get_text":
                result = await pages.get_text(
                    context, profile_id, ref=body.get("ref") or None,
                    offset=int(body.get("offset") or 0), max_chars=int(body.get("max_chars") or 6000),
                    whole_page=bool(body.get("whole_page")),
                )
            elif action == "click":
                result = await pages.click(context, profile_id, str(body.get("ref") or ""))
            elif action == "type":
                result = await pages.type_text(
                    context, profile_id, str(body.get("ref") or ""), body.get("text"), submit=bool(body.get("submit"))
                )
            elif action == "press_key":
                result = await pages.press_key(context, profile_id, str(body.get("key") or ""))
            elif action == "scroll":
                result = await pages.scroll(
                    context, profile_id, str(body.get("direction") or "down"), int(body.get("amount") or 600)
                )
            elif action == "screenshot":
                result = await pages.screenshot(
                    context, profile_id,
                    full_page=bool(body.get("full_page")), fmt=str(body.get("format") or "jpeg"),
                )
            elif action == "wait_for":
                result = await pages.wait_for(
                    context, profile_id, text=body.get("text") or None,
                    ms=int(body["ms"]) if body.get("ms") is not None else None,
                )
            elif action == "back":
                result = await pages.back(context, profile_id)
            elif action == "tabs":
                result = await pages.tabs(
                    context, profile_id, str(body.get("action") or "list"),
                    index=body.get("index"), url=body.get("url"),
                )
            else:
                return fail(404, "not_found", f"没有这个页面动作：{action}")
        except PageControlError as exc:
            return fail(_REASON_STATUS.get(exc.reason, 409), exc.reason, exc.detail)
        except (TypeError, ValueError) as exc:
            return fail(400, "invalid_argument", f"参数不合法：{exc}")
        return result

    # ── tool API ───────────────────────────────────────────────────────────

    @router.get("/api/agent/tools")
    async def list_tools(request: Request, format: str = Query(default="raw", pattern="^(raw|openai|anthropic)$")):
        scope, _ = agent_scope_of(request)
        mode = clamp_mode(deps.get_mode(), scope)
        return {"mode": mode, "scope": scope, "tools": tool_specs(mode, scope, fmt=format)}

    @router.post("/api/agent/tools/{name}")
    async def call_tool(name: str, request: Request, body: ToolCallRequest | None = Body(default=None)):
        body = body or ToolCallRequest()
        scope, token_name = agent_scope_of(request)
        if name not in TOOLS:
            return JSONResponse(
                {"ok": False, "reason": "unknown_tool", "detail": f"没有这个工具：{name}"}, status_code=404
            )
        client_info = body.client or {}
        client_name = client_info.get("name") or token_name or "rest"
        holder = body.holder or (f"{token_name}:{client_name}" if token_name else None)
        result = await dispatch(
            inproc_client(deps, request.headers),
            name,
            body.arguments,
            client_name=str(client_name),
            client_version=client_info.get("version"),
            token_scope=scope,
            holder=holder,
        )
        return result

    @router.get("/api/agent/guide", response_class=PlainTextResponse)
    async def guide():
        return guide_text()

    # ── agent tokens (administrator only) ──────────────────────────────────

    def _admin_only(request: Request) -> None:
        if agent_scope_of(request)[0] is not None:
            raise HTTPException(status_code=403, detail="agent token 不能管理 agent token")

    @router.get("/api/agent/tokens")
    async def list_tokens(request: Request):
        _admin_only(request)
        return {"enforced": deps.auth_required(), "scopes": list(SCOPES), "tokens": deps.token_store.list()}

    @router.post("/api/agent/tokens", status_code=201)
    async def create_token(request: Request, body: TokenCreate):
        _admin_only(request)
        try:
            record, token = deps.token_store.create(body.name, body.scope)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "token": token,
            "record": record,
            "enforced": deps.auth_required(),
            "note": "token 只显示这一次，请立刻保存。Manager 没开鉴权时 token 不会被检查。",
        }

    @router.delete("/api/agent/tokens/{token_id}")
    async def revoke_token(request: Request, token_id: str):
        _admin_only(request)
        if not deps.token_store.revoke(token_id):
            raise HTTPException(status_code=404, detail="Token not found")
        return {"ok": True}

    return router


# ── Streamable-HTTP MCP endpoint ─────────────────────────────────────────────


class HttpMcp:
    """The Manager's MCP-over-HTTP endpoint.

    ``run()`` must be entered for the app's lifetime (see ``lifespan`` in
    main.py). The SDK's session manager can only run once per instance, so
    each ``run()`` builds a fresh one; the app may start more than once in a
    process (tests do).
    """

    def __init__(self, make_manager: Callable[[], Any], make_endpoint: Callable[["HttpMcp"], Any]) -> None:
        self._make_manager = make_manager
        self.manager: Any = None
        self.endpoint = make_endpoint(self)

    @contextlib.asynccontextmanager
    async def run(self):
        manager = self._make_manager()
        async with manager.run():
            self.manager = manager
            try:
                yield
            finally:
                self.manager = None


def build_http_mcp(deps: AgentDeps) -> HttpMcp | None:
    try:
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.transport_security import TransportSecuritySettings
        from starlette.datastructures import Headers

        from . import mcp_server
    except ImportError as exc:
        logger.info("HTTP MCP endpoint disabled (mcp SDK not installed): %s", exc)
        return None

    request_info: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
        "agent_http_request", default=None
    )

    def backend() -> LocalBackend:
        info = request_info.get()
        if info is None:
            raise RuntimeError("HTTP MCP call outside a request")
        return LocalBackend(info["client"], token_scope=info["scope"], holder=info["holder"])

    server = mcp_server.build_server(backend)

    def make_manager() -> Any:
        return StreamableHTTPSessionManager(
            app=server,
            json_response=True,
            stateless=True,
            # The Manager's request guard already checks Host/Origin for every route.
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )

    def make_endpoint(http_mcp: HttpMcp) -> Any:
        class Endpoint:
            async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                manager = http_mcp.manager
                if manager is None:
                    response = JSONResponse({"detail": "HTTP MCP is not running"}, status_code=503)
                    await response(scope, receive, send)
                    return
                headers = Headers(scope=scope)
                token_scope, token_name = agent_scope_of(scope)
                agent_id = headers.get("x-agent-id")
                holder = agent_id or (f"{token_name}:http" if token_name else "http-mcp")
                reset = request_info.set(
                    {"client": inproc_client(deps, headers), "scope": token_scope, "holder": holder}
                )
                try:
                    await manager.handle_request(scope, receive, send)
                finally:
                    request_info.reset(reset)

        return Endpoint()

    return HttpMcp(make_manager, make_endpoint)


def install(app: Any, deps: AgentDeps) -> HttpMcp | None:
    """Register the agent routes (and the HTTP MCP endpoint when available)."""
    app.include_router(create_router(deps))
    http_mcp = build_http_mcp(deps)
    if http_mcp is not None:
        app.add_route("/api/agent/mcp", http_mcp.endpoint, methods=["GET", "POST", "DELETE"])
    return http_mcp


__all__ = ["AgentDeps", "CdpConnections", "HttpMcp", "install", "SERVER_NAME"]
