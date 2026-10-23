"""Stdio MCP bridge: let an MCP client (Claude Desktop / Muse) drive
the local Manager through its existing REST API.

Design (see MCP-PLAN.md):

* This process is launched by the user's own MCP client and speaks MCP over
  stdio. It adds no listening port; every tool call is translated into a
  request to ``http://127.0.0.1:{server_port()}/api/...``.
* Tools are layered. The 14 read tools are always available unless the mode
  is ``off``; the 5 action tools (launch / stop / site-check / warm-up /
  evolution) only register when the Manager setting ``mcp.mode`` is ``full``
  (default ``read-only``). Destructive operations, proposal approvals and
  anything Cookie-shaped are not tools at all — by construction.
* Field policy: profile payloads are rebuilt from an allowlist, proxies are
  reduced to ``scheme://host:port`` (credentials stripped), and the user's
  free-text fields (``notes`` / ``warmup_persona``) plus ``cookies_json``
  never leave the Manager. The license key value does not exist in any REST
  response, so it cannot appear here either.
* Every dispatched call is reported to ``POST /api/mcp/audit`` with a
  redacted argument summary (best effort: when the Manager is unreachable
  the call itself already failed, so there is nothing unrecorded).

This is the only module that imports the ``mcp`` SDK; the FastAPI app never
does, so the panel runs unchanged where the SDK is not installed.

Run with: ``python -m backend.mcp_server`` (Manager must be running).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .linkability import parse_proxy_endpoint
from .runtime import server_port

SERVER_NAME = "cloakbrowser-manager"

MODE_OFF = "off"
MODE_READ_ONLY = "read-only"
MODE_FULL = "full"
_MODES = (MODE_OFF, MODE_READ_ONLY, MODE_FULL)

READ_TIMEOUT_S = 30.0
ACTION_TIMEOUT_S = 180.0  # browser launches take a while

# Mirrors backend/evolution.py's seat markers (kept in sync deliberately:
# the bridge stays import-light and never pulls the automation modules in).
_SEAT_MARKERS = ("session limit", "seat", "license", "licence", "并发", "授权", "concurren")
_RUNNING_MARKERS = ("already running", "正在运行", "请先关闭")
# Same-automation 409 phrasings -> the automation that is busy.
_BUSY_OWNERS = (
    ("已经有一个检测", "site_check"),
    ("已经有一个画像在养号", "warmup"),
    ("已经有一个进化周期", "evolution"),
)
_AUTOMATION_DETAIL_RE = re.compile(r"另一个自动化[（(]([^）)]+)[）)]")


class ManagerUnreachable(Exception):
    """The Manager's REST API could not be reached at all."""


# ── REST client ──────────────────────────────────────────────────────────────


class RestClient:
    """Thin httpx wrapper over the Manager's own REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        token: str | None = None,
    ) -> None:
        self.base_url = (base_url or f"http://127.0.0.1:{server_port()}").rstrip("/")
        # Same Bearer the Manager itself uses (main.py AUTH_TOKEN); the MCP
        # client config carries it in this process's env when auth is on.
        self._token = os.environ.get("AUTH_TOKEN", "") if token is None else token
        self._transport = transport

    def _new_client(self, timeout: float) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            transport=self._transport,
            timeout=timeout,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        timeout: float = READ_TIMEOUT_S,
    ) -> tuple[int, Any]:
        try:
            async with self._new_client(timeout) as client:
                resp = await client.request(method, path, json=json_body)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ManagerUnreachable(f"连不上 Manager（{self.base_url}）：{exc}") from exc
        except httpx.TimeoutException as exc:
            raise ManagerUnreachable(f"Manager 响应超时（{path}）：{exc}") from exc
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, None

    async def get(self, path: str, *, timeout: float = READ_TIMEOUT_S) -> tuple[int, Any]:
        return await self.request("GET", path, timeout=timeout)

    async def post(
        self, path: str, *, json_body: dict | None = None, timeout: float = READ_TIMEOUT_S
    ) -> tuple[int, Any]:
        return await self.request("POST", path, json_body=json_body, timeout=timeout)


# ── Structured error mapping ─────────────────────────────────────────────────


def _detail_of(payload: Any) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return json.dumps(detail, ensure_ascii=False)[:300]
    return ""


def automation_owner_from_detail(detail: str) -> str | None:
    match = _AUTOMATION_DETAIL_RE.search(detail or "")
    return match.group(1) if match else None


def is_seat_error_text(detail: str | None) -> bool:
    text = (detail or "").lower()
    return any(marker in text for marker in _SEAT_MARKERS)


def error_result(status: int, payload: Any, *, tool: str = "") -> dict[str, Any]:
    """Map a REST error onto the bridge's structured result vocabulary."""
    detail = _detail_of(payload)
    if status == 404:
        # stop on a stopped profile is a domain answer, not a missing route.
        if tool == "stop_profile" and "not running" in detail.lower():
            return {"ok": False, "reason": "not_running", "detail": detail}
        return {"ok": False, "reason": "not_found", "detail": detail}
    if status == 409:
        owner = automation_owner_from_detail(detail)
        if owner:
            return {"ok": False, "reason": "automation_busy", "owner": owner, "detail": detail}
        for marker, kind in _BUSY_OWNERS:
            if marker in detail:
                return {"ok": False, "reason": "automation_busy", "owner": kind, "detail": detail}
        if is_seat_error_text(detail):
            return {"ok": False, "reason": "seat_busy", "detail": detail}
        if any(marker in detail.lower() or marker in detail for marker in _RUNNING_MARKERS):
            return {"ok": False, "reason": "already_running", "detail": detail}
        return {"ok": False, "reason": "conflict", "detail": detail}
    return {"ok": False, "reason": "manager_error", "status": status, "detail": detail}


