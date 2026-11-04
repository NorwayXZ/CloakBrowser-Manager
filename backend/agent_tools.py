"""SDK-free agent tool layer shared by every way an agent reaches the Manager.

The same tool registry backs four front ends: the stdio MCP bridge
(``backend/mcp_server.py``), the HTTP MCP endpoint and the plain REST tool API
inside the Manager (``/api/agent/...``), and the ``cloak`` CLI. None of them
needs the ``mcp`` SDK to use these tools; only ``mcp_server.py`` and the HTTP
MCP mount import it.

Design (see MCP-PLAN.md):

* Every tool call is translated into a request to the Manager's own REST API
  (``http://127.0.0.1:{server_port()}/api/...``). Nothing here touches a
  browser directly; the Manager is the only executor.
* Tools are layered. The 14 read tools are always available unless the mode
  is ``off``; the action tools (launch / stop / site-check / warm-up /
  evolution / mail) register when the Manager setting ``mcp.mode`` is ``full`` or
  ``automation`` (``automation`` by default). The browser tools (CDP handout and
  page control) are a separate tier that only registers in ``automation``.
  ``automation`` is the unrestricted tier (delete / purge profiles, cookies,
  page JavaScript included) and is the default, because the Manager is a
  single-user local tool; the lower tiers stay available for people who want
  to narrow what an agent can do.
* Field policy: profile payloads are rebuilt from an allowlist and proxies are
  reduced to ``scheme://host:port`` (credentials stripped). ``get_profile``
  also returns the user's ``notes`` / ``warmup_persona``. The license key value
  does not exist in any REST response, so it cannot appear here either.
* Every dispatched call is reported to ``POST /api/mcp/audit`` with a
  redacted argument summary (best effort: when the Manager is unreachable
  the call itself already failed, so there is nothing unrecorded).
"""

from __future__ import annotations

import contextvars
import asyncio
import json
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import httpx

from .agent_auth import clamp_mode
from .linkability import parse_proxy_endpoint
from .runtime import server_port

SERVER_NAME = "cloakbrowser-manager"

MODE_OFF = "off"
MODE_READ_ONLY = "read-only"
MODE_FULL = "full"
# full + the "browser" tools: the only tier that hands out a CDP endpoint.
MODE_AUTOMATION = "automation"
_MODES = (MODE_OFF, MODE_READ_ONLY, MODE_FULL, MODE_AUTOMATION)
_ACTION_MODES = (MODE_FULL, MODE_AUTOMATION)

LAUNCH_MODES = ("manual", "debug")
MODES_FOR_CLI = (MODE_OFF, MODE_READ_ONLY, MODE_FULL, MODE_AUTOMATION)

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


# ── REST client ──────────────────────────────────────────────────────────────


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
        public_base_url: str | None = None,
    ) -> None:
        self.base_url = (base_url or f"http://127.0.0.1:{server_port()}").rstrip("/")
        # What an agent should dial to reach the Manager (CDP endpoints). Differs
        # from base_url when this client talks to the Manager in-process.
        self.public_base_url = (public_base_url or self.base_url).rstrip("/")
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
            # Loopback only: the user's proxy env vars must never reroute
            # (or break) calls to the local Manager.
            trust_env=False,
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
        except httpx.TimeoutException as exc:
            raise ManagerUnreachable(f"Manager 响应超时（{path}）：{exc}") from exc
        except httpx.HTTPError as exc:
            raise ManagerUnreachable(f"连不上 Manager（{self.base_url}）：{exc}") from exc
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, None

    @property
    def auth_required(self) -> bool:
        return bool(self._token)

    async def get(self, path: str, *, timeout: float = READ_TIMEOUT_S) -> tuple[int, Any]:
        return await self.request("GET", path, timeout=timeout)

    async def post(
        self, path: str, *, json_body: dict | None = None, timeout: float = READ_TIMEOUT_S
    ) -> tuple[int, Any]:
        return await self.request("POST", path, json_body=json_body, timeout=timeout)

    async def put(
        self, path: str, *, json_body: dict | None = None, timeout: float = READ_TIMEOUT_S
    ) -> tuple[int, Any]:
        return await self.request("PUT", path, json_body=json_body, timeout=timeout)


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


_LEASE_MARKER = "[profile_leased]"


def error_result(status: int, payload: Any, *, tool: str = "") -> dict[str, Any]:
    """Map a REST error onto the bridge's structured result vocabulary."""
    # The Manager's agent endpoints already answer in the structured form.
    if isinstance(payload, dict) and isinstance(payload.get("reason"), str) and payload.get("ok") is False:
        return dict(payload)
    detail = _detail_of(payload)
    if _LEASE_MARKER in detail:
        result = {"ok": False, "reason": "profile_leased", "detail": detail}
        lease = payload.get("lease") if isinstance(payload, dict) else None
        if isinstance(lease, dict):
            result["lease"] = lease
        return result
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


def scope_denied_result(scope: str | None, needed: str) -> dict[str, Any]:
    return {
        "ok": False,
        "reason": "scope_denied",
        "detail": f"这个 agent token 的 scope={scope} 不够用，这个工具需要 {needed} 权限。让管理员签发更高 scope 的 token。",
    }


def not_automation_result() -> dict[str, Any]:
    return {
        "ok": False,
        "reason": "mode_not_automation",
        "detail": (
            "页面控制、Cookie、删除画像等只在 mcp.mode=automation 下开放（默认就是 automation，"
            "这里说明有人把它调低了）：在 Manager 设置「API 与 MCP」里改回 automation 并重启客户端。"
        ),
    }


# ── Field policy (MCP-PLAN §3) ───────────────────────────────────────────────


def sanitize_proxy(proxy: Any) -> str | None:
    """scheme://host:port with credentials stripped; opaque share links
    (whose stored string itself encodes secrets) collapse to a marker."""
    if not proxy:
        return None
    endpoint = parse_proxy_endpoint(str(proxy))
    return endpoint if endpoint else "configured"


# Profile fields an agent may see in lists. Everything else on ProfileResponse is
# left out: cookies_json (read cookies with browser_cookies), cdp_url / vnc_ws_port /
# user_data_dir / proxy_geo (local access paths and exit-IP details). notes and
# warmup_persona are added by get_profile only, to keep list output small.
PROFILE_FIELDS = (
    "id", "name", "browser_engine", "device_profile", "fingerprint_seed",
    "proxy_id", "proxy_connection_mode", "relay_id", "relay_name",
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


# `text` is what browser_type types: it can be a password, so the audit keeps only its length.
_PRIVATE_ARG_KEYS = {"notes", "persona", "warmup_persona", "text", "cookies", "cookies_json"}


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
    layer: str  # "read" | "action" | "browser"
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


def visible_tools(mode: str, token_scope: str | None = None) -> list[ToolDef]:
    mode = clamp_mode(mode, token_scope)
    if mode == MODE_OFF:
        return []
    if mode == MODE_AUTOMATION:
        return list(TOOLS.values())
    if mode == MODE_FULL:
        return [tool for tool in TOOLS.values() if tool.layer in ("read", "action")]
    return [tool for tool in TOOLS.values() if tool.layer == "read"]


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


_PROCESS_TAG = uuid.uuid4().hex[:6]
# Who is calling, for leases: set per dispatch so handlers need no extra argument.
_CALLER: contextvars.ContextVar[str] = contextvars.ContextVar("agent_caller", default="agent")

_LAYER_NEEDS = {"action": "control", "browser": "cdp"}

# What an agent should do next after a failure; added to {ok:false} results.
NEXT_STEPS: dict[str, str] = {
    "manager_unreachable": "让用户先打开 CloakBrowser Manager（端口要一致），不要反复重试。",
    "mcp_disabled": "MCP 被关了：让用户在 Manager 设置里把 mcp.mode 改成 read-only/full/automation。",
    "mode_read_only": "需要写操作：让用户把 mcp.mode 改成 full，再重启 MCP 客户端。",
    "mode_not_automation": "页面控制/CDP 要 automation 档：向用户说明（CDP 能读 Cookie），由用户决定是否开启。",
    "scope_denied": "换一个 scope 更高的 agent token，或让用户用管理员权限操作。",
    "seat_busy": "授权座位被占：等几分钟，或先 stop_profile 关掉别的画像；不要立刻重试。",
    "automation_busy": "另一个自动化（检测/养号/进化）在跑：等它结束再试，可用 manager_status 查看。",
    "already_running": "画像已在运行。若是 manual 模式开的且要用页面控制：确认可关后 stop_profile，再 open_browser。",
    "not_running": "画像没在运行：先 open_browser。",
    "cdp_unavailable": "画像是 manual 模式启动的，没有 CDP：stop_profile 后用 open_browser 重新启动。",
    "profile_leased": "画像正被别人控制（可能是用户在接管）：等租约过期或让用户归还，不要强行操作。",
    "not_found": "找不到：用 list_profiles 重新查画像 id/名称。",
    "invalid_argument": "按 detail 修正参数后再调用。",
    "unknown_ref": "元素引用无效：先调 browser_snapshot 取最新引用。",
    "stale_ref": "页面变了，引用失效：重新调 browser_snapshot。",
    "page_navigating": "页面还在跳转：等一两秒再调 browser_snapshot。",
    "no_page": "没有打开的标签页：用 browser_tabs(action=new) 或 browser_navigate。",
    "path_not_allowed": "上传只认 agent 文件目录：用 browser_downloads 看目录位置，把文件复制进去再传。",
    "files_disabled": "这个 Manager 没开启 agent 文件目录：让用户检查版本和配置。",
    "dialog_open": "页面被 JS 对话框挡住：先调 browser_dialog(action=accept 或 dismiss)，再继续。",
    "no_dialog": "现在没有待处理的对话框，直接继续操作即可。",
    "selector_not_found": "没匹配到元素：browser_snapshot 看看页面现状，再换个写法或用 ref。",
    "ambiguous_selector": "匹配到多个：把选择器写具体（加 name=…），或改用 browser_snapshot 里的 ref。",
    "navigation_failed": "网址打不开：检查网址和代理出口，必要时 get_fingerprint_report。",
    "timeout": "操作超时：页面可能还在加载，browser_snapshot 看看现状再决定是否重试。",
    "mail_not_configured": "邮箱还没配置：告诉用户在 Manager 的「邮箱」页填写邮箱服务器和管理员账号，不要自己去找别的邮箱。",
    "mail_server_error": "邮箱服务器出错或连不上：稍等再试一次；还不行就把 detail 告诉用户。",
    "vault_ref_invalid": "引用无效：用 vault_list 看这个画像有哪些条目；条目属于哪个画像，引用就只能在哪个画像里用。",
    "quota_exceeded": "今天新建的保险库条目到上限了：别再批量创建，需要的话让用户处理。",
    "mail_timeout": "还没收到邮件：确认表单真的提交成功、地址没填错（browser_snapshot 看看页面），需要的话点页面上的「重新发送」，再调一次 mail_wait_code。",
}


def caller_holder(client_name: str | None, holder: str | None = None) -> str:
    return holder or f"{client_name or 'agent'}#{_PROCESS_TAG}"


async def dispatch(
    client: RestClient,
    name: str,
    arguments: dict[str, Any] | None,
    *,
    client_name: str | None = None,
    client_version: str | None = None,
    token_scope: str | None = None,
    holder: str | None = None,
) -> dict[str, Any]:
    """Run one tool call through the mode gate and audit trail.

    ``token_scope`` is the scope of the agent token the call came in with (or
    ``None`` for an administrator / a local bridge); it caps the effective mode.
    """
    args = arguments or {}
    started = time.monotonic()
    tool = TOOLS.get(name)
    if tool is None:
        result: dict[str, Any] = {"ok": False, "reason": "unknown_tool", "detail": f"没有这个工具：{name}"}
    else:
        try:
            configured = await fetch_mode(client)
        except ManagerUnreachable as exc:
            result = unreachable_result(exc)
            configured = None
        if tool is not None and configured is not None:
            mode = clamp_mode(configured, token_scope)
            clamped = mode != configured
            if mode == MODE_OFF:
                result = {
                    "ok": False,
                    "reason": "mcp_disabled",
                    "detail": "MCP 接口已在 Manager 设置里关闭（mcp.mode=off）。",
                }
            elif tool.layer == "action" and mode not in _ACTION_MODES:
                result = (
                    scope_denied_result(token_scope, _LAYER_NEEDS["action"])
                    if clamped
                    else {
                        "ok": False,
                        "reason": "mode_read_only",
                        "detail": "当前是只读模式（mcp.mode=read-only）；动作工具要在 Manager 设置里把 mcp.mode 改成 full 才开放。",
                    }
                )
            elif tool.layer == "browser" and mode != MODE_AUTOMATION:
                result = (
                    scope_denied_result(token_scope, _LAYER_NEEDS["browser"])
                    if clamped
                    else not_automation_result()
                )
            else:
                token = _CALLER.set(caller_holder(client_name, holder))
                try:
                    result = await tool.handler(client, args)
                except ManagerUnreachable as exc:
                    result = unreachable_result(exc)
                except Exception as exc:  # a bridge bug must not kill the session
                    result = {"ok": False, "reason": "bridge_error", "detail": str(exc)[:300]}
                finally:
                    _CALLER.reset(token)
    if result.get("ok") is False and "next_step" not in result:
        hint = NEXT_STEPS.get(str(result.get("reason")))
        if hint:
            result["next_step"] = hint
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


async def _get_or_error(
    client: RestClient, path: str, tool: str
) -> tuple[Any, dict[str, Any] | None]:
    status, payload = await client.get(path)
    if status >= 300:
        return None, error_result(status, payload, tool=tool)
    return payload, None


def _profile_id_arg(args: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    profile_id = str(args.get("profile_id") or "").strip()
    if not profile_id:
        return "", {"ok": False, "reason": "invalid_argument", "detail": "缺少 profile_id，先用 list_profiles 查。"}
    return profile_id, None


LIST_PROFILES_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "page": {"type": "integer", "default": 1, "minimum": 1, "description": "第几页（从 1 开始）"},
        "limit": {"type": "integer", "default": 200, "minimum": 1, "maximum": 500, "description": "每页多少个，默认 200"},
        "group_name": {"type": "string", "description": "只看这个分组"},
        "query": {"type": "string", "description": "名称里包含这段文字（不区分大小写）"},
        "status": {"type": "string", "enum": ["running", "stopped"], "description": "只看运行中或已停止的"},
    },
}


