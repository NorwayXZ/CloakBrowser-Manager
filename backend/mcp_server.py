"""Stdio MCP bridge: let an MCP client (Claude Desktop / Muse) drive
the local Manager through its existing REST API.

Design (see MCP-PLAN.md):

* This process is launched by the user's own MCP client and speaks MCP over
  stdio. It adds no listening port; every tool call is translated into a
  request to ``http://127.0.0.1:{server_port()}/api/...``.
* Tools are layered. The 14 read tools are always available unless the mode
  is ``off``; the 5 action tools (launch / stop / site-check / warm-up /
  evolution) only register when the Manager setting ``mcp.mode`` is ``full``
  (default ``read-only``). The 2 browser tools (``open_browser`` /
  ``get_cdp_endpoint``, which hand out a CDP endpoint) are a separate tier that
  only registers when the mode is ``automation``. Destructive operations,
  proposal approvals and Cookie tools are not tools at all — by construction.
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
from urllib.parse import quote

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
# full + the "browser" tools: the only tier that hands out a CDP endpoint.
MODE_AUTOMATION = "automation"
_MODES = (MODE_OFF, MODE_READ_ONLY, MODE_FULL, MODE_AUTOMATION)
_ACTION_MODES = (MODE_FULL, MODE_AUTOMATION)

LAUNCH_MODES = ("manual", "debug")

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


def not_automation_result() -> dict[str, Any]:
    return {
        "ok": False,
        "reason": "mode_not_automation",
        "detail": (
            "浏览器控制（CDP）只在 mcp.mode=automation 下开放。CDP 能读取画像的 Cookie，"
            "所以单独成档：在 Manager 设置里把 mcp.mode 改成 automation 并重启客户端。"
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


def visible_tools(mode: str) -> list[ToolDef]:
    if mode == MODE_OFF:
        return []
    if mode == MODE_AUTOMATION:
        return list(TOOLS.values())
    if mode == MODE_FULL:
        return [tool for tool in TOOLS.values() if tool.layer in ("read", "action")]
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
            elif tool.layer == "action" and mode not in _ACTION_MODES:
                result = {
                    "ok": False,
                    "reason": "mode_read_only",
                    "detail": "当前是只读模式（mcp.mode=read-only）；动作工具要在 Manager 设置里把 mcp.mode 改成 full 才开放。",
                }
            elif tool.layer == "browser" and mode != MODE_AUTOMATION:
                result = not_automation_result()
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


@register("list_profiles", "列出全部画像的摘要（id、名称、平台、设备模板、时区/语言、指纹配置、养号与进化开关、运行状态）。代理只回出口端点不带账密，备注与 Cookie 不回。", NO_ARGS, "read")
async def _list_profiles(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    payload, err = await _get_or_error(client, "/api/profiles", "list_profiles")
    if err:
        return err
    profiles = [shape_profile(p) for p in payload if isinstance(p, dict)]
    return {"ok": True, "count": len(profiles), "profiles": profiles}


@register("get_profile", "看单个画像的完整配置（字段政策同 list_profiles）加实时运行状态。", PROFILE_ID_ARGS, "read")
async def _get_profile(client: RestClient, args: dict[str, Any]) -> dict[str, Any]:
    profile_id, err = _profile_id_arg(args)
    if err:
        return err
    quoted = quote(profile_id, safe="")
    payload, err = await _get_or_error(client, f"/api/profiles/{quoted}", "get_profile")
    if err:
        return err
    result: dict[str, Any] = {"ok": True, "profile": shape_profile(payload)}
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
    "看画像的 AI 养号剧本批次：状态、主题与意图（搜索词）。persona 快照不回。批准/驳回只能在面板里人工操作，这里没有对应工具。",
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
    "看自对抗进化：引擎状态、待人工批准的提案、实验战报。section 可选 status/proposals/logs/all（默认 all）。批准提案只能在面板里人工操作。",
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
    http_endpoint = f"{client.base_url}{cdp_path}"
    ws_base = client.base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
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


# ── Tools: browser layer (registered only when mcp.mode == "automation") ─────


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
    return await _cdp_endpoint_info(client, profile_id, tool="get_cdp_endpoint")


async def _resolve_profile(client: RestClient, ref: str) -> tuple[str, dict[str, Any] | None]:
    """Profile id from an id or an exact, unique name."""
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
    return {**info, "started": started}


# ── MCP server wiring (the only place the SDK is touched) ────────────────────

# Shown to the agent at connect time (MCP `instructions`). Full guide: docs/AGENT.md.
INSTRUCTIONS = """\
CloakBrowser Manager：管理「指纹浏览器画像」（profile）的本机服务。每个画像是一个独立的浏览器身份\
（指纹、代理、Cookie、登录状态都隔离）。你通过这组工具看懂并启停画像；在 automation 档还能拿到 CDP 去操作页面。
CloakBrowser Manager runs isolated fingerprint-browser profiles on this machine. These tools inspect and start/stop them; in `automation` mode they also give you a CDP endpoint to drive pages.

标准流程 / Standard flow:
1. manager_status — 先打招呼：版本、运行数、是否有自动化在跑。
2. list_profiles — 找到要用的画像（id 或名称）。
3. get_profile_preflight — 可选：确认现在能不能启动。
4. open_browser(profile) — 以 debug 模式启动并拿 CDP 端点（automation 档）。已在跑则直接返回信息。
   只想打开给人看：launch_profile（manual 模式，无 CDP）。
5. 用返回的 cdp_http_endpoint 接 Playwright / playwright-mcp / chrome-devtools-mcp 操作页面。
6. 用完 stop_profile。

规则 / Rules:
- 权限由 Manager 设置 mcp.mode 决定：read-only 只读；full 加启停与检测/养号/进化；automation 再加 open_browser / get_cdp_endpoint。工具列表在连接时协商，改模式后要重启客户端。
- CDP 能读 Cookie：只对当前任务需要的画像开，用完就关；不要导出或回显 Cookie、账号、代理凭据。
- 不要改画像的指纹配置来「绕过」问题；指纹异常先看 get_fingerprint_report / get_profile_preflight。
- 免费授权只有一个并发座位：同时只开一个画像。seat_busy 表示座位未释放，等几分钟，不要立刻重试。
- automation_busy 表示另一个自动化（检测/养号/进化）在跑，等它结束。
- 工具失败回 {ok:false, reason, detail}，按 reason 决定下一步，不要盲目重试。
- 没有删除画像、批准提案、Cookie 读取、备份恢复这类工具，这是设计如此。
完整说明见仓库 docs/AGENT.md。
"""


def build_server(client: RestClient) -> Server:
    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        try:
            mode = await fetch_mode(client)
        except Exception:
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

    return Server(
        SERVER_NAME,
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def _serve(client: RestClient) -> None:
    server = build_server(client)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    client = RestClient()
    try:
        mode = asyncio.run(fetch_mode(client))
    except Exception:
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