def unreachable_result(exc: ManagerUnreachable) -> dict[str, Any]:
    return {"ok": False, "reason": "manager_unreachable", "detail": str(exc)}


# ── Field policy (MCP-PLAN §3) ───────────────────────────────────────────────


def sanitize_proxy(proxy: Any) -> str | None:
    """scheme://host:port with credentials stripped; opaque share links
    (whose stored string itself encodes secrets) collapse to a marker."""
    if not proxy:
        return None
    endpoint = parse_proxy_endpoint(str(proxy))
    return endpoint if endpoint else "configured"


# Profile fields an agent may see. Everything else on ProfileResponse is
# excluded on purpose: notes / warmup_persona (user free text), cookies_json
# (cookie values), cdp_url / vnc_ws_port / user_data_dir / proxy_geo (local
# access paths and exit-IP details the agent does not need).
PROFILE_FIELDS = (
    "id", "name", "browser_engine", "device_profile", "fingerprint_seed",
    "timezone", "locale", "platform", "user_agent",
    "screen_width", "screen_height", "gpu_vendor", "gpu_renderer",
    "hardware_concurrency", "device_memory",
    "humanize", "human_preset", "headless", "geoip", "clipboard_sync",
    "auto_launch", "color_scheme", "group_name", "account_platform",
    "startup_urls", "launch_args", "fingerprint_options", "disposable",
    "warmup_enabled", "warmup_daily_max", "warmup_targets",
    "evolution_enabled", "evolution_interval_hours",
    "status", "runtime_mode", "viewer_mode",
    "created_at", "updated_at", "last_opened_at", "tags",
)


def shape_profile(profile: dict[str, Any]) -> dict[str, Any]:
    shaped = {key: profile.get(key) for key in PROFILE_FIELDS if key in profile}
    shaped["proxy"] = sanitize_proxy(profile.get("proxy"))
    return shaped


_PRIVATE_ARG_KEYS = {"notes", "persona", "warmup_persona"}


def summarize_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """Redacted argument summary for the audit log (MCP-PLAN §4): private
    free-text fields are recorded as presence+length only, proxy values as
    scheme://host:port, long strings truncated to their length."""
    summary: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if key in _PRIVATE_ARG_KEYS:
            summary[key] = {"present": value is not None, "length": len(str(value))}
        elif key == "proxy" and isinstance(value, str):
            summary[key] = sanitize_proxy(value)
        elif isinstance(value, str) and len(value) > 80:
            summary[key] = {"truncated": True, "length": len(value)}
        elif isinstance(value, (str, int, float, bool)) or value is None:
            summary[key] = value
        elif isinstance(value, list):
            summary[key] = {"count": len(value)}
        elif isinstance(value, dict):
            summary[key] = {"keys": sorted(str(k) for k in value)[:10]}
        else:
            summary[key] = type(value).__name__
    return summary


# ── Tool registry ────────────────────────────────────────────────────────────

Handler = Callable[[RestClient, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    layer: str  # "read" | "action"
    handler: Handler


TOOLS: dict[str, ToolDef] = {}


def register(name: str, description: str, input_schema: dict[str, Any], layer: str) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        TOOLS[name] = ToolDef(name, description, input_schema, layer, fn)
        return fn

    return decorator


NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}}
PROFILE_ID_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {"profile_id": {"type": "string", "description": "画像 id（先用 list_profiles 查）"}},
    "required": ["profile_id"],
}


def visible_tools(mode: str) -> list[ToolDef]:
    if mode == MODE_OFF:
        return []
    if mode == MODE_FULL:
        return list(TOOLS.values())
    return [tool for tool in TOOLS.values() if tool.layer == "read"]


def build_mcp_tools(mode: str) -> list[types.Tool]:
    return [
        types.Tool(name=tool.name, description=tool.description, input_schema=tool.input_schema)
        for tool in visible_tools(mode)
    ]


# ── Mode gate + dispatch + audit ─────────────────────────────────────────────


async def fetch_mode(client: RestClient) -> str:
    """Current mcp.mode from the Manager; conservative default when the
    endpoint is missing (older Manager) — read-only, never full."""
    status, payload = await client.get("/api/settings/mcp", timeout=5.0)
    if status == 200 and isinstance(payload, dict):
        mode = payload.get("mode")
        if mode in _MODES:
            return str(mode)
    return MODE_READ_ONLY