@register("list_profiles", "列出画像的摘要（id、名称、平台、设备模板、时区/语言、指纹配置、养号与进化开关、运行状态），默认每页 200 个，可按分组、名称、运行状态筛选。total_pages 大于 1 时必须翻完所有页再对“全部画像”做事。代理只回出口端点不带账密，备注与 Cookie 不回。", LIST_PROFILES_ARGS, "read")
async def _list_profiles(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    payload, err = await _get_or_error(client, "/api/profiles", "list_profiles")
    if err:
        return err
    rows = [p for p in payload if isinstance(p, dict)]
    group = str(args.get("group_name") or "").strip()
    if group:
        rows = [p for p in rows if p.get("group_name") == group]
    query = str(args.get("query") or "").strip().lower()
    if query:
        rows = [p for p in rows if query in str(p.get("name") or "").lower()]
    wanted = str(args.get("status") or "").strip()
    if wanted:
        rows = [p for p in rows if (p.get("status") == "running") == (wanted == "running")]
    limit = max(1, min(500, int(args.get("limit") or 200)))
    total = len(rows)
    pages = max(1, -(-total // limit))
    page = max(1, int(args.get("page") or 1))
    chunk = rows[(page - 1) * limit : page * limit]
    return {
        "ok": True,
        "count": len(chunk),
        "total": total,
        "page": page,
        "total_pages": pages,
        "profiles": [shape_profile(p) for p in chunk],
    }


@register("get_profile", "看单个画像的完整配置（含备注 notes 和养号人设）加实时运行状态。代理只显示地址，不显示账号密码。", PROFILE_ID_ARGS, "read")
async def _get_profile(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    quoted = quote(profile_id, safe="")
    payload, err = await _get_or_error(client, f"/api/profiles/{quoted}", "get_profile")
    if err:
        return err
    shaped = shape_profile(payload)
    shaped["notes"] = payload.get("notes")
    shaped["warmup_persona"] = payload.get("warmup_persona")
    result: dict[str, Any] = {"ok": True, "profile": shaped}
    s_status, p_status = await client.get(f"/api/profiles/{quoted}/status")
    if s_status < 300 and isinstance(p_status, dict):
        result["live_status"] = {
            key: p_status.get(key)
            for key in ("status", "runtime_mode", "viewer_mode", "browser_engine", "launch_mode")
        }
    return result


@register("get_profile_preflight", "启动前一致性检查：这个画像现在能不能启动、有哪些问题。launch 之前可以先看它。", PROFILE_ID_ARGS, "read")
async def _get_profile_preflight(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    payload, err = await _get_or_error(
        client, f"/api/profiles/{quote(profile_id, safe='')}/preflight", "get_profile_preflight"
    )
    if err:
        return err
    return {"ok": True, "preflight": payload}


@register(
    "list_device_templates",
    "列出设备模板库（104 个真实 Windows 设备）的摘要：id、名称、屏幕、GPU、CPU、核数、内存。",
    NO_ARGS,
    "read",
)
async def _list_device_templates(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    payload, err = await _get_or_error(client, "/api/device-templates", "list_device_templates")
    if err:
        return err
    keys = (
        "id", "name", "family", "cpu", "screen_width", "screen_height",
        "gpu_vendor", "gpu_renderer", "hardware_concurrency", "device_memory",
    )
    templates = [
        {key: t.get(key) for key in keys if key in t} for t in payload if isinstance(t, dict)
    ]
    return {"ok": True, "count": len(templates), "templates": templates}


@register("get_linkability", "关联分析：哪些画像看起来像同一个人（共用代理出口/设备/指纹种子等），附原因与改进建议。", NO_ARGS, "read")
async def _get_linkability(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    payload, err = await _get_or_error(client, "/api/linkability", "get_linkability")
    if err:
        return err
    return {"ok": True, "linkability": payload}


@register("list_site_check_reports", "列出已保存的指纹检测报告的元数据与通过计数（不含逐项明细，明细用 get_site_check_report）。", NO_ARGS, "read")
async def _list_site_check_reports(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    payload, err = await _get_or_error(client, "/api/site-checks", "list_site_check_reports")
    if err:
        return err
    reports = payload if isinstance(payload, list) else []
    return {"ok": True, "count": len(reports), "reports": reports[:50]}


@register(
    "get_site_check_report",
    "读一份完整的指纹检测报告（含与上一份的 diff、是否无头运行的标记）。",
    {
        "type": "object",
        "properties": {"report_id": {"type": "string", "description": "报告 id（先用 list_site_check_reports 查）"}},
        "required": ["report_id"],
    },
    "read",
)
async def _get_site_check_report(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    report_id = str(args.get("report_id") or "").strip()
    if not report_id:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 report_id，先用 list_site_check_reports 查。"}
    payload, err = await _get_or_error(
        client, f"/api/site-checks/{quote(report_id, safe='')}", "get_site_check_report"
    )
    if err:
        return err
    return {"ok": True, "report": payload}


@register("get_current_site_check", "看正在进行中的指纹检测的进度快照（run_site_check 之后轮询这个）。", NO_ARGS, "read")
async def _get_current_site_check(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    payload, err = await _get_or_error(client, "/api/site-checks/current", "get_current_site_check")
    if err:
        return err
    return {"ok": True, "current": payload}


@register("get_fingerprint_report", "读画像的本地指纹探针报告（逐项一致性检查结果，不访问外部检测站）。", PROFILE_ID_ARGS, "read")
async def _get_fingerprint_report(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    payload, err = await _get_or_error(
        client, f"/api/profiles/{quote(profile_id, safe='')}/fingerprint-report", "get_fingerprint_report"
    )
    if err:
        return err
    return {"ok": True, "report": payload}


@register("get_warmup_state", "看画像的养号状态：开关、每日上限、目标平台、身份年龄、最近运行记录。", PROFILE_ID_ARGS, "read")
async def _get_warmup_state(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    payload, err = await _get_or_error(
        client, f"/api/profiles/{quote(profile_id, safe='')}/warmup", "get_warmup_state"
    )
    if err:
        return err
    return {"ok": True, "warmup": payload}


@register(
    "list_warmup_scripts",
    "看画像的 AI 养号剧本批次：状态、主题与意图（搜索词）。persona 快照不回。批准/驳回用 approve_warmup_batch / reject_warmup_batch。",
    PROFILE_ID_ARGS,
    "read",
)
async def _list_warmup_scripts(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    payload, err = await _get_or_error(
        client, f"/api/profiles/{quote(profile_id, safe='')}/warmup/scripts", "list_warmup_scripts"
    )
    if err:
        return err
    batches = []
    for batch in payload.get("batches") or []:
        if not isinstance(batch, dict):
            continue
        shaped = {key: batch.get(key) for key in ("batch_id", "created_at", "status", "model")}
        shaped["scripts"] = batch.get("scripts") or []
        batches.append(shaped)
    return {
        "ok": True,
        "llm_configured": payload.get("llm_configured"),
        "generating": payload.get("generating"),
        "last_generation": payload.get("last_generation"),
        "batches": batches,
    }


@register(
    "get_evolution",
    "看自对抗进化：引擎状态、待人工批准的提案、实验战报。section 可选 status/proposals/logs/all（默认 all）。批准提案用 approve_evolution_proposal，驳回用 dismiss_evolution_proposal。",
    {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": ["all", "status", "proposals", "logs"],
                "default": "all",
            }
        },
    },
    "read",
)
async def _get_evolution(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    section = str(args.get("section") or "all")
    if section not in ("all", "status", "proposals", "logs"):
        return {"ok": False, "reason": "invalid_argument", "detail": f"section 只能是 all/status/proposals/logs，收到：{section}"}
    result: dict[str, Any] = {"ok": True}
    if section in ("all", "status"):
        payload, err = await _get_or_error(client, "/api/evolution/status", "get_evolution")
        if err:
            return err
        result["status"] = payload
    if section in ("all", "proposals"):
        payload, err = await _get_or_error(client, "/api/evolution/proposals", "get_evolution")
        if err:
            return err
        result["proposals"] = payload
    if section in ("all", "logs"):
        payload, err = await _get_or_error(client, "/api/evolution/logs", "get_evolution")
        if err:
            return err
        result["logs"] = payload[:20] if isinstance(payload, list) else payload
    return result


@register("get_kernel_info", "看浏览器内核信息：版本、已安装内核、授权状态（只有 tier/plan/到期/key 是否已存，key 值本身任何接口都不返回）。", NO_ARGS, "read")
async def _get_kernel_info(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    payload, err = await _get_or_error(client, "/api/kernel", "get_kernel_info")
    if err:
        return err
    return {"ok": True, "kernel": payload}


PROXY_CAP_ARGS = {"type": "object", "properties": {
    "proxy_id": {"type": "string", "description": "list_proxies 返回的代理编号"},
    "profile_id": {"type": "string", "description": "可改用环境编号，检查该环境真实绑定的代理"},
}}
ROTATION_JOB_ARGS = {"type":"object","properties":{"job_id":{"type":"string"}},"required":["job_id"]}
ROTATE_IP_ARGS = {"type":"object","properties":{
    "proxy_id":{"type":"string"},"profile_id":{"type":"string"},
    "request_id":{"type":"string","description":"同一意图重试须复用此编号，避免再次换 IP"},
    "wait_seconds":{"type":"integer","default":90,"minimum":0,"maximum":105},
},"required":["proxy_id"]}


@register("list_proxies", "列出已保存代理及换 IP 能力；仅返回端点，不返回账号密码或刷新链接。", NO_ARGS, "read")
async def _list_proxies(client, args):
    payload, err = await _get_or_error(client,"/api/proxy-presets","list_proxies")
    if err: return err
    return {"ok":True,"proxies":[{"proxy_id":p["id"],"name":p["name"],"endpoint":sanitize_proxy(p.get("proxy")),
        "capabilities":{"rotate_ip":bool(p.get("can_rotate_ip")),"check_exit_ip":True},"rotate_tool":"rotate_proxy_ip"} for p in payload]}


@register("get_proxy_capabilities", "查看代理或环境是否支持一键换 IP、冷却时间及受影响环境。不会暴露切换链接。", PROXY_CAP_ARGS, "read")
async def _get_proxy_capabilities(client,args):
    if args.get("profile_id"): path=f'/api/profiles/{quote(str(args["profile_id"]),safe="")}/proxy-capabilities'
    elif args.get("proxy_id"): path=f'/api/proxy-presets/{quote(str(args["proxy_id"]),safe="")}/capabilities'
    else: return {"ok":False,"reason":"invalid_argument","detail":"请提供 proxy_id 或 profile_id"}
    status,payload=await client.get(path)
    if status>=300:return error_result(status,payload,tool="get_proxy_capabilities")
    return {"ok":True,**payload}


@register("check_proxy_exit_ip", "经代理/环境的实际直连或中转路径，建立新连接检测最终出口 IP；不触发换 IP，不代表旧网页连接已重连。", PROXY_CAP_ARGS, "read")
async def _check_proxy_exit_ip(client,args):
    proxy_id=str(args.get("proxy_id") or "")
    if args.get("profile_id"):
        status,caps=await client.get(f'/api/profiles/{quote(str(args["profile_id"]),safe="")}/proxy-capabilities')
        if status>=300:return error_result(status,caps,tool="check_proxy_exit_ip")
        proxy_id=str(caps.get("proxy_id") or "")
    if not proxy_id:return {"ok":False,"reason":"invalid_argument","detail":"请提供明确的代理或已关联的环境"}
    status,payload=await client.post(f'/api/proxy-presets/{quote(proxy_id,safe="")}/check',json_body={"profile_id":args.get("profile_id")},timeout=ACTION_TIMEOUT_S)
    if status>=300:return error_result(status,payload,tool="check_proxy_exit_ip")
    return {"ok":True,**payload}


@register("get_proxy_rotation_result", "查看一次换 IP 操作的进度/结果。pending 时继续查询，不要重新触发切换。verified 才表示已确认改变。", ROTATION_JOB_ARGS, "read")
async def _get_proxy_rotation_result(client,args):
    job_id=str(args.get("job_id") or "")
    if not job_id:return {"ok":False,"reason":"invalid_argument","detail":"缺少 job_id"}
    status,payload=await client.get(f'/api/proxy-rotations/{quote(job_id,safe="")}')
    if status>=300:return error_result(status,payload,tool="get_proxy_rotation_result")
    return {"ok":True,"job":payload}


@register("list_groups", "列出全部分组（id、名称、颜色）和每个分组里有多少个画像。新建画像、移动画像前先看这里。", NO_ARGS, "read")
async def _list_groups(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    payload, err = await _get_or_error(client, "/api/groups", "list_groups")
    if err:
        return err
    profiles, perr = await _get_or_error(client, "/api/profiles", "list_groups")
    if perr:
        return perr
    counts: dict[str, int] = {}
    for item in profiles:
        if isinstance(item, dict):
            name = str(item.get("group_name") or "未分组")
            counts[name] = counts.get(name, 0) + 1
    groups = [
        {"id": g.get("id"), "name": g.get("name"), "color": g.get("color"), "profiles": counts.get(str(g.get("name")), 0)}
        for g in payload
        if isinstance(g, dict)
    ]
    return {"ok": True, "count": len(groups), "groups": groups}


@register("list_running", "现在正在运行的画像（id、名称、启动模式）。想知道占了几个授权座位、要不要先关几个时看这里。", NO_ARGS, "read")
async def _list_running(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    payload, err = await _get_or_error(client, "/api/profiles", "list_running")
    if err:
        return err
    running = [
        {"id": p.get("id"), "name": p.get("name"), "runtime_mode": p.get("runtime_mode")}
        for p in payload
        if isinstance(p, dict) and p.get("status") == "running"
    ]
    return {"ok": True, "count": len(running), "profiles": running}


@register("list_trash", "回收站里的画像（7 天内删除的，可用 restore_profile 恢复）。只回摘要。", NO_ARGS, "read")
async def _list_trash(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    payload, err = await _get_or_error(client, "/api/profiles/trash", "list_trash")
    if err:
        return err
    items = [
        {"id": p.get("id"), "name": p.get("name"), "group_name": p.get("group_name"), "deleted_at": p.get("deleted_at")}
        for p in payload
        if isinstance(p, dict)
    ]
    return {"ok": True, "count": len(items), "profiles": items}


# ── Tools: action layer (registered only when mcp.mode == "full") ────────────


LAUNCH_PROFILE_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "profile_id": {"type": "string", "description": "画像 id（先用 list_profiles 查）"},
        "launch_mode": {
            "type": "string",
            "enum": list(LAUNCH_MODES),
            "default": "manual",
            "description": (
                "manual（默认）：给人用，没有 CDP。"
                "debug：开放 CDP 供 agent 操作页面，只在 mcp.mode=automation 下可用；"
                "要操作页面更省事的是直接用 open_browser。"
            ),
        },
    },
    "required": ["profile_id"],
}

OPEN_BROWSER_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "profile": {"type": "string", "description": "画像 id 或画像名称（名称需完全一致且唯一）"},
    },
    "required": ["profile"],
}

# What the agent needs to attach a CDP client; nothing else of the profile.
_CDP_FIELDS = ("cdp_http_endpoint", "cdp_ws_endpoint", "auth_required", "auth_hint", "tabs", "usage")


async def _cdp_endpoint_info(client: RestClient, profile_id: str, *, tool: str) -> dict[str, Any]:
    """CDP connection info for a running debug-mode profile, or a structured
    error. The endpoints point at the Manager's own CDP proxy
    (``/api/profiles/{id}/cdp``), never at Chrome's raw debugging port."""
    quoted = quote(profile_id, safe="")
    status, payload = await client.get(f"/api/profiles/{quoted}/status")
    if status >= 300 or not isinstance(payload, dict):
        return error_result(status, payload, tool=tool)
    if payload.get("status") != "running":
        return {
            "ok": False,
            "reason": "not_running",
            "detail": "这个画像没在运行。用 open_browser 启动它。",
        }
    if not payload.get("cdp_url"):
        return {
            "ok": False,
            "reason": "cdp_unavailable",
            "detail": (
                "这个画像是以 manual 模式启动的，没有 CDP。先 stop_profile，"
                "再用 open_browser（或 launch_profile launch_mode=debug）重新启动。"
            ),
        }
    cdp_path = f"/api/profiles/{quoted}/cdp"
    http_endpoint = f"{client.public_base_url}{cdp_path}"
    ws_base = client.public_base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    tabs: list[dict[str, Any]] = []
    tabs_status, tabs_payload = await client.get(f"{cdp_path}/json/list")
    if tabs_status < 300 and isinstance(tabs_payload, list):
        tabs = [
            {key: tab.get(key) for key in ("id", "title", "url")}
            for tab in tabs_payload
            if isinstance(tab, dict) and tab.get("type") == "page"
        ]
    result: dict[str, Any] = {
        "ok": True,
        "profile_id": profile_id,
        "browser_engine": payload.get("browser_engine"),
        "launch_mode": payload.get("launch_mode"),
        "cdp_http_endpoint": http_endpoint,
        "cdp_ws_endpoint": f"{ws_base}{cdp_path}",
        "auth_required": client.auth_required,
        "tabs": tabs,
        "usage": {
            "playwright": f"chromium.connect_over_cdp('{http_endpoint}')",
            "playwright_mcp": f"npx @playwright/mcp@latest --cdp-endpoint {http_endpoint}",
            "chrome_devtools_mcp": f"npx chrome-devtools-mcp@latest --browser-url {http_endpoint}",
        },
    }
    if client.auth_required:
        # Placeholders only: the real token is never echoed back.
        result["usage"]["playwright_mcp"] = (
            f"npx @playwright/mcp@latest --cdp-endpoint {http_endpoint}"
            " --cdp-header 'Authorization: Bearer <TOKEN>'"
        )
        result["usage"]["chrome_devtools_mcp"] = (
            f"npx chrome-devtools-mcp@latest --wsEndpoint={result['cdp_ws_endpoint']}"
            " --wsHeaders='{\"Authorization\":\"Bearer <TOKEN>\"}'"
        )
        result["auth_hint"] = (
            "Manager 开了鉴权：CDP 客户端连接时要带 Authorization: Bearer <AUTH_TOKEN> 请求头"
            "（token 与 Manager 的 AUTH_TOKEN 相同，这里不回显）。"
        )
    return result


def _with_cdp(result: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    if info.get("ok"):
        result.update({key: info[key] for key in _CDP_FIELDS if key in info})
    else:
        result["cdp_error"] = {"reason": info.get("reason"), "detail": info.get("detail")}
    return result


@register(
    "launch_profile",
    "启动一个画像的浏览器。已在跑会回 already_running；撞上授权单座位会回 seat_busy（座位释放需要几分钟，不要立刻重试）。"
    "launch_mode=debug 会同时开放 CDP 并回连接信息，仅 mcp.mode=automation 可用；想操作页面直接用 open_browser。",
    LAUNCH_PROFILE_ARGS,
    "action",
)
async def _launch_profile(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    launch_mode = str(args.get("launch_mode") or "manual")
    if launch_mode not in LAUNCH_MODES:
        return {
            "ok": False,
            "reason": "invalid_argument",
            "detail": f"launch_mode 只能是 {'/'.join(LAUNCH_MODES)}，收到：{launch_mode}",
        }
    # debug opens a CDP port, and CDP can read cookies: automation tier only.
    if launch_mode == "debug" and await fetch_mode(client) != MODE_AUTOMATION:
        return not_automation_result()
    status, payload = await client.post(
        f"/api/profiles/{quote(profile_id, safe='')}/launch",
        json_body={"launch_mode": launch_mode},
        timeout=ACTION_TIMEOUT_S,
    )
    if status >= 300 or not isinstance(payload, dict):
        return error_result(status, payload, tool="launch_profile")
    # LaunchResponse also carries cdp_url / vnc_ws_port / display — local
    # access paths the agent does not get; in automation mode the CDP info is
    # rebuilt by _cdp_endpoint_info instead of passing cdp_url through.
    result: dict[str, Any] = {
        "ok": True,
        **{
            key: payload.get(key)
            for key in ("profile_id", "status", "runtime_mode", "viewer_mode", "browser_engine", "launch_mode")
        },
    }
    if launch_mode == "debug":
        _with_cdp(result, await _cdp_endpoint_info(client, profile_id, tool="launch_profile"))
    return result


@register("rotate_proxy_ip", "调用已配置的供应商链接切换 SOCKS5 IP，并经环境实际直连/中转路径验证。可能影响共享代理的其他环境；不会自动关闭浏览器。仅 verified 表示确认新 IP；其他结果不要盲目重试，用 job_id 查询，并复用 request_id。", ROTATE_IP_ARGS, "action")
async def _rotate_proxy_ip(client,args):
    proxy_id=str(args.get("proxy_id") or "")
    if not proxy_id:return {"ok":False,"reason":"invalid_argument","detail":"缺少 proxy_id"}
    request_id=str(args.get("request_id") or uuid.uuid4())
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",request_id):
        return {"ok":False,"reason":"invalid_argument","detail":"request_id 仅支持字母、数字、连字符和下划线"}
    body={"request_id":request_id,"profile_id":args.get("profile_id")}
    try:
        status,payload=await client.post(f'/api/proxy-presets/{quote(proxy_id,safe="")}/rotate',json_body=body,timeout=ACTION_TIMEOUT_S)
    except ManagerUnreachable:
        return {"ok":False,"reason":"manager_unreachable","request_id":request_id,"do_not_retry":True,"detail":"请求结果未知；恢复后复用 request_id 查询，不要创建新的切换请求"}
    if status>=300:return error_result(status,payload,tool="rotate_proxy_ip")
    deadline=time.monotonic()+max(0,min(105,int(args.get("wait_seconds",90))))
    while payload.get("state") in {"queued","running"} and time.monotonic()<deadline:
        await asyncio.sleep(2)
        try:
            status,updated=await client.get(f'/api/proxy-rotations/{quote(payload["id"],safe="")}')
        except ManagerUnreachable:
            return {"ok":False,"reason":"manager_unreachable","request_id":request_id,"job":payload,
                "verified":False,"do_not_retry":True,"detail":"读取结果中断；用 job.id 查询，不要重新切换"}
        if status>=300:break
        payload=updated
    return {"ok":payload.get("state")!="failed","reason":"rotation_failed" if payload.get("state")=="failed" else None,"request_id":request_id,"job":payload,"verified":payload.get("state")=="verified" and payload.get("proxy_id")==proxy_id and payload.get("profile_id")==args.get("profile_id"),
        "do_not_retry":True,"next_step":"查看 job.state；未完成用 get_proxy_rotation_result 查询。已打开的网页连接可能需要重连，未经用户要求不要自动关闭浏览器。"}


@register("stop_profile", "关闭一个正在运行的画像浏览器。没在跑会回 not_running。", PROFILE_ID_ARGS, "action")
async def _stop_profile(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    status, payload = await client.post(
        f"/api/profiles/{quote(profile_id, safe='')}/stop", timeout=ACTION_TIMEOUT_S
    )
    if status >= 300:
        return error_result(status, payload, tool="stop_profile")
    return {"ok": True, "profile_id": profile_id}


@register(
    "run_site_check",
    "对画像跑一轮指纹检测（异步：先关掉该画像的浏览器再以调试模式重开，测完自动关闭）。返回任务快照，进度用 get_current_site_check 轮询，报告用 list_site_check_reports 查。另一个自动化在跑时回 automation_busy。",
    PROFILE_ID_ARGS,
    "action",
)
async def _run_site_check(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    status, payload = await client.post(
        f"/api/profiles/{quote(profile_id, safe='')}/site-check", json_body={}
    )
    if status >= 300:
        return error_result(status, payload, tool="run_site_check")
    return {"ok": True, "job": payload}


@register("run_warmup", "立刻给画像跑一轮养号（不等定时调度）。另一个自动化在跑时回 automation_busy。", PROFILE_ID_ARGS, "action")
async def _run_warmup(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    status, payload = await client.post(
        f"/api/profiles/{quote(profile_id, safe='')}/warmup/run", json_body={}
    )
    if status >= 300:
        return error_result(status, payload, tool="run_warmup")
    return {"ok": True, "started": bool(isinstance(payload, dict) and payload.get("started"))}


@register(
    "run_evolution",
    "立刻给画像跑一轮自对抗进化实验（只在一次性克隆上实验，胜出方案变成待批提案，不直接改真画像）。另一个进化周期在跑时回 conflict/automation_busy。",
    PROFILE_ID_ARGS,
    "action",
)
async def _run_evolution(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    status, payload = await client.post(
        f"/api/profiles/{quote(profile_id, safe='')}/evolution/run", json_body={}
    )
    if status >= 300:
        return error_result(status, payload, tool="run_evolution")
    return {"ok": True, "started": bool(isinstance(payload, dict) and payload.get("started"))}


# ── Tools: mail (action layer) ────────────────────────────────────────────────


def _mail_error(status: int, payload: Any, *, tool: str) -> dict[str, Any]:
    detail = _detail_of(payload)
    if status == 409:
        return {"ok": False, "reason": "mail_not_configured", "detail": detail}
    if status == 502:
        return {"ok": False, "reason": "mail_server_error", "detail": detail}
    return error_result(status, payload, tool=tool)


MAIL_ADDRESS_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "profile": {"type": "string", "description": "画像 id 或名称：地址记在这个画像名下，以后再要会给同一个"},
        "new": {"type": "boolean", "default": False, "description": "true = 给这个画像再发一个新地址（同一画像注册第二个账号时用）"},
        "domain": {"type": "string", "description": "可选：指定域名（如 example.com），不填随机选一个"},
    },
    "required": ["profile"],
}

MAIL_WAIT_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "address": {"type": "string", "description": "mail_get_address 给的邮箱地址"},
        "timeout_s": {"type": "number", "default": 120, "maximum": 170, "description": "最多等多少秒（默认 120，上限 170）"},
        "from_contains": {"type": "string", "description": "可选：发件人里要包含的文字，如 github.com"},
        "subject_contains": {"type": "string", "description": "可选：标题里要包含的文字"},
    },
    "required": ["address"],
}

MAIL_LIST_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "address": {"type": "string", "description": "mail_get_address 给的邮箱地址"},
        "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
    },
    "required": ["address"],
}


def _mail_summary(message: dict[str, Any], *, text_limit: int) -> dict[str, Any]:
    return {
        "id": message.get("id"),
        "from": message.get("from"),
        "subject": message.get("subject"),
        "received_at": message.get("received_at"),
        "code": message.get("code"),
        "link": message.get("link"),
        "text": str(message.get("text") or "")[:text_limit],
    }


@register(
    "mail_get_address",
    "给画像一个能收信的邮箱地址，注册账号时填它。同一画像默认一直给同一个地址；new=true 再发一个新的。"
    "填进表单提交后，用 mail_wait_code 取验证码。邮箱没配置回 mail_not_configured。",
    MAIL_ADDRESS_ARGS,
    "action",
)
async def _mail_get_address(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    ref = str(args.get("profile") or "").strip()
    if not ref:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 profile（画像 id 或名称），先用 list_profiles 查。"}
    profile_id, err = await _resolve_profile(client, ref)
    if err:
        return err
    next_step = "把地址填进注册表单并提交，然后调 mail_wait_code(address=…) 等验证码。"
    if not args.get("new"):
        status, payload = await client.get(f"/api/mail/addresses?profile_id={quote(profile_id, safe='')}")
        if status >= 300 or not isinstance(payload, list):
            return _mail_error(status, payload, tool="mail_get_address")
        if payload:
            return {"ok": True, "address": payload[0]["address"], "created": False, "profile_id": profile_id, "next_step": next_step}
    body: dict[str, Any] = {"profile_id": profile_id}
    if args.get("domain"):
        body["domain"] = str(args["domain"])
    status, payload = await client.post("/api/mail/addresses", json_body=body)
    if status >= 300 or not isinstance(payload, dict):
        return _mail_error(status, payload, tool="mail_get_address")
    return {"ok": True, "address": payload["address"], "created": True, "profile_id": profile_id, "next_step": next_step}


@register(
    "mail_wait_code",
    "等这个地址收到新邮件（只算上次取过之后的新邮件），直接回验证码 code 和验证链接 link。"
    "提交注册表单后调用；默认最多等 120 秒，没等到回 mail_timeout。code 为空时看 text 自己找。",
    MAIL_WAIT_ARGS,
    "action",
)
async def _mail_wait_code(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    address = str(args.get("address") or "").strip()
    if not address:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 address，先调 mail_get_address。"}
    try:
        raw_timeout = args.get("timeout_s")
        timeout_s = max(0.0, min(float(120 if raw_timeout is None else raw_timeout), 170.0))
    except (TypeError, ValueError):
        return {"ok": False, "reason": "invalid_argument", "detail": "timeout_s 要是秒数"}
    status, payload = await client.post(
        "/api/mail/wait",
        json_body={
            "address": address,
            "timeout_s": timeout_s,
            "from_contains": str(args.get("from_contains") or ""),
            "subject_contains": str(args.get("subject_contains") or ""),
        },
        timeout=ACTION_TIMEOUT_S,
    )
    if status >= 300 or not isinstance(payload, dict):
        return _mail_error(status, payload, tool="mail_wait_code")
    if not payload.get("found"):
        return {"ok": False, "reason": "mail_timeout", "detail": f"{timeout_s:.0f} 秒内 {address} 没有收到新邮件。"}
    message = payload.get("message") or {}
    return {"ok": True, "address": address, **_mail_summary(message, text_limit=1500)}


@register(
    "mail_list_messages",
    "列出这个地址最近收到的邮件（新的在前），每封带提取出的 code / link 和正文开头。用来回看已经取过的验证码或邮件内容。",
    MAIL_LIST_ARGS,
    "action",
)
async def _mail_list_messages(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    address = str(args.get("address") or "").strip()
    if not address:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 address，先调 mail_get_address。"}
    limit = max(1, min(int(args.get("limit") or 5), 20))
    status, payload = await client.get(f"/api/mail/messages?address={quote(address, safe='')}&limit={limit}")
    if status >= 300 or not isinstance(payload, dict):
        return _mail_error(status, payload, tool="mail_list_messages")
    messages = [_mail_summary(m, text_limit=500) for m in payload.get("messages") or []]
    return {"ok": True, "address": address, "count": len(messages), "messages": messages}


# ── Tools: profile / group / proxy management (action layer) ─────────────────
#
# Writes go through a field whitelist so a typo fails loudly instead of being ignored.

_WRITABLE_PROFILE_FIELDS = (
    "name", "platform", "group_name", "proxy_id", "device_profile", "timezone",
    "locale", "account_platform", "startup_urls", "color_scheme", "tags",
    "notes", "warmup_persona", "cookies_json", "proxy", "launch_args", "headless",
    "humanize", "human_preset", "geoip", "auto_launch",
)

_PROFILE_WRITE_PROPS: dict[str, Any] = {
    "name": {"type": "string", "description": "画像名称（只用来自己识别）"},
    "platform": {"type": "string", "enum": ["windows", "macos", "linux"], "description": "设备系统；新建时不填就用本机系统（本地版只能启动和本机同系统的画像）"},
    "group_name": {"type": "string", "description": "分组名称（先用 list_groups 查；没有就先 create_group）"},
    "proxy_id": {"type": "string", "description": "list_proxies 里的 proxy_id；不填表示不改/直连"},
    "device_profile": {"type": "string", "description": "设备模板 id（list_device_templates 查）"},
    "timezone": {"type": "string", "description": "例如 America/New_York；不填跟随出口 IP"},
    "locale": {"type": "string", "description": "例如 en-US；不填跟随出口 IP"},
    "account_platform": {"type": "string", "description": "这个画像对应的账号平台，如 Amazon"},
    "startup_urls": {"type": "array", "items": {"type": "string"}, "maxItems": 20, "description": "启动时自动打开的 http/https 网址"},
    "color_scheme": {"type": "string", "enum": ["light", "dark", "no-preference"]},
    "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 20, "description": "标签（文字）"},
    "notes": {"type": "string", "description": "备注（自由文本）"},
    "warmup_persona": {"type": "string", "maxLength": 200, "description": "养号人设（一句话）"},
    "cookies_json": {"type": "string", "description": "要导入的 Cookie（JSON 数组字符串）；环境在运行时请用 browser_cookies"},
    "proxy": {"type": "string", "description": "直接写代理地址，如 socks5://user:pass@host:port；想复用代理库里的就用 proxy_id"},
    "launch_args": {"type": "array", "items": {"type": "string"}, "description": "额外的浏览器启动参数"},
    "headless": {"type": "boolean"},
    "humanize": {"type": "boolean", "description": "拟人化输入/鼠标"},
    "human_preset": {"type": "string", "enum": ["default", "careful"]},
    "geoip": {"type": "boolean", "description": "时区/语言是否跟随出口 IP"},
    "auto_launch": {"type": "boolean", "description": "Manager 启动时自动打开"},
}

CREATE_PROFILE_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": dict(_PROFILE_WRITE_PROPS),
    "required": ["name"],
}

UPDATE_PROFILE_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {"profile_id": {"type": "string", "description": "画像 id（先用 list_profiles 查）"}, **_PROFILE_WRITE_PROPS},
    "required": ["profile_id"],
}


def _profile_write_body(args: dict[str, Any], *, creating: bool) -> tuple[dict[str, Any], dict[str, Any] | None]:
    allowed = set(_WRITABLE_PROFILE_FIELDS) | ({"profile_id"} if not creating else set())
    unknown = sorted(set(args) - allowed)
    if unknown:
        return {}, {
            "ok": False,
            "reason": "invalid_argument",
            "detail": f"不支持的字段：{', '.join(unknown)}。可改的字段只有：{', '.join(_WRITABLE_PROFILE_FIELDS)}。",
        }
    body: dict[str, Any] = {}
    for key in _WRITABLE_PROFILE_FIELDS:
        if key not in args or args[key] is None:
            continue
        value = args[key]
        if key == "startup_urls":
            urls = [str(u).strip() for u in value] if isinstance(value, list) else []
            bad = [u for u in urls if not u.lower().startswith(("http://", "https://"))]
            if bad:
                return {}, {"ok": False, "reason": "invalid_argument", "detail": f"启动网址只允许 http/https：{bad[0]}"}
            body[key] = urls
        elif key == "tags":
            body[key] = [{"tag": str(t).strip()} for t in value if str(t).strip()] if isinstance(value, list) else []
        else:
            body[key] = value
    return body, None


async def _with_proxy_from_library(client: RestClient, body: dict[str, Any], *, tool: str) -> dict[str, Any] | None:
    """Pair ``proxy_id`` with the saved proxy's address (the Manager requires both).

    The address, credentials included, is read and written server-side; it never
    appears in what the agent sees. Returns an error result, or None on success.
    """
    proxy_id = body.get("proxy_id")
    if not proxy_id:
        return None
    presets, err = await _get_or_error(client, "/api/proxy-presets", tool)
    if err:
        return err
    match = next((p for p in presets if isinstance(p, dict) and p.get("id") == proxy_id), None)
    if match is None:
        return {"ok": False, "reason": "not_found", "detail": f"找不到代理 {proxy_id}：先用 list_proxies 查 proxy_id，或 create_proxy 新建。"}
    body["proxy"] = match.get("proxy")
    return None


@register(
    "create_profile",
    "新建一个画像（环境）。只需要名称，其余有默认值；可选分组、代理（proxy_id）、设备系统、设备模板、时区、语言、账号平台、启动网址、标签。不能写 Cookie、备注，也不能直接填代理账密（要用代理先 create_proxy）。受授权环境数量限制。",
    CREATE_PROFILE_ARGS,
    "action",
)
async def _create_profile(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    body, err = _profile_write_body(args, creating=True)
    if err:
        return err
    if not str(body.get("name") or "").strip():
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 name。"}
    err = await _with_proxy_from_library(client, body, tool="create_profile")
    if err:
        return err
    if not body.get("platform"):
        # The API defaults to windows, which a Mac or Linux install cannot launch.
        s_status, host = await client.get("/api/status")
        host_os = host.get("host_os") if s_status < 300 and isinstance(host, dict) else None
        if host_os in ("windows", "macos", "linux"):
            body["platform"] = host_os
    status, payload = await client.post("/api/profiles", json_body=body, timeout=ACTION_TIMEOUT_S)
    if status >= 300:
        return error_result(status, payload, tool="create_profile")
    return {"ok": True, "profile": shape_profile(payload)}


@register(
    "update_profile",
    "修改画像的名称、分组、代理、设备系统/模板、时区、语言、账号平台、启动网址、颜色模式或标签。只给要改的字段。运行中的画像改动要先 stop_profile。备注、养号人设、Cookie（cookies_json）、直连代理地址也能改。",
    UPDATE_PROFILE_ARGS,
    "action",
)
async def _update_profile(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    body, err = _profile_write_body(args, creating=False)
    if err:
        return err
    if not body:
        return {"ok": False, "reason": "invalid_argument", "detail": "没有要改的字段。"}
    err = await _with_proxy_from_library(client, body, tool="update_profile")
    if err:
        return err
    status, payload = await client.put(f"/api/profiles/{quote(profile_id, safe='')}", json_body=body, timeout=ACTION_TIMEOUT_S)
    if status >= 300:
        return error_result(status, payload, tool="update_profile")
    return {"ok": True, "profile": shape_profile(payload)}


@register(
    "apply_device_template",
    "把一个设备模板（屏幕、显卡、CPU、内存）套到画像上；模板 id 用 list_device_templates 查。运行中的画像要先 stop_profile。",
    {
        "type": "object",
        "properties": {
            "profile_id": {"type": "string", "description": "画像 id"},
            "template_id": {"type": "string", "description": "list_device_templates 里的模板 id"},
        },
        "required": ["profile_id", "template_id"],
    },
    "action",
)
async def _apply_device_template(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    template_id = str(args.get("template_id") or "").strip()
    if not template_id:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 template_id，先用 list_device_templates 查。"}
    status, payload = await client.post(
        f"/api/profiles/{quote(profile_id, safe='')}/apply-device-template",
        json_body={"template_id": template_id},
        timeout=ACTION_TIMEOUT_S,
    )
    if status >= 300:
        return error_result(status, payload, tool="apply_device_template")
    return {"ok": True, "profile": shape_profile(payload)}


@register(
    "regenerate_fingerprint",
    "给画像换一个新的指纹种子（Canvas、WebGL、音频、字体等噪声随之变化）。账号已经在用的画像别随便换：网站会看到“设备变了”。运行中的画像要先 stop_profile。",
    PROFILE_ID_ARGS,
    "action",
)
async def _regenerate_fingerprint(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    seed = secrets.randbelow(2**31 - 1) + 1
    status, payload = await client.put(
        f"/api/profiles/{quote(profile_id, safe='')}", json_body={"fingerprint_seed": seed}, timeout=ACTION_TIMEOUT_S
    )
    if status >= 300:
        return error_result(status, payload, tool="regenerate_fingerprint")
    return {"ok": True, "profile": shape_profile(payload)}


@register(
    "reset_profile",
    "一键重置环境：把这个画像变成一个全新的浏览器——Cookie、登录状态、LocalStorage/IndexedDB、历史、缓存、Service Worker 全部删除（不可恢复），"
    "并重新随机生成指纹（种子、设备、分辨率、显卡、CPU、内存、UA）；时区和语言清空，下次启动按代理出口 IP 自动匹配。"
    "名称、分组、备注、标签、代理绑定和换 IP 链接都保留。运行中会先正常关闭。注册失败想换个干净环境、又要留着同一个代理 IP 时用它。"
    "必须带 confirm=true。bindings 决定这个画像的邮箱地址和保险库账号：unbind（默认，保留但解绑）/ keep（仍绑在这个画像）/ delete（删除记录）。",
    {
        "type": "object",
        "properties": {
            "profile_id": {"type": "string", "description": "画像 id（先用 list_profiles 查）"},
            "confirm": {"type": "boolean", "description": "必须为 true：浏览器数据删除后不可恢复"},
            "bindings": {
                "type": "string",
                "enum": ["unbind", "keep", "delete"],
                "description": "邮箱地址和保险库账号怎么处理，默认 unbind",
            },
        },
        "required": ["profile_id", "confirm"],
    },
    "action",
)
async def _reset_profile(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    if args.get("confirm") is not True:
        return {
            "ok": False,
            "reason": "invalid_argument",
            "detail": "重置会删除这个画像的全部浏览器数据（Cookie、登录状态、历史），不可恢复；确认后带 confirm=true 再调。",
        }
    bindings = str(args.get("bindings") or "unbind")
    if bindings not in ("unbind", "keep", "delete"):
        return {"ok": False, "reason": "invalid_argument", "detail": "bindings 只能是 unbind / keep / delete。"}
    status, payload = await client.post(
        f"/api/profiles/{quote(profile_id, safe='')}/reset",
        json_body={"confirm": True, "bindings": bindings},
        timeout=ACTION_TIMEOUT_S,
    )
    if status >= 300:
        return error_result(status, payload, tool="reset_profile")
    return {
        "ok": True,
        "profile": shape_profile(payload.get("profile") or {}),
        "was_running": payload.get("was_running"),
        "files_removed": payload.get("files_removed"),
        "new_fingerprint_seed": payload.get("new_fingerprint_seed"),
        "device_profile": payload.get("device_profile"),
        "bindings": payload.get("bindings"),
        "mail_addresses": payload.get("mail_addresses"),
        "vault_entries": payload.get("vault_entries"),
        "next_step": "环境已是全新浏览器，代理没变；需要的话用 open_browser 重新打开。",
    }


@register(
    "create_group",
    "新建一个分组。名称已存在会回 conflict。",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "分组名称（1~64 个字）"},
            "color": {"type": "string", "description": "可选：十六进制颜色，如 #3b82f6"},
        },
        "required": ["name"],
    },
    "action",
)
async def _create_group(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name") or "").strip()
    if not name:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 name。"}
    body: dict[str, Any] = {"name": name}
    if args.get("color"):
        body["color"] = str(args["color"])
    status, payload = await client.post("/api/groups", json_body=body)
    if status >= 300:
        return error_result(status, payload, tool="create_group")
    return {"ok": True, "group": {"id": payload.get("id"), "name": payload.get("name"), "color": payload.get("color")}}


@register(
    "move_profiles",
    "把一批画像移到某个分组（先用 list_groups 确认分组存在）。单个失败不影响其他，结果里逐个说明。",
    {
        "type": "object",
        "properties": {
            "profile_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 100},
            "group_name": {"type": "string", "description": "目标分组名称"},
        },
        "required": ["profile_ids", "group_name"],
    },
    "action",
)
async def _move_profiles(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    ids = [str(i).strip() for i in (args.get("profile_ids") or []) if str(i).strip()]
    group = str(args.get("group_name") or "").strip()
    if not ids or not group:
        return {"ok": False, "reason": "invalid_argument", "detail": "需要 profile_ids 和 group_name。"}
    moved: list[str] = []
    failed: list[dict[str, Any]] = []
    for profile_id in ids[:100]:
        status, payload = await client.put(
            f"/api/profiles/{quote(profile_id, safe='')}", json_body={"group_name": group}, timeout=ACTION_TIMEOUT_S
        )
        if status < 300:
            moved.append(profile_id)
        else:
            failed.append({"profile_id": profile_id, **{k: v for k, v in error_result(status, payload, tool="move_profiles").items() if k != "ok"}})
    return {"ok": not failed, "moved": moved, "failed": failed}


@register(
    "restore_profile",
    "把回收站里的画像恢复回来（先用 list_trash 查 id）。",
    PROFILE_ID_ARGS,
    "action",
)
async def _restore_profile(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    status, payload = await client.post(f"/api/profiles/{quote(profile_id, safe='')}/restore")
    if status >= 300:
        return error_result(status, payload, tool="restore_profile")
    return {"ok": True, "profile": shape_profile(payload)}


@register(
    "create_proxy",
    "保存一个代理到代理库（之后用 proxy_id 绑定到画像）。账号密码只写不读：保存后任何工具都看不到它。格式如 socks5://user:pass@host:port。",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "代理名称（1~64 个字）"},
            "proxy": {"type": "string", "description": "代理地址，如 socks5://user:pass@host:port 或 http://host:port"},
        },
        "required": ["name", "proxy"],
    },
    "action",
)
async def _create_proxy(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name") or "").strip()
    proxy = str(args.get("proxy") or "").strip()
    if not name or not proxy:
        return {"ok": False, "reason": "invalid_argument", "detail": "需要 name 和 proxy。"}
    status, payload = await client.post("/api/proxy-presets", json_body={"name": name, "proxy": proxy, "mode": "custom"})
    if status >= 300:
        return error_result(status, payload, tool="create_proxy")
    return {"ok": True, "proxy": {"proxy_id": payload.get("id"), "name": payload.get("name"), "endpoint": sanitize_proxy(payload.get("proxy"))}}


@register(
    "stop_all_profiles",
    "关闭所有正在运行的画像浏览器（逐个关，结果里逐个说明）。有人在接管的画像会被跳过并说明。",
    NO_ARGS,
    "action",
)
async def _stop_all_profiles(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    payload, err = await _get_or_error(client, "/api/profiles", "stop_all_profiles")
    if err:
        return err
    stopped: list[str] = []
    failed: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("status") != "running":
            continue
        profile_id = str(item.get("id"))
        status, body = await client.post(f"/api/profiles/{quote(profile_id, safe='')}/stop", timeout=ACTION_TIMEOUT_S)
        if status < 300:
            stopped.append(profile_id)
        else:
            failed.append({"profile_id": profile_id, **{k: v for k, v in error_result(status, body, tool="stop_profile").items() if k != "ok"}})
    return {"ok": not failed, "stopped": stopped, "failed": failed}


# ── Tools: browser layer (registered only when mcp.mode == "automation") ─────


_BATCH_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "profile_id": {"type": "string", "description": "画像 id"},
        "batch_id": {"type": "string", "description": "list_warmup_scripts 里的批次 id"},
    },
    "required": ["profile_id", "batch_id"],
}


async def _batch_decision(client: RestClient, args: dict[str, Any], verb: str) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    batch_id = str(args.get("batch_id") or "").strip()
    if not batch_id:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 batch_id（list_warmup_scripts 查）。"}
    status, payload = await client.post(
        f"/api/profiles/{quote(profile_id, safe='')}/warmup/scripts/batches/{quote(batch_id, safe='')}/{verb}"
    )
    if status >= 300:
        return error_result(status, payload, tool=f"{verb}_warmup_batch")
    return payload if isinstance(payload, dict) else {"ok": True}


@register("approve_warmup_batch", "批准一批 AI 养号剧本，之后 run_warmup 才会用它们。", _BATCH_ARGS, "action")
async def _approve_warmup_batch(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _batch_decision(client, args, "approve")


@register("reject_warmup_batch", "驳回一批 AI 养号剧本。", _BATCH_ARGS, "action")
async def _reject_warmup_batch(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _batch_decision(client, args, "reject")


_PROPOSAL_ARGS: dict[str, Any] = {
    "type": "object",
    "properties": {"proposal_id": {"type": "string", "description": "get_evolution 里待批准的提案 id"}},
    "required": ["proposal_id"],
}


async def _proposal_decision(client: RestClient, args: dict[str, Any], verb: str, tool: str) -> dict[str, Any]:
    proposal_id = str(args.get("proposal_id") or "").strip()
    if not proposal_id:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 proposal_id（get_evolution 查）。"}
    status, payload = await client.post(f"/api/evolution/proposals/{quote(proposal_id, safe='')}/{verb}")
    if status >= 300:
        return error_result(status, payload, tool=tool)
    return {"ok": True, "proposal": payload}


@register("approve_evolution_proposal", "批准一条自对抗进化提案，让它生效。", _PROPOSAL_ARGS, "action")
async def _approve_evolution_proposal(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _proposal_decision(client, args, "approve", "approve_evolution_proposal")


@register("dismiss_evolution_proposal", "驳回一条自对抗进化提案。", _PROPOSAL_ARGS, "action")
async def _dismiss_evolution_proposal(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _proposal_decision(client, args, "dismiss", "dismiss_evolution_proposal")


@register(
    "get_cdp_endpoint",
    "拿一个正在运行（debug 模式）的画像的 CDP 连接信息：HTTP/WebSocket 端点、当前标签页、"
    "Playwright / playwright-mcp / chrome-devtools-mcp 的接入写法。没在跑回 not_running，"
    "是 manual 模式启动的回 cdp_unavailable。",
    PROFILE_ID_ARGS,
    "browser",
)
async def _get_cdp_endpoint(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    lease_err = await _ensure_lease(client, profile_id)
    if lease_err:
        return lease_err
    return await _cdp_endpoint_info(client, profile_id, tool="get_cdp_endpoint")


async def _ensure_lease(client: RestClient, profile_id: str) -> dict[str, Any] | None:
    """Take (or renew) this caller's control lease on the profile.

    ``None`` on success, else a structured error (``profile_leased`` when a
    person or another agent has the profile).
    """
    status, payload = await client.post(
        f"/api/profiles/{quote(profile_id, safe='')}/lease",
        json_body={"holder": _CALLER.get()},
    )
    if status >= 300:
        return error_result(status, payload, tool="lease")
    return None


async def _resolve_profile(client: RestClient, ref: str) -> tuple[str, dict[str, Any] | None]:
    """Profile id from an id or an exact, unique name."""
    by_id_status, by_id = await client.get(f"/api/profiles/{quote(ref, safe='')}")
    if by_id_status == 200 and isinstance(by_id, dict) and by_id.get("id") == ref:
        return ref, None
    status, payload = await client.get("/api/profiles")
    if status >= 300 or not isinstance(payload, list):
        return "", error_result(status, payload, tool="open_browser")
    profiles = [p for p in payload if isinstance(p, dict)]
    by_id = [p for p in profiles if p.get("id") == ref]
    if by_id:
        return str(by_id[0]["id"]), None
    by_name = [p for p in profiles if p.get("name") == ref]
    if len(by_name) == 1:
        return str(by_name[0]["id"]), None
    if len(by_name) > 1:
        ids = ", ".join(str(p.get("id")) for p in by_name)
        return "", {
            "ok": False,
            "reason": "invalid_argument",
            "detail": f"有多个画像叫「{ref}」，请改用 id：{ids}",
        }
    return "", {
        "ok": False,
        "reason": "not_found",
        "detail": f"没有 id 或名称是「{ref}」的画像，先用 list_profiles 查。",
    }


@register(
    "open_browser",
    "一步到位：确保画像的浏览器以 debug 模式在跑，并回 CDP 连接信息（同 get_cdp_endpoint）。"
    "画像参数可以是 id 或名称。已经以 debug 模式在跑就直接回信息（started=false），不会重启；"
    "是 manual 模式在跑回 already_running，需要先 stop_profile。撞授权单座位回 seat_busy。",
    OPEN_BROWSER_ARGS,
    "browser",
)
async def _open_browser(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    ref = str(args.get("profile") or "").strip()
    if not ref:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 profile（画像 id 或名称），先用 list_profiles 查。"}
    profile_id, err = await _resolve_profile(client, ref)
    if err:
        return err
    lease_err = await _ensure_lease(client, profile_id)
    if lease_err:
        return lease_err
    quoted = quote(profile_id, safe="")
    status, payload = await client.get(f"/api/profiles/{quoted}/status")
    if status >= 300 or not isinstance(payload, dict):
        return error_result(status, payload, tool="open_browser")
    started = False
    if payload.get("status") == "running":
        if not payload.get("cdp_url"):
            return {
                "ok": False,
                "reason": "already_running",
                "detail": "这个画像已在以 manual 模式运行（没有 CDP）。不会替你重启；确认可以关掉后先 stop_profile，再调 open_browser。",
            }
    else:
        status, payload = await client.post(
            f"/api/profiles/{quoted}/launch",
            json_body={"launch_mode": "debug"},
            timeout=ACTION_TIMEOUT_S,
        )
        if status >= 300:
            return error_result(status, payload, tool="open_browser")
        started = True
    info = await _cdp_endpoint_info(client, profile_id, tool="open_browser")
    if not info.get("ok"):
        return info
    return {
        **info,
        "started": started,
        "next_step": "已就绪。直接用 browser_navigate / browser_snapshot 操作页面，或把 cdp_http_endpoint 交给 Playwright。",
    }


# ── Tools: page control (browser layer; run inside the Manager) ───────────────

PAGE_PROFILE_PROP: dict[str, Any] = {
    "type": "string",
    "description": "画像 id 或名称（需已用 open_browser 以 debug 模式打开）",
}


def _page_schema(extra: dict[str, Any] | None = None, required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"profile": PAGE_PROFILE_PROP, **(extra or {})},
        "required": ["profile", *required],
    }


async def _page_call(
    client: RestClient, args: dict[str, Any], action: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Resolve the profile, hold its lease, and run one page action in the Manager."""
    ref = str(args.get("profile") or "").strip()
    if not ref:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 profile（画像 id 或名称），先用 list_profiles 查。"}
    profile_id, err = await _resolve_profile(client, ref)
    if err:
        return err
    lease_err = await _ensure_lease(client, profile_id)
    if lease_err:
        return lease_err
    status, payload = await client.post(
        f"/api/profiles/{quote(profile_id, safe='')}/page/{action}",
        json_body=body or {},
        timeout=ACTION_TIMEOUT_S,
    )
    if status >= 300 or not isinstance(payload, dict):
        return error_result(status, payload, tool=f"browser_{action}")
    return {"ok": True, "profile_id": profile_id, **payload}


@register(
    "browser_navigate",
    "让画像当前标签页打开一个网址（只允许 http/https）。返回最终 url、标题、HTTP 状态。之后用 browser_snapshot 看页面。",
    _page_schema({"url": {"type": "string", "description": "要打开的 http(s) 网址"}}, ("url",)),
    "browser",
)
async def _browser_navigate(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(client, args, "navigate", {"url": args.get("url")})


@register(
    "browser_snapshot",
    "读当前页面：返回文字轮廓，可交互元素带 ref（如 [e3] button \"登录\"）。点击/输入都要用最近一次快照里的 ref。页面变化后要重新快照。"
    "长页面会被截断（truncated=true）：往下 browser_scroll 后用 viewport_only=true 只看当前屏；要读正文用 browser_get_text。",
    _page_schema(
        {"viewport_only": {"type": "boolean", "default": False, "description": "只列出当前视口内的内容（滚动后翻页用）"}}
    ),
    "browser",
)
async def _browser_snapshot(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(client, args, "snapshot", {"viewport_only": bool(args.get("viewport_only"))})


@register(
    "browser_get_text",
    "读当前页面（或某个 ref 元素）的纯文字，分页返回：用返回的 next_offset 作为下次的 offset 接着读。读文章、结果列表正文用它，比快照省。"
    "默认只读页面的主体内容（跳过菜单和页脚），要整页文字设 whole_page=true。",
    _page_schema(
        {
            "ref": {"type": "string", "description": "可选：只读这个元素（快照 ref 或语义选择器）"},
            "offset": {"type": "integer", "default": 0, "description": "从第几个字符开始"},
            "max_chars": {"type": "integer", "default": 6000, "description": "本次最多返回多少字符，100~20000"},
            "whole_page": {"type": "boolean", "default": False, "description": "读整页文字（含菜单页脚），默认只读主体内容"},
        }
    ),
    "browser",
)
async def _browser_get_text(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(
        client, args, "get_text",
        {
            "ref": args.get("ref"),
            "offset": args.get("offset") or 0,
            "max_chars": args.get("max_chars") or 6000,
            "whole_page": bool(args.get("whole_page")),
        },
    )


@register(
    "browser_click",
    "点击一个元素：最近一次 browser_snapshot 里的 ref（如 e3），或语义选择器（text=登录、role=button[name=\"登录\"] 等，页面跳转后依然有效）。点击若打开新标签页会自动切过去。",
    _page_schema({"ref": {"type": "string", "description": "快照里的元素引用（如 e3），或语义选择器：text=登录 / role=button[name=\"登录\"] / label=邮箱 / placeholder=… / css=…（必须恰好匹配一个可见元素）"}}, ("ref",)),
    "browser",
)
async def _browser_click(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(client, args, "click", {"ref": args.get("ref")})


@register(
    "browser_type",
    "往输入框（或下拉框，按选项文字选）填内容。默认替换原有内容；submit=true 填完按回车。",
    _page_schema(
        {
            "ref": {"type": "string", "description": "快照里的元素引用（如 e3），或语义选择器：text=登录 / role=button[name=\"登录\"] / label=邮箱 / placeholder=… / css=…（必须恰好匹配一个可见元素）"},
            "text": {"type": "string", "description": "要填的文字"},
            "submit": {"type": "boolean", "default": False, "description": "填完是否按回车提交"},
        },
        ("ref", "text"),
    ),
    "browser",
)
async def _browser_type(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(
        client, args, "type",
        {"ref": args.get("ref"), "text": args.get("text"), "submit": bool(args.get("submit"))},
    )


@register(
    "browser_press_key",
    "按一个键或组合键，如 Enter、Tab、Escape、ArrowDown、Control+A。作用在当前焦点上。",
    _page_schema({"key": {"type": "string", "description": "键名，如 Enter / Control+A"}}, ("key",)),
    "browser",
)
async def _browser_press_key(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(client, args, "press_key", {"key": args.get("key")})


@register(
    "browser_scroll",
    "滚动当前页面。direction 为 up/down/left/right，amount 是像素（默认 600）。",
    _page_schema(
        {
            "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "default": "down"},
            "amount": {"type": "integer", "default": 600, "description": "滚动像素，1~5000"},
        }
    ),
    "browser",
)
async def _browser_scroll(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(
        client, args, "scroll",
        {"direction": args.get("direction") or "down", "amount": args.get("amount") or 600},
    )


@register(
    "browser_screenshot",
    "给当前页面截图（默认 jpeg，视口范围；full_page=true 截整页）。图片随结果返回。",
    _page_schema(
        {
            "full_page": {"type": "boolean", "default": False},
            "format": {"type": "string", "enum": ["jpeg", "png"], "default": "jpeg"},
        }
    ),
    "browser",
)
async def _browser_screenshot(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(
        client, args, "screenshot",
        {"full_page": bool(args.get("full_page")), "format": args.get("format") or "jpeg"},
    )


@register(
    "browser_wait_for",
    "等条件成立再往下走（给了几个就全部要满足）：text 出现、text_gone 消失、url 包含某段、selector（语义选择器）出现，"
    "或单纯等 ms 毫秒。每个条件最多等 timeout_ms（默认 15000，最大 30000）。比固定等待可靠。",
    _page_schema(
        {
            "text": {"type": "string", "description": "等它出现的文字"},
            "text_gone": {"type": "string", "description": "等它消失的文字（如加载提示）"},
            "url": {"type": "string", "description": "等当前网址包含这段文字"},
            "selector": {"type": "string", "description": "等它可见：text=… / role=button[name=\"…\"] / css=…"},
            "ms": {"type": "integer", "description": "单纯等待的毫秒数"},
            "timeout_ms": {"type": "integer", "default": 15000, "description": "每个条件的最长等待，100~30000"},
        }
    ),
    "browser",
)
async def _browser_wait_for(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(
        client, args, "wait_for",
        {key: args.get(key) for key in ("text", "text_gone", "url", "selector", "ms", "timeout_ms")},
    )


@register(
    "browser_dialog",
    "处理页面弹出的 JS 对话框（alert / confirm / prompt / beforeunload）。动作返回里出现 dialog 字段就必须先处理它，"
    "否则页面被冻住、其他操作都会回 dialog_open。accept=确定，dismiss=取消；prompt 可用 text 填内容。2 分钟没人处理会自动取消。",
    _page_schema(
        {
            "action": {"type": "string", "enum": ["accept", "dismiss"]},
            "text": {"type": "string", "description": "prompt 对话框要填的内容（仅 accept 时有效）"},
        },
        ("action",),
    ),
    "browser",
)
async def _browser_dialog(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(client, args, "dialog", {"action": args.get("action"), "text": args.get("text")})


@register(
    "browser_batch",
    "一次调用按顺序做最多 20 步，省掉来回往返。steps 是数组，每步 {\"do\": 动词, ...该动词自己的参数}，动词："
    "navigate(url) click(ref) type(ref,text,submit?) press_key(key) scroll(direction?,amount?) "
    "wait_for(text/text_gone/url/selector/ms) back get_text(ref?,offset?,max_chars?) dialog(answer=accept|dismiss,text?) "
    "tabs(tab_action,index?,url?) upload(ref,paths)。页面跳转后 ref 会失效，所以跨页面的步骤请用语义选择器（text=… / role=…[name=…]）。"
    "某步出错或弹出对话框就停（stopped/stopped_at 会说明），最后默认附一次快照（snapshot_after=false 关闭）。",
    _page_schema(
        {
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": {"type": "object", "properties": {"do": {"type": "string"}}, "required": ["do"]},
                "description": "按顺序执行的步骤",
            },
            "snapshot_after": {"type": "boolean", "default": True, "description": "做完后附一次快照"},
            "viewport_only": {"type": "boolean", "default": False, "description": "附带的快照只看当前屏"},
            "stop_on_error": {"type": "boolean", "default": True, "description": "某步失败就停（false 则继续后面的步骤）"},
        },
        ("steps",),
    ),
    "browser",
)
async def _browser_batch(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(
        client, args, "batch",
        {
            "steps": args.get("steps"),
            "snapshot_after": args.get("snapshot_after", True),
            "viewport_only": bool(args.get("viewport_only")),
            "stop_on_error": args.get("stop_on_error", True),
        },
    )


@register(
    "browser_upload",
    "往文件输入框上传文件（ref 是 input[type=file]，或点它会弹出文件选择器的按钮）。"
    "为防止把本机文件传给网站，只允许上传「agent 文件目录」里的文件，路径要写完整；目录位置见 browser_downloads 的 files_dir。",
    _page_schema(
        {
            "ref": {"type": "string", "description": "文件输入框或上传按钮：快照 ref 或语义选择器"},
            "paths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10, "description": "要上传的文件的完整路径（必须在 agent 文件目录里，单个不超过 50 MB）"},
        },
        ("ref", "paths"),
    ),
    "browser",
)
async def _browser_upload(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(client, args, "upload", {"ref": args.get("ref"), "paths": args.get("paths")})


@register(
    "browser_downloads",
    "列出这个画像下载过的文件（自动保存到 agent 文件目录，返回完整路径、大小、状态），并告诉你目录在哪。点了下载按钮之后调它。",
    _page_schema(),
    "browser",
)
async def _browser_downloads(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(client, args, "downloads")


@register("browser_back", "当前标签页后退一步。", _page_schema(), "browser")
async def _browser_back(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(client, args, "back")


@register(
    "browser_tabs",
    "管理标签页：list 列出；new 新开（可带 url）；select 切换到 index；close 关闭 index。",
    _page_schema(
        {
            "action": {"type": "string", "enum": ["list", "new", "select", "close"], "default": "list"},
            "index": {"type": "integer", "description": "select/close 的标签页序号（从 0 开始）"},
            "url": {"type": "string", "description": "new 时可选的网址"},
        }
    ),
    "browser",
)
async def _browser_tabs(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(
        client, args, "tabs",
        {"action": args.get("action") or "list", "index": args.get("index"), "url": args.get("url")},
    )


# ── Tools: credential vault (browser layer) ──────────────────────────────────
#
# The agent signs up for accounts without ever holding a password: the Manager generates
# and stores it, the agent types a {{vault:…}} reference that the Manager resolves on the
# way to the page. Details in backend/vault.py. Mail comes from the mail_* tools above.


async def _profile_call(
    client: RestClient, args: dict[str, Any], method: str, suffix: str, body: dict[str, Any] | None = None,
    *, tool: str = "",
) -> dict[str, Any]:
    """Resolve the profile, call ``/api/profiles/{id}/{suffix}`` and pass the answer through."""
    ref = str(args.get("profile") or "").strip()
    if not ref:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 profile（画像 id 或名称），先用 list_profiles 查。"}
    profile_id, err = await _resolve_profile(client, ref)
    if err:
        return err
    path = f"/api/profiles/{quote(profile_id, safe='')}/{suffix}"
    status, payload = await client.request(method, path, json_body=body)
    if status >= 300 or not isinstance(payload, dict):
        return error_result(status, payload, tool=tool)
    if payload.get("ok") is False:
        return dict(payload)
    return {"profile_id": profile_id, **payload}


@register(
    "account_prepare",
    "注册新账号前一步到位：给这个画像新建一个邮箱地址（走「邮箱」页接好的邮箱服务器）+ 一个保险库条目（用户名、自动生成的强密码）。"
    "返回 email、username 和三个引用 refs（{{vault:…password}} 等）：往注册表单里填的时候，"
    "把引用原样写进 browser_type 的 text，Manager 会在服务端换成真值，密码不会经过你。"
    "提交后用 mail_wait_code(address=email) 取验证码或验证链接。",
    _page_schema(
        {
            "site": {"type": "string", "description": "要注册的网站域名，如 example.com"},
            "username": {"type": "string", "description": "可选：指定用户名；不填则随机生成"},
            "password_length": {"type": "integer", "default": 20, "description": "密码长度，12~64"},
            "symbols": {"type": "boolean", "default": True, "description": "密码里是否含符号（个别网站不允许时设 false）"},
            "domain": {"type": "string", "description": "可选：邮箱域名，不填随机选一个"},
        },
        ("site",),
    ),
    "browser",
)
async def _account_prepare(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    ref = str(args.get("profile") or "").strip()
    if not ref:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 profile（画像 id 或名称），先用 list_profiles 查。"}
    profile_id, err = await _resolve_profile(client, ref)
    if err:
        return err
    address_body: dict[str, Any] = {"profile_id": profile_id}
    if args.get("domain"):
        address_body["domain"] = str(args["domain"])
    status, payload = await client.post("/api/mail/addresses", json_body=address_body)
    if status >= 300 or not isinstance(payload, dict):
        return _mail_error(status, payload, tool="account_prepare")
    address = str(payload["address"])
    status, payload = await client.post(
        f"/api/profiles/{quote(profile_id, safe='')}/vault",
        json_body={
            "site": args.get("site"), "username": args.get("username"), "email": address,
            "generate_username": not args.get("username"),
            "password_length": args.get("password_length") or 20, "symbols": args.get("symbols", True) is not False,
        },
    )
    if status >= 300 or not isinstance(payload, dict):
        return error_result(status, payload, tool="account_prepare")
    if payload.get("ok") is False:
        return dict(payload)
    return {
        "ok": True, "profile_id": profile_id, "email": address, "entry": payload["entry"],
        "next_step": (
            "用 browser_navigate 打开注册页，browser_type 把 refs 里的引用原样填进邮箱/用户名/密码；提交后 "
            "mail_wait_code(address=email) 取验证码。遇到图形验证码或手机短信验证：停下来，请用户在面板里接管处理。"
        ),
    }


@register(
    "vault_create",
    "为一个网站新建保险库条目：Manager 生成强密码并加密保存，你只拿到引用（{{vault:…}}），拿不到明文。"
    "已有邮箱地址要用时通过 email 传入；要一步拿邮箱加条目就用 account_prepare。",
    _page_schema(
        {
            "site": {"type": "string", "description": "网站域名"},
            "username": {"type": "string", "description": "可选：用户名"},
            "email": {"type": "string", "description": "可选：账号用的邮箱"},
            "password_length": {"type": "integer", "default": 20},
            "symbols": {"type": "boolean", "default": True},
        },
        ("site",),
    ),
    "browser",
)
async def _vault_create(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _profile_call(
        client, args, "POST", "vault",
        {
            "site": args.get("site"), "username": args.get("username"), "email": args.get("email"),
            "password_length": args.get("password_length") or 20, "symbols": args.get("symbols", True) is not False,
        },
        tool="vault_create",
    )


@register("vault_list", "列出这个画像的保险库条目（网站、用户名、邮箱、状态、引用），不含密码。登录已注册的网站时用它找引用。", _page_schema(), "browser")
async def _vault_list(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _profile_call(client, args, "GET", "vault", tool="vault_list")


@register(
    "vault_mark",
    "更新条目的状态：registered（已提交注册）/ verified（邮箱已验证、账号可用）/ failed；可附备注。",
    _page_schema(
        {
            "entry_id": {"type": "string", "description": "条目 id"},
            "status": {"type": "string", "enum": ["new", "registered", "verified", "failed"]},
            "notes": {"type": "string", "description": "可选备注（不要写密码）"},
        },
        ("entry_id",),
    ),
    "browser",
)
async def _vault_mark(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    entry_id = str(args.get("entry_id") or "").strip()
    if not entry_id:
        return {"ok": False, "reason": "invalid_argument", "detail": "缺少 entry_id。"}
    return await _profile_call(
        client, args, "PATCH", f"vault/{quote(entry_id, safe='')}",
        {"status": args.get("status"), "notes": args.get("notes")}, tool="vault_mark",
    )


# ── English summaries (tool lists show "中文 | English") ──────────────────────

# ── Tools: delete / approve / page extras (no human-only gates) ──────────────


@register(
    "delete_profile",
    "删除画像：先停掉浏览器，再放进回收站（7 天内可用 restore_profile 恢复）。要彻底删掉用 purge_profile。",
    PROFILE_ID_ARGS,
    "browser",
)
async def _delete_profile(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    status, payload = await client.request("DELETE", f"/api/profiles/{quote(profile_id, safe='')}", timeout=ACTION_TIMEOUT_S)
    if status >= 300:
        return error_result(status, payload, tool="delete_profile")
    return {"ok": True, "profile_id": profile_id, "in_trash": True}


@register(
    "purge_profile",
    "彻底删除画像：数据库记录和整个用户数据目录（登录态、Cookie）一并清除，不可恢复。普通删除用 delete_profile。",
    PROFILE_ID_ARGS,
    "browser",
)
async def _purge_profile(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    status, payload = await client.request("DELETE", f"/api/profiles/{quote(profile_id, safe='')}/purge", timeout=ACTION_TIMEOUT_S)
    if status >= 300:
        return error_result(status, payload, tool="purge_profile")
    return {"ok": True, "profile_id": profile_id, "purged": True}


@register(
    "browser_hover",
    "把鼠标移到元素上（弹出菜单、悬浮提示）。ref 同 browser_click。",
    _page_schema({"ref": {"type": "string", "description": "快照 ref（如 e3）或语义选择器"}}, ("ref",)),
    "browser",
)
async def _browser_hover(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(client, args, "hover", {"ref": args.get("ref")})


@register(
    "browser_drag",
    "按住 ref 元素拖到 to_ref 元素上松开（滑块、排序、拖放上传区）。",
    _page_schema(
        {
            "ref": {"type": "string", "description": "起点：快照 ref 或语义选择器"},
            "to_ref": {"type": "string", "description": "终点：快照 ref 或语义选择器"},
        },
        ("ref", "to_ref"),
    ),
    "browser",
)
async def _browser_drag(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(client, args, "drag", {"ref": args.get("ref"), "to_ref": args.get("to_ref")})


@register(
    "browser_get_html",
    "读页面（或某个元素）的原始 HTML，分页返回（offset/max_chars，看 next_offset）。找不到元素、要看隐藏属性时用；平时读 browser_snapshot 更省。",
    _page_schema(
        {
            "ref": {"type": "string", "description": "可选：只读这个元素的 outerHTML"},
            "offset": {"type": "integer", "default": 0},
            "max_chars": {"type": "integer", "default": 6000, "description": "100~20000"},
        }
    ),
    "browser",
)
async def _browser_get_html(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(
        client, args, "get_html",
        {"ref": args.get("ref"), "offset": args.get("offset") or 0, "max_chars": args.get("max_chars") or 6000},
    )


@register(
    "browser_evaluate",
    "在页面里执行 JavaScript 并返回结果（可 JSON 化的值，超过 2 万字符会截断）。script 写表达式或箭头函数，如 () => document.title；"
    "给了 ref 时函数的参数就是那个元素，如 el => el.value。",
    _page_schema(
        {
            "script": {"type": "string", "description": "JS 表达式或箭头函数"},
            "ref": {"type": "string", "description": "可选：函数的第一个参数是这个元素"},
        },
        ("script",),
    ),
    "browser",
)
async def _browser_evaluate(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(client, args, "evaluate", {"script": args.get("script"), "ref": args.get("ref")})


@register(
    "browser_cookies",
    "读、写或清空这个画像的 Cookie（整个浏览器，不是单个标签页）。action=get 可用 domain 过滤或 urls 限定；"
    "set 传 cookies 数组（每项 name、value，加 url 或 domain+path）；clear 清空全部。",
    _page_schema(
        {
            "action": {"type": "string", "enum": ["get", "set", "clear"], "default": "get"},
            "domain": {"type": "string", "description": "get：只返回域名包含它的 Cookie"},
            "urls": {"type": "array", "items": {"type": "string"}, "description": "get：只返回对这些网址生效的 Cookie"},
            "cookies": {"type": "array", "items": {"type": "object"}, "description": "set：要写入的 Cookie"},
        }
    ),
    "browser",
)
async def _browser_cookies(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    return await _page_call(
        client, args, "cookies",
        {
            "action": args.get("action") or "get",
            "domain": args.get("domain"),
            "urls": args.get("urls"),
            "cookies": args.get("cookies"),
        },
    )


TOOL_EN: dict[str, str] = {
    "list_groups": "List groups with how many profiles each holds.",
    "list_running": "Profiles that are running now (id, name, mode); shows how many license seats are used.",
    "list_trash": "Profiles in the recycle bin (deleted within 7 days), recoverable with restore_profile.",
    "create_profile": "Create a profile (name required; optional group, proxy_id, platform, device template, timezone, locale, startup URLs, tags). No cookies or notes; subject to the license's profile limit.",
    "update_profile": "Change a profile's name, group, proxy, platform, device template, timezone, locale, startup URLs, color scheme or tags. Stop it first if it is running.",
    "apply_device_template": "Apply a device template (screen, GPU, CPU, memory) to a profile.",
    "regenerate_fingerprint": "Give a profile a new fingerprint seed. Do not use it on profiles whose account is already live.",
    "reset_profile": "Turn a profile into a brand-new browser: wipe cookies, logins, storage, history and cache (not recoverable) and roll a new fingerprint, keeping name, group, notes and the proxy. Needs confirm=true.",
    "create_group": "Create a group.",
    "move_profiles": "Move up to 100 profiles into a group; per-profile results.",
    "restore_profile": "Restore a profile from the recycle bin.",
    "delete_profile": "Stop the profile and move it to the recycle bin (restorable for 7 days).",
    "purge_profile": "Permanently delete a profile and its whole data directory. Not recoverable.",
    "approve_warmup_batch": "Approve a batch of AI warm-up scripts so run_warmup can use them.",
    "reject_warmup_batch": "Reject a batch of AI warm-up scripts.",
    "approve_evolution_proposal": "Approve a pending self-adversarial evolution proposal.",
    "dismiss_evolution_proposal": "Dismiss a pending evolution proposal.",
    "browser_hover": "Move the mouse over an element (menus, tooltips).",
    "browser_drag": "Drag one element onto another (sliders, sorting, drop zones).",
    "browser_get_html": "Raw HTML of the page or one element, paged. Prefer browser_snapshot for reading.",
    "browser_evaluate": "Run JavaScript in the page and return its JSON result; with ref the function receives that element.",
    "browser_cookies": "Read, write or clear the profile's cookies (get / set / clear).",
    "create_proxy": "Save a proxy to the proxy library (credentials are write-only); bind it to profiles via proxy_id.",
    "stop_all_profiles": "Stop every running profile browser; per-profile results.",
    "check_proxy_exit_ip": "Check a new connection through the selected proxy route without rotating its IP.",
    "list_proxies": "List saved proxy endpoints and their rotation capabilities without credentials.",
    "get_proxy_capabilities": "Discover IP rotation support, cooldown and affected profiles.",
    "get_proxy_rotation_result": "Read a rotation job without triggering another refresh request.",
    "rotate_proxy_ip": "Rotate a SOCKS5 exit via its configured supplier link and verify the actual route.",
    "manager_status": "Overview: versions, running browsers, profile count, active automation. Call this first.",
    "list_profiles": "List profiles, 200 per page (page/limit; filter by group_name, query, status). Walk every page before acting on \"all\". Proxy shown as endpoint only; no notes or cookies.",
    "get_profile": "One profile's full config (same field policy) plus live run state.",
    "get_profile_preflight": "Pre-launch consistency check: can this profile launch now, and what is wrong.",
    "list_device_templates": "Device template library summary (id, screen, GPU, CPU, cores, memory).",
    "get_linkability": "Which profiles look like the same person (shared proxy exit / device / seed), with reasons and fixes.",
    "list_site_check_reports": "Saved fingerprint site-check reports (metadata and pass counts).",
    "get_site_check_report": "One full fingerprint site-check report, with diff against the previous one.",
    "get_current_site_check": "Progress of the running site check (poll after run_site_check).",
    "get_fingerprint_report": "A profile's local fingerprint probe report (per-item consistency; no external sites).",
    "get_warmup_state": "Warm-up state: switch, daily cap, targets, identity age, recent runs.",
    "list_warmup_scripts": "Warm-up script batches awaiting or past review (intents and search terms only).",
    "get_evolution": "Evolution state, pending proposals and logs.",
    "get_kernel_info": "Browser kernel info: versions, installed kernels, license tier (never the key).",
    "launch_profile": "Start a profile's browser. manual = for people, no CDP; debug = CDP for agents (automation mode only).",
    "stop_profile": "Stop a running profile's browser and release its control lease.",
    "run_site_check": "Run a fingerprint site check (async; relaunches the profile in debug and closes it afterwards).",
    "run_warmup": "Run one warm-up round now.",
    "run_evolution": "Run one evolution experiment round now (on disposable clones only).",
    "get_cdp_endpoint": "CDP connection info for a running debug profile (HTTP/WS endpoints, tabs, client snippets). Automation mode.",
    "open_browser": "Ensure a profile runs in debug mode and return CDP info. Idempotent; never restarts a manual session. Automation mode.",
    "browser_navigate": "Open an http(s) URL in the profile's current tab.",
    "browser_snapshot": "Read the page: text outline with refs (e.g. [e3]) for interactive elements. Re-snapshot after the page changes. Long pages truncate: scroll, then viewport_only=true.",
    "browser_get_text": "Read the page's (or an element's) plain text in pages; pass next_offset back as offset to continue.",
    "browser_click": "Click an element by its ref from the latest snapshot.",
    "browser_type": "Fill an input (or pick a select option by text); submit=true presses Enter.",
    "browser_press_key": "Press a key or combo (Enter, Tab, Control+A) on the focused element.",
    "browser_scroll": "Scroll the page up/down/left/right by pixels.",
    "browser_screenshot": "Screenshot the current page (jpeg default; full_page for the whole page).",
    "browser_wait_for": "Wait until text appears / disappears, the URL contains a string, or a selector is visible (or just wait ms). Each condition is bounded by timeout_ms.",
    "account_prepare": "Before a sign-up: get a mailbox address and a vault entry (generated password). Returns the email, username and {{vault:…}} references to type; the password never reaches you.",
    "vault_create": "Create a vault entry for a site: the Manager generates and encrypts the password; you only get {{vault:…}} references.",
    "vault_list": "List this profile's vault entries (site, username, email, status, references), never passwords.",
    "vault_mark": "Set an entry's status (registered / verified / failed) and notes.",
    "browser_batch": "Run up to 20 page steps in one call ({do: click|type|navigate|...}); stops on an error or a dialog and appends a snapshot. Use semantic selectors across page changes.",
    "browser_upload": "Upload files to a file input or the chooser a button opens. Only files inside the agent files folder are allowed (see browser_downloads.files_dir).",
    "browser_downloads": "List files this profile downloaded (auto-saved into the agent files folder) and where that folder is.",
    "browser_dialog": "Accept or dismiss a JS dialog (alert/confirm/prompt/beforeunload) that froze the page. Required when an action result carries `dialog`.",
    "browser_back": "Go back one step in the current tab.",
    "browser_tabs": "List, open, select or close tabs.",
    "mail_get_address": "Get a receiving email address for a profile (the same one each time; new=true for another). Fill it into a sign-up form, then call mail_wait_code.",
    "mail_wait_code": "Wait for a new mail to the address and return the extracted verification code / link (default 120 s, max 170 s).",
    "mail_list_messages": "Recent mail to the address, newest first, with extracted code / link and a text excerpt.",
}


# Words people actually say, in Chinese and English, so the right tool is picked
# even when the user's phrasing does not match the tool's name.
TRIGGERS: dict[str, str] = {
    "manager_status": "状态,概览,版本,先看看,status,overview,health",
    "list_profiles": "列出环境,所有画像,搜索环境,查询环境,list profiles,search profiles,show all",
    "get_profile": "环境详情,画像配置,查看配置,profile details,show config",
    "get_profile_preflight": "能不能启动,启动前检查,preflight,can it launch",
    "list_device_templates": "设备模板,设备型号,device templates",
    "get_linkability": "关联,会不会被关联,同一个人,linkability,linked accounts",
    "list_site_check_reports": "检测报告列表,历史检测,check reports",
    "get_site_check_report": "检测报告详情,对比上一次,check report",
    "get_current_site_check": "检测进度,检测到哪了,check progress",
    "get_fingerprint_report": "指纹自检,指纹报告,本地探针,fingerprint report",
    "get_warmup_state": "养号状态,养号进度,warmup state",
    "list_warmup_scripts": "养号剧本,待审核剧本,warmup scripts",
    "get_evolution": "进化状态,进化提案,evolution",
    "get_kernel_info": "内核版本,授权信息,kernel,license tier",
    "list_proxies": "代理列表,代理库,list proxies",
    "get_proxy_capabilities": "能否换 IP,换 IP 冷却,rotation support",
    "check_proxy_exit_ip": "检测代理,出口 IP,代理通不通,check proxy,exit ip",
    "get_proxy_rotation_result": "换 IP 结果,rotation result",
    "list_groups": "分组列表,有哪些分组,list groups",
    "list_running": "正在运行,已打开,开着的环境,opened browsers,running profiles",
    "list_trash": "回收站,最近删除,已删除环境,recycle bin,trash",
    "launch_profile": "打开环境,启动浏览器,启动画像,open profile,launch,start browser",
    "rotate_proxy_ip": "换 IP,切换 IP,刷新代理,rotate ip,change ip",
    "stop_profile": "关闭环境,关闭浏览器,停止画像,close browser,stop profile",
    "run_site_check": "跑检测,指纹检测,验收环境,run check,fingerprint test",
    "run_warmup": "养号,跑一轮养号,run warmup",
    "run_evolution": "进化,跑一轮进化,run evolution",
    "create_profile": "新建环境,创建画像,添加浏览器,新开环境,create profile,new profile,add browser",
    "update_profile": "修改环境,改配置,改代理,改时区,编辑画像,update profile,edit settings,change proxy",
    "apply_device_template": "套用设备模板,换设备型号,apply template,change device",
    "regenerate_fingerprint": "换新指纹,重新生成指纹,new fingerprint,regenerate fingerprint",
    "reset_profile": "重置环境,一键重置,换环境,清空环境,全新环境,注册失败,reset profile,fresh browser,wipe profile,new environment",
    "create_group": "新建分组,创建分组,create group,new group",
    "move_profiles": "移动分组,换组,归类,move to group,regroup",
    "restore_profile": "恢复环境,还原回收站,找回已删除,restore profile,undelete",
    "delete_profile": "删除环境,删掉画像,放进回收站,delete profile,remove profile,trash",
    "purge_profile": "彻底删除,永久删除,清除数据,purge profile,delete forever,wipe",
    "approve_warmup_batch": "批准养号剧本,通过剧本,approve warmup",
    "reject_warmup_batch": "驳回养号剧本,拒绝剧本,reject warmup",
    "approve_evolution_proposal": "批准进化提案,通过提案,approve proposal",
    "dismiss_evolution_proposal": "驳回进化提案,忽略提案,dismiss proposal",
    "browser_hover": "悬停,鼠标移上去,hover",
    "browser_drag": "拖拽,拖动,滑块,drag and drop,drag",
    "browser_get_html": "读 HTML,页面源码,看源码,get html,page source",
    "browser_evaluate": "执行脚本,执行 JS,运行 JavaScript,evaluate,run script",
    "browser_cookies": "读 Cookie,导出 Cookie,导入 Cookie,清 Cookie,cookies,export cookies,import cookies",
    "create_proxy": "添加代理,保存代理,新建代理,add proxy,save proxy",
    "stop_all_profiles": "全部关闭,关掉所有浏览器,close all,stop all",
    "mail_get_address": "收件邮箱,注册邮箱,get email address",
    "mail_wait_code": "等验证码,收验证码,wait verification code",
    "mail_list_messages": "收到的邮件,看邮件,list mail",
    "get_cdp_endpoint": "CDP 地址,调试端口,playwright 连接,cdp endpoint",
    "open_browser": "打开并接管,调试模式打开,open for automation",
    "browser_navigate": "打开网址,访问网页,go to url,navigate",
    "browser_snapshot": "看页面,页面快照,读取页面结构,snapshot,read page",
    "browser_get_text": "读文字,页面文字,get text",
    "browser_click": "点击,点按钮,click",
    "browser_type": "输入,填表单,type,fill input",
    "browser_press_key": "按键,回车,press key",
    "browser_scroll": "滚动,scroll",
    "browser_screenshot": "截图,screenshot",
    "browser_wait_for": "等待,等出现,wait for",
    "browser_dialog": "弹窗,确认框,dialog,alert",
    "browser_batch": "批量步骤,一次做多步,batch steps",
    "browser_upload": "上传文件,upload file",
    "browser_downloads": "下载的文件,downloads",
    "browser_back": "后退,返回上一页,go back",
    "browser_tabs": "标签页,新开标签,tabs",
    "account_prepare": "注册准备,生成密码,准备账号,prepare sign-up",
    "vault_create": "保险库新建,保存账号密码,vault create",
    "vault_list": "保险库列表,vault list",
    "vault_mark": "标记账号状态,vault mark",
}


def tool_description(tool: ToolDef) -> str:
    en = TOOL_EN.get(tool.name)
    text = f"{tool.description}\n{en}" if en else tool.description
    words = TRIGGERS.get(tool.name)
    return f"{text}\n触发词 / Triggers: {words}" if words else text


def tool_specs(mode: str, token_scope: str | None = None, *, fmt: str = "raw") -> list[dict[str, Any]]:
    """Tool definitions visible in ``mode`` for plain-HTTP agents.

    ``fmt``: ``raw`` (name/description/input_schema/layer), ``openai``
    (function-calling ``tools`` array) or ``anthropic`` (Messages API ``tools``).
    """
    specs: list[dict[str, Any]] = []
    for tool in visible_tools(mode, token_scope):
        description = tool_description(tool)
        if fmt == "openai":
            specs.append(
                {"type": "function", "function": {"name": tool.name, "description": description, "parameters": tool.input_schema}}
            )
        elif fmt == "anthropic":
            specs.append({"name": tool.name, "description": description, "input_schema": tool.input_schema})
        else:
            specs.append(
                {"name": tool.name, "description": description, "input_schema": tool.input_schema, "layer": tool.layer}
            )
    return specs


# ── Backends: where a tool call actually runs ────────────────────────────────
#
# The stdio bridge, the HTTP MCP endpoint and the CLI all talk to a "backend":
#   LocalBackend  runs the tools in this process against the Manager's raw REST
#                 (what the bridge always did; needs a token that can read raw REST).
#   RemoteBackend asks the Manager to run them (/api/agent/tools): field policy and
#                 audit stay server-side and a scoped agent token is enough.
#   AutoBackend   RemoteBackend, falling back to LocalBackend on an older Manager.


class LocalBackend:
    def __init__(self, client: RestClient, *, token_scope: str | None = None, holder: str | None = None) -> None:
        self.client = client
        self.token_scope = token_scope
        self.holder = holder

    async def list_tools(self) -> list[dict[str, Any]]:
        try:
            mode = await fetch_mode(self.client)
        except ManagerUnreachable:
            mode = MODE_READ_ONLY
        return tool_specs(mode, self.token_scope)

    async def call(
        self, name: str, args: dict[str, Any], client_name: str | None = None, client_version: str | None = None
    ) -> dict[str, Any]:
        return await dispatch(
            self.client, name, args,
            client_name=client_name, client_version=client_version,
            token_scope=self.token_scope, holder=self.holder,
        )


class RemoteBackend:
    """Runs tools in the Manager. ``supported`` is False once the Manager
    turned out to have no tool API (older version)."""

    def __init__(self, client: RestClient, *, holder: str | None = None) -> None:
        self.client = client
        self.supported = True
        # Lease holder name sent with every call; None = derived from the client
        # name plus this process's tag, so two agent sessions never share a lease.
        self.holder = holder

    async def list_tools(self) -> list[dict[str, Any]]:
        status, payload = await self.client.get("/api/agent/tools?format=raw", timeout=10.0)
        if status == 200 and isinstance(payload, dict) and isinstance(payload.get("tools"), list):
            return payload["tools"]
        if status in (404, 405) and not (isinstance(payload, dict) and payload.get("reason")):
            self.supported = False
        return []

    async def call(
        self, name: str, args: dict[str, Any], client_name: str | None = None, client_version: str | None = None
    ) -> dict[str, Any]:
        status, payload = await self.client.post(
            f"/api/agent/tools/{quote(name, safe='')}",
            json_body={
                "arguments": args,
                "client": {"name": client_name, "version": client_version},
                "holder": caller_holder(client_name, self.holder),
            },
            timeout=ACTION_TIMEOUT_S,
        )
        if isinstance(payload, dict) and "ok" in payload:
            return payload
        # An older Manager answers 404 (unknown /api path) or 405 (its SPA route
        # only takes GET); a real tool answer always has a structured body.
        if status in (404, 405):
            self.supported = False
            return {"ok": False, "reason": "tool_api_missing", "detail": "这个 Manager 没有 /api/agent/tools。"}
        if status == 401:
            return {"ok": False, "reason": "unauthorized", "detail": "Manager 开了鉴权：AUTH_TOKEN 不对，或 agent token 已被撤销。"}
        return error_result(status, payload, tool=name)


class AutoBackend:
    """Prefer the Manager's tool API; fall back to running tools locally."""

    def __init__(self, client: RestClient, *, holder: str | None = None) -> None:
        self.remote = RemoteBackend(client, holder=holder)
        self.local = LocalBackend(client, holder=holder)

    async def list_tools(self) -> list[dict[str, Any]]:
        if self.remote.supported:
            try:
                tools = await self.remote.list_tools()
            except ManagerUnreachable:
                tools = []
            if tools or self.remote.supported:
                return tools
        return await self.local.list_tools()

    async def call(
        self, name: str, args: dict[str, Any], client_name: str | None = None, client_version: str | None = None
    ) -> dict[str, Any]:
        if self.remote.supported:
            try:
                result = await self.remote.call(name, args, client_name, client_version)
            except ManagerUnreachable as exc:
                return unreachable_result(exc)
            if result.get("reason") != "tool_api_missing":
                return result
        try:
            return await self.local.call(name, args, client_name, client_version)
        except ManagerUnreachable as exc:
            return unreachable_result(exc)


# Shown to the agent at connect time (MCP `instructions`). Full guide: docs/AGENT.md.
INSTRUCTIONS = """\
CloakBrowser Manager：管理「指纹浏览器画像」（profile）的本机服务。每个画像是一个独立的浏览器身份\
（指纹、代理、Cookie、登录状态都隔离）。你通过这组工具看懂并启停画像；在 automation 档还能直接操作页面。
CloakBrowser Manager runs isolated fingerprint-browser profiles on this machine. These tools inspect and start/stop them; in `automation` mode they also let you drive pages.

代理换 IP：先 list_proxies / get_proxy_capabilities 查能力、关联和影响范围；用 rotate_proxy_ip 调用已配置的供应商链接。只有 verified 才表示所验证路径的 IP 已改变；queued/running 用 get_proxy_rotation_result 继续查，accepted_unverified/unchanged 不要反复请求刷新链接。同一意图复用 request_id。check_proxy_exit_ip 会按环境实际直连/中转路径新建连接检查。旧网页连接可能仍需重连，未经要求不要关闭浏览器。Proxy rotation: discover capabilities, invoke rotate_proxy_ip once, poll its job; never replay uncertain mutations.

标准流程 / Standard flow:
1. manager_status — 先打招呼：版本、运行数、是否有自动化在跑。
2. list_profiles — 找到要用的画像（id 或名称）。
3. get_profile_preflight — 可选：确认现在能不能启动。
4. open_browser(profile) — 以 debug 模式启动（automation 档）。已在跑则直接返回，不会重启。
   只想打开给人看：launch_profile（manual 模式，无页面控制）。
5. 循环：browser_navigate → browser_snapshot → 用快照里的 ref 做 browser_click / browser_type；页面变了就重新 browser_snapshot。
   长页面：browser_scroll 后用 browser_snapshot(viewport_only=true) 看当前一屏，或用 browser_get_text 分页读正文。
   省往返：browser_batch 一次做多步；跨页面的步骤用语义选择器（text=… / role=button[name=…]），快照 ref 在页面跳转后会失效。
   动作结果里出现 dialog 字段，说明弹了 JS 对话框，先 browser_dialog 处理。上传只允许 agent 文件目录里的文件（browser_downloads 能看到目录位置）。
   也可以把 open_browser 返回的 cdp_http_endpoint 交给 Playwright / playwright-mcp / chrome-devtools-mcp。
6. 用完 stop_profile。
注册要邮箱验证时（full 档）：mail_get_address(profile) 拿地址 → 填表提交 → mail_wait_code(address) 拿验证码或验证链接。不要向用户要邮箱或验证码。
注册新账号（automation 档）更省事：account_prepare(profile, site) 一步拿到邮箱、用户名和密码引用 → browser_type 把引用（如 {{vault:ID.password}}）原样填进表单，你拿不到密码明文 → 提交后 mail_wait_code 取验证码 → vault_mark(registered/verified)。登录已注册的网站：vault_list 找引用再填。遇到图形验证码或手机短信验证：停下来，请用户在面板里接管。

规则 / Rules:
- 权限由 Manager 设置 mcp.mode 决定，默认 automation = 全部开放：读、启停、新建/修改/删除画像、批准养号剧本和进化提案、open_browser / get_cdp_endpoint / browser_* 页面控制、Cookie 读写、执行 JS。用户手动调低后才会看到更少的工具（read-only 只读；full 去掉页面控制和删除）；你的 token 也可能把上限压得更低（scope_denied）。工具列表在连接时协商，改模式后要重启客户端。
- 页面控制会拿一个「控制租约」。profile_leased 说明用户在接管或别的 agent 在用：停下来等，不要重试轰炸，也不要绕过。
- 页面控制和 Cookie 只对当前任务需要的画像开，用完就 stop_profile。
- delete_profile 进回收站可恢复；purge_profile 不可恢复，只在用户明确要求彻底删除时用。
- 不要改画像的指纹配置来「绕过」问题；指纹异常先看 get_fingerprint_report / get_profile_preflight，把结论告诉用户。
- 免费授权只有一个并发座位：同时只开一个画像。seat_busy 表示座位未释放，等几分钟，不要立刻重试。
- automation_busy 表示另一个自动化（检测/养号/进化）在跑，等它结束。
- 工具失败回 {ok:false, reason, detail, next_step}，按 reason / next_step 决定下一步，不要盲目重试。
完整说明见资源 cloakbrowser://guide（仓库 docs/AGENT.md）。
"""


_GUIDE_PATH = Path(__file__).resolve().parents[1] / "docs" / "AGENT.md"


def guide_text() -> str:
    """The full agent guide (docs/AGENT.md); the short INSTRUCTIONS if it is not shipped."""
    try:
        return _GUIDE_PATH.read_text(encoding="utf-8")
    except OSError:
        return INSTRUCTIONS