async def _report_audit(
    client: RestClient,
    *,
    tool: str,
    args: dict[str, Any],
    result: dict[str, Any],
    duration_ms: int,
    client_name: str | None,
    client_version: str | None,
) -> None:
    try:
        await client.post(
            "/api/mcp/audit",
            json_body={
                "client_name": client_name,
                "client_version": client_version,
                "tool": tool,
                "args_summary": summarize_args(args),
                "ok": bool(result.get("ok")),
                "reason": result.get("reason"),
                "duration_ms": duration_ms,
            },
            timeout=5.0,
        )
    except Exception:
        # Best effort only: when the Manager is down the tool call itself
        # already failed, so no work can have happened unrecorded.
        pass


async def dispatch(
    client: RestClient,
    name: str,
    arguments: dict[str, Any] | None,
    *,
    client_name: str | None = None,
    client_version: str | None = None,
) -> dict[str, Any]:
    """Run one tool call through the mode gate and audit trail."""
    args = arguments or {}
    started = time.monotonic()
    tool = TOOLS.get(name)
    if tool is None:
        result: dict[str, Any] = {"ok": False, "reason": "unknown_tool", "detail": f"没有这个工具：{name}"}
    else:
        try:
            mode = await fetch_mode(client)
        except ManagerUnreachable as exc:
            result = unreachable_result(exc)
            mode = None
        if tool is not None and mode is not None:
            if mode == MODE_OFF:
                result = {
                    "ok": False,
                    "reason": "mcp_disabled",
                    "detail": "MCP 接口已在 Manager 设置里关闭（mcp.mode=off）。",
                }
            elif tool.layer == "action" and mode != MODE_FULL:
                result = {
                    "ok": False,
                    "reason": "mode_read_only",
                    "detail": "当前是只读模式（mcp.mode=read-only）；动作工具要在 Manager 设置里把 mcp.mode 改成 full 才开放。",
                }
            else:
                try:
                    result = await tool.handler(client, args)
                except ManagerUnreachable as exc:
                    result = unreachable_result(exc)
                except Exception as exc:  # a bridge bug must not kill the session
                    result = {"ok": False, "reason": "bridge_error", "detail": str(exc)[:300]}
    duration_ms = int((time.monotonic() - started) * 1000)
    await _report_audit(
        client,
        tool=name,
        args=args,
        result=result,
        duration_ms=duration_ms,
        client_name=client_name,
        client_version=client_version,
    )
    return result


# ── Tools: read layer ────────────────────────────────────────────────────────


@register(
    "manager_status",
    "Manager 总览：应用版本、内核版本、运行中的浏览器数、画像总数，以及当前正在跑的自动化（检测/养号/进化）。接通后先调这个。",
    {
        "type": "object",
        "properties": {
            "include_automation_hours": {
                "type": "boolean",
                "default": False,
                "description": "是否一并返回自动化时段设置",
            }
        },
    },
    "read",
)
async def _manager_status(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    status, payload = await client.get("/api/status")
    if status >= 300 or not isinstance(payload, dict):
        return error_result(status, payload, tool="manager_status")
    result: dict[str, Any] = {"ok": True, "status": payload}
    s_auto, p_auto = await client.get("/api/automation/status")
    if s_auto < 300 and isinstance(p_auto, dict):
        result["automation"] = p_auto
    if args.get("include_automation_hours"):
        s_hours, p_hours = await client.get("/api/automation/hours")
        if s_hours < 300 and isinstance(p_hours, dict):
            result["automation_hours"] = p_hours
    return result


# ── MCP server wiring (the only place the SDK is touched) ────────────────────


def build_server(client: RestClient) -> Server:
    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        try:
            mode = await fetch_mode(client)
        except ManagerUnreachable:
            mode = MODE_READ_ONLY
        return types.ListToolsResult(tools=build_mcp_tools(mode))

    async def on_call_tool(ctx: Any, params: Any) -> types.CallToolResult:
        client_name = client_version = None
        try:
            info = ctx.session.client_params.client_info
            client_name, client_version = info.name, info.version
        except Exception:
            pass
        result = await dispatch(
            client,
            params.name,
            params.arguments or {},
            client_name=client_name,
            client_version=client_version,
        )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            is_error=result.get("reason") == "unknown_tool",
        )

    return Server(SERVER_NAME, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def _serve(client: RestClient) -> None:
    server = build_server(client)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    client = RestClient()
    try:
        mode = asyncio.run(fetch_mode(client))
    except ManagerUnreachable:
        mode = None  # Manager may start later; tools will report unreachable.
    if mode == MODE_OFF:
        print(
            "MCP 接口已被关闭（Manager 设置 mcp.mode=off），桥拒绝服务。"
            "在面板设置里改成 read-only 或 full 后再启动。",
            file=sys.stderr,
        )
        raise SystemExit(1)
    asyncio.run(_serve(client))


if __name__ == "__main__":
    main()
