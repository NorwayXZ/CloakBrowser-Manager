"""Tests for the stdio MCP bridge (backend/mcp_server.py) and the Manager-side
MCP endpoints (settings + audit).

The bridge is exercised against a fake REST layer (httpx.MockTransport), the
same way it talks to the real Manager; Manager-side endpoints go through the
usual TestClient fixtures.
"""

from __future__ import annotations

import json

import httpx
import pytest

from backend import mcp_server
from backend import database as db


# ── Fake Manager REST layer ──────────────────────────────────────────────────


class FakeManager:
    """Stand-in for the Manager's REST API behind an httpx MockTransport."""

    def __init__(self, mode: str = "full") -> None:
        self.mode = mode
        self.requests: list[tuple[str, str]] = []
        self.audits: list[dict] = []
        self.bodies: dict[tuple[str, str], dict] = {}
        self.routes: dict[tuple[str, str], tuple[int, object]] = {}
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.requests.append((method, path))
        if method == "POST" and request.content:
            self.bodies[(method, path)] = json.loads(request.content)
        if path == "/api/settings/mcp":
            return httpx.Response(200, json={"mode": self.mode})
        if path == "/api/mcp/audit" and method == "POST":
            self.audits.append(json.loads(request.content or b"{}"))
            return httpx.Response(201, json={"id": "audit-1", "ok": True})
        key = (method, path)
        if key in self.routes:
            status, payload = self.routes[key]
            return httpx.Response(status, json=payload)
        return httpx.Response(404, json={"detail": "Profile not found"})

    def client(self) -> mcp_server.RestClient:
        return mcp_server.RestClient(
            "http://127.0.0.1:9999", transport=self.transport, token=""
        )

    def hit(self, method: str, path: str) -> bool:
        return (method, path) in self.requests


def unreachable_client() -> mcp_server.RestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return mcp_server.RestClient(
        "http://127.0.0.1:9999", transport=httpx.MockTransport(handler), token=""
    )


# ── Schema snapshot ──────────────────────────────────────────────────────────

NO_ARGS = {"type": "object", "properties": {}}
PROFILE_ID_ARGS = {
    "type": "object",
    "properties": {
        "profile_id": {"type": "string", "description": "画像 id（先用 list_profiles 查）"}
    },
    "required": ["profile_id"],
}

EXPECTED_READ_TOOLS = {
    "manager_status": {
        "type": "object",
        "properties": {
            "include_automation_hours": {
                "type": "boolean",
                "default": False,
                "description": "是否一并返回自动化时段设置",
            }
        },
    },
    "list_profiles": NO_ARGS,
    "get_profile": PROFILE_ID_ARGS,
    "get_profile_preflight": PROFILE_ID_ARGS,
    "list_device_templates": NO_ARGS,
    "get_linkability": NO_ARGS,
    "list_site_check_reports": NO_ARGS,
    "get_site_check_report": {
        "type": "object",
        "properties": {
            "report_id": {"type": "string", "description": "报告 id（先用 list_site_check_reports 查）"}
        },
        "required": ["report_id"],
    },
    "get_current_site_check": NO_ARGS,
    "get_fingerprint_report": PROFILE_ID_ARGS,
    "get_warmup_state": PROFILE_ID_ARGS,
    "list_warmup_scripts": PROFILE_ID_ARGS,
    "get_evolution": {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": ["all", "status", "proposals", "logs"],
                "default": "all",
            }
        },
    },
    "get_kernel_info": NO_ARGS,
}

LAUNCH_PROFILE_ARGS = {
    "type": "object",
    "properties": {
        "profile_id": {"type": "string", "description": "画像 id（先用 list_profiles 查）"},
        "launch_mode": {
            "type": "string",
            "enum": ["manual", "debug"],
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

EXPECTED_ACTION_TOOLS = {
    "launch_profile": LAUNCH_PROFILE_ARGS,
    "stop_profile": PROFILE_ID_ARGS,
    "run_site_check": PROFILE_ID_ARGS,
    "run_warmup": PROFILE_ID_ARGS,
    "run_evolution": PROFILE_ID_ARGS,
}

EXPECTED_BROWSER_TOOLS = {
    "get_cdp_endpoint": PROFILE_ID_ARGS,
    "open_browser": {
        "type": "object",
        "properties": {
            "profile": {"type": "string", "description": "画像 id 或画像名称（名称需完全一致且唯一）"},
        },
        "required": ["profile"],
    },
}


def test_tool_snapshot_read_only_mode():
    tools = mcp_server.build_mcp_tools("read-only")
    assert [t.name for t in tools] == list(EXPECTED_READ_TOOLS)
    assert {t.name: t.input_schema for t in tools} == EXPECTED_READ_TOOLS


def test_tool_snapshot_full_mode():
    tools = mcp_server.build_mcp_tools("full")
    expected = {**EXPECTED_READ_TOOLS, **EXPECTED_ACTION_TOOLS}
    assert [t.name for t in tools] == list(expected)
    assert {t.name: t.input_schema for t in tools} == expected


def test_tool_snapshot_automation_mode():
    tools = mcp_server.build_mcp_tools("automation")
    expected = {**EXPECTED_READ_TOOLS, **EXPECTED_ACTION_TOOLS, **EXPECTED_BROWSER_TOOLS}
    assert [t.name for t in tools] == list(expected)
    assert {t.name: t.input_schema for t in tools} == expected


def test_tool_snapshot_off_mode_is_empty():
    assert mcp_server.build_mcp_tools("off") == []


def test_no_cookie_or_destructive_tools_exist():
    names = set(mcp_server.TOOLS)
    for forbidden in names:
        assert "cookie" not in forbidden
        assert "burn" not in forbidden
        assert "purge" not in forbidden
        assert "delete" not in forbidden
        assert "approve" not in forbidden
        assert "clipboard" not in forbidden
        # CDP handout lives only in the automation-tier "browser" layer.
        if "cdp" in forbidden:
            assert mcp_server.TOOLS[forbidden].layer == "browser"


def test_instructions_name_real_tools():
    for name in (
        "manager_status", "list_profiles", "get_profile_preflight", "open_browser",
        "launch_profile", "stop_profile", "get_fingerprint_report", "get_cdp_endpoint",
    ):
        assert name in mcp_server.TOOLS, name
        assert name in mcp_server.INSTRUCTIONS, name
    server = mcp_server.build_server(FakeManager().client())
    assert server.instructions == mcp_server.INSTRUCTIONS


# ── Mapping integration ──────────────────────────────────────────────────────


async def test_manager_status_merges_status_and_automation():
    fake = FakeManager()
    fake.routes[("GET", "/api/status")] = (200, {"running_count": 2, "profiles_total": 5})
    fake.routes[("GET", "/api/automation/status")] = (200, {"active": True, "kind": "warmup"})
    fake.routes[("GET", "/api/automation/hours")] = (200, {"hours": "09-18", "open_now": True})
    result = await mcp_server.dispatch(
        fake.client(), "manager_status", {"include_automation_hours": True}
    )
    assert result["ok"] is True
    assert result["status"]["running_count"] == 2
    assert result["automation"]["kind"] == "warmup"
    assert result["automation_hours"]["hours"] == "09-18"


async def test_each_read_tool_hits_its_endpoint():
    fake = FakeManager()
    pid, rid = "p1", "r1"
    for method, path, payload in [
        ("GET", "/api/profiles", []),
        ("GET", f"/api/profiles/{pid}", {"id": pid}),
        ("GET", f"/api/profiles/{pid}/status", {"status": "stopped"}),
        ("GET", f"/api/profiles/{pid}/preflight", {"can_launch": True}),
        ("GET", "/api/device-templates", []),
        ("GET", "/api/linkability", {"clusters": []}),
        ("GET", "/api/site-checks", []),
        ("GET", f"/api/site-checks/{rid}", {"id": rid}),
        ("GET", "/api/site-checks/current", {"phase": "idle"}),
        ("GET", f"/api/profiles/{pid}/fingerprint-report", {"items": []}),
        ("GET", f"/api/profiles/{pid}/warmup", {"enabled": False}),
        ("GET", f"/api/profiles/{pid}/warmup/scripts", {"batches": []}),
        ("GET", "/api/evolution/status", {"busy": False}),
        ("GET", "/api/evolution/proposals", []),
        ("GET", "/api/evolution/logs", []),
        ("GET", "/api/kernel", {"license": {"tier": "free"}}),
    ]:
        fake.routes[(method, path)] = (200, payload)

    client = fake.client()
    calls = [
        ("list_profiles", {}, "/api/profiles"),
        ("get_profile", {"profile_id": pid}, f"/api/profiles/{pid}"),
        ("get_profile_preflight", {"profile_id": pid}, f"/api/profiles/{pid}/preflight"),
        ("list_device_templates", {}, "/api/device-templates"),
        ("get_linkability", {}, "/api/linkability"),
        ("list_site_check_reports", {}, "/api/site-checks"),
        ("get_site_check_report", {"report_id": rid}, f"/api/site-checks/{rid}"),
        ("get_current_site_check", {}, "/api/site-checks/current"),
        ("get_fingerprint_report", {"profile_id": pid}, f"/api/profiles/{pid}/fingerprint-report"),
        ("get_warmup_state", {"profile_id": pid}, f"/api/profiles/{pid}/warmup"),
        ("list_warmup_scripts", {"profile_id": pid}, f"/api/profiles/{pid}/warmup/scripts"),
        ("get_evolution", {}, "/api/evolution/status"),
        ("get_kernel_info", {}, "/api/kernel"),
    ]
    for name, args, path in calls:
        result = await mcp_server.dispatch(client, name, args)
        assert result["ok"] is True, (name, result)
        assert fake.hit("GET", path), name
    # get_profile also consulted the live status endpoint.
    assert fake.hit("GET", f"/api/profiles/{pid}/status")
    # get_evolution "all" merged all three sections.
    assert fake.hit("GET", "/api/evolution/proposals")
    assert fake.hit("GET", "/api/evolution/logs")


async def test_each_action_tool_hits_its_endpoint():
    fake = FakeManager(mode="full")
    pid = "p1"
    for path, payload in [
        (f"/api/profiles/{pid}/launch", {"profile_id": pid, "status": "running"}),
        (f"/api/profiles/{pid}/stop", {"ok": True}),
        (f"/api/profiles/{pid}/site-check", {"phase": "launching"}),
        (f"/api/profiles/{pid}/warmup/run", {"ok": True, "started": True}),
        (f"/api/profiles/{pid}/evolution/run", {"ok": True, "started": True}),
    ]:
        fake.routes[("POST", path)] = (200, payload)
    client = fake.client()
    for name in ("launch_profile", "stop_profile", "run_site_check", "run_warmup", "run_evolution"):
        result = await mcp_server.dispatch(client, name, {"profile_id": pid})
        assert result["ok"] is True, (name, result)
    assert fake.hit("POST", f"/api/profiles/{pid}/launch")
    assert fake.hit("POST", f"/api/profiles/{pid}/stop")
    assert fake.hit("POST", f"/api/profiles/{pid}/site-check")
    assert fake.hit("POST", f"/api/profiles/{pid}/warmup/run")
    assert fake.hit("POST", f"/api/profiles/{pid}/evolution/run")


async def test_missing_arguments_are_invalid_argument():
    fake = FakeManager()
    result = await mcp_server.dispatch(fake.client(), "get_profile", {})
    assert result["ok"] is False
    assert result["reason"] == "invalid_argument"
    result = await mcp_server.dispatch(fake.client(), "get_site_check_report", {})
    assert result["reason"] == "invalid_argument"
    result = await mcp_server.dispatch(fake.client(), "get_evolution", {"section": "bogus"})
    assert result["reason"] == "invalid_argument"


async def test_unknown_tool():
    fake = FakeManager()
    result = await mcp_server.dispatch(fake.client(), "burn_profile", {"profile_id": "p1"})
    assert result["ok"] is False
    assert result["reason"] == "unknown_tool"


# ── Structured error mapping ─────────────────────────────────────────────────


async def test_launch_seat_error_maps_to_seat_busy():
    fake = FakeManager(mode="full")
    fake.routes[("POST", "/api/profiles/p1/launch")] = (
        409, {"detail": "Failed to launch: session limit reached for this license"},
    )
    result = await mcp_server.dispatch(fake.client(), "launch_profile", {"profile_id": "p1"})
    assert result["ok"] is False
    assert result["reason"] == "seat_busy"


async def test_launch_already_running_maps():
    fake = FakeManager(mode="full")
    fake.routes[("POST", "/api/profiles/p1/launch")] = (
        409, {"detail": "Profile is already running"},
    )
    result = await mcp_server.dispatch(fake.client(), "launch_profile", {"profile_id": "p1"})
    assert result["reason"] == "already_running"


async def test_automation_busy_carries_owner_from_lock_detail():
    fake = FakeManager(mode="full")
    fake.routes[("POST", "/api/profiles/p1/site-check")] = (
        409, {"detail": "另一个自动化（warmup）正在运行，请等它结束。"},
    )
    result = await mcp_server.dispatch(fake.client(), "run_site_check", {"profile_id": "p1"})
    assert result["reason"] == "automation_busy"
    assert result["owner"] == "warmup"


async def test_same_automation_busy_maps_with_owner():
    fake = FakeManager(mode="full")
    fake.routes[("POST", "/api/profiles/p1/site-check")] = (
        409, {"detail": "已经有一个检测在进行，请等它结束。"},
    )
    result = await mcp_server.dispatch(fake.client(), "run_site_check", {"profile_id": "p1"})
    assert result["reason"] == "automation_busy"
    assert result["owner"] == "site_check"


async def test_not_found_and_not_running():
    fake = FakeManager(mode="full")
    result = await mcp_server.dispatch(fake.client(), "get_profile", {"profile_id": "ghost"})
    assert result["reason"] == "not_found"
    fake.routes[("POST", "/api/profiles/p1/stop")] = (
        404, {"detail": "Profile is not running"},
    )
    result = await mcp_server.dispatch(fake.client(), "stop_profile", {"profile_id": "p1"})
    assert result["reason"] == "not_running"


async def test_manager_unreachable_is_structured_not_raised():
    client = unreachable_client()
    result = await mcp_server.dispatch(client, "manager_status", {})
    assert result["ok"] is False
    assert result["reason"] == "manager_unreachable"
    result = await mcp_server.dispatch(client, "launch_profile", {"profile_id": "p1"})
    assert result["reason"] == "manager_unreachable"


# ── Mode gate ────────────────────────────────────────────────────────────────


async def test_read_only_mode_rejects_actions_and_audits_the_rejection():
    fake = FakeManager(mode="read-only")
    fake.routes[("POST", "/api/profiles/p1/launch")] = (200, {"profile_id": "p1"})
    result = await mcp_server.dispatch(fake.client(), "launch_profile", {"profile_id": "p1"})
    assert result["ok"] is False
    assert result["reason"] == "mode_read_only"
    # The REST action endpoint was never called...
    assert not fake.hit("POST", "/api/profiles/p1/launch")
    # ...but the rejection itself was audited.
    rejections = [a for a in fake.audits if a["tool"] == "launch_profile"]
    assert len(rejections) == 1
    assert rejections[0]["ok"] is False
    assert rejections[0]["reason"] == "mode_read_only"
    # Read tools still work in read-only mode.
    fake.routes[("GET", "/api/profiles")] = (200, [])
    result = await mcp_server.dispatch(fake.client(), "list_profiles", {})
    assert result["ok"] is True


async def test_off_mode_refuses_everything():
    fake = FakeManager(mode="off")
    result = await mcp_server.dispatch(fake.client(), "list_profiles", {})
    assert result["ok"] is False
    assert result["reason"] == "mcp_disabled"


async def test_garbage_mode_from_manager_falls_back_to_read_only():
    fake = FakeManager(mode="weird-value")
    result = await mcp_server.dispatch(fake.client(), "launch_profile", {"profile_id": "p1"})
    assert result["reason"] == "mode_read_only"


# ── Audit ────────────────────────────────────────────────────────────────────


async def test_every_dispatch_reports_one_audit_row():
    fake = FakeManager()
    fake.routes[("GET", "/api/profiles")] = (200, [])
    await mcp_server.dispatch(
        fake.client(),
        "list_profiles",
        {},
        client_name="Claude Desktop",
        client_version="1.2.3",
    )
    assert len(fake.audits) == 1
    row = fake.audits[0]
    assert row["tool"] == "list_profiles"
    assert row["ok"] is True
    assert row["reason"] is None
    assert row["client_name"] == "Claude Desktop"
    assert row["client_version"] == "1.2.3"
    assert isinstance(row["duration_ms"], int)


def test_summarize_args_redacts_private_values():
    summary = mcp_server.summarize_args(
        {
            "profile_id": "p1",
            "proxy": "socks5://user:proxy-pass@10.0.0.8:1080",
            "notes": "我的账号备忘",
            "persona": "人设原文",
            "blob": "x" * 120,
        }
    )
    assert summary["profile_id"] == "p1"
    assert summary["proxy"] == "socks5://10.0.0.8:1080"
    assert summary["notes"] == {"present": True, "length": 6}
    assert summary["persona"] == {"present": True, "length": 4}
    blob = json.dumps(summary, ensure_ascii=False)
    assert "proxy-pass" not in blob
    assert "我的账号备忘" not in blob
    assert "人设原文" not in blob
    assert "x" * 120 not in blob


# ── Secrets never leak (hard assertions) ─────────────────────────────────────

PROXY_PASSWORD = "PROXY_PASSWORD_XYZ"
NOTE_SECRET = "NOTE_SECRET_XYZ"
PERSONA_SECRET = "PERSONA_SECRET_XYZ"
COOKIE_VALUE = "COOKIE_VALUE_XYZ"
LICENSE_KEY = "FAKE_LICENSE_KEY_XYZ"

SECRET_PROFILE = {
    "id": "p-secret",
    "name": "秘密画像",
    "fingerprint_seed": 42,
    "proxy": f"socks5://agentuser:{PROXY_PASSWORD}@10.0.0.8:1080",
    "notes": NOTE_SECRET,
    "warmup_persona": PERSONA_SECRET,
    "cookies_json": json.dumps([{"name": "sid", "value": COOKIE_VALUE}]),
    "cdp_url": "/api/profiles/p-secret/cdp",
    "user_data_dir": "/home/user/.cloak/p-secret",
    "proxy_geo": {"ip": "203.0.113.9", "country_code": "TW"},
    "timezone": "Asia/Shanghai",
    "locale": "zh-CN",
    "platform": "windows",
    "status": "running",
    "warmup_enabled": True,
    "warmup_targets": ["google"],
    "tags": [],
    "fingerprint_options": {},
    "created_at": "2026-10-23T00:00:00+08:00",
    "updated_at": "2026-10-23T00:00:00+08:00",
}


def secret_fake(tmp_path) -> FakeManager:
    # A fake license key file exists on disk somewhere; no tool may ever
    # surface its content (the REST layer never returns it either).
    (tmp_path / "license.key").write_text(LICENSE_KEY, encoding="utf-8")
    fake = FakeManager(mode="full")
    pid = "p-secret"
    fake.routes.update(
        {
            ("GET", "/api/status"): (200, {"running_count": 1, "profiles_total": 1}),
            ("GET", "/api/automation/status"): (200, {"active": False}),
            ("GET", "/api/profiles"): (200, [SECRET_PROFILE]),
            ("GET", f"/api/profiles/{pid}"): (200, SECRET_PROFILE),
            ("GET", f"/api/profiles/{pid}/status"): (
                200,
                {
                    "status": "running",
                    "runtime_mode": "native",
                    "viewer_mode": "native-window",
                    "vnc_ws_port": 6080,
                    "display": ":0",
                    "cdp_url": "/api/profiles/p-secret/cdp",
                    "browser_engine": "cloak",
                    "launch_mode": "debug",
                    "proxy_geo": {"ip": "203.0.113.9"},
                },
            ),
            ("GET", f"/api/profiles/{pid}/preflight"): (200, {"can_launch": True, "issues": []}),
            ("GET", "/api/device-templates"): (
                200,
                [{"id": "tpl-1", "name": "Dell XPS 15", "family": "dell", "cpu": "i7",
                  "screen_width": 1920, "screen_height": 1080,
                  "gpu_vendor": "NVIDIA", "gpu_renderer": "RTX 4060",
                  "hardware_concurrency": 16, "device_memory": 16}],
            ),
            ("GET", "/api/linkability"): (200, {"profile_count": 1, "unclustered_count": 1, "clusters": []}),
            ("GET", "/api/site-checks"): (200, [{"id": "rep1", "passed": 9, "total": 10}]),
            ("GET", "/api/site-checks/rep1"): (
                200,
                {"id": "rep1", "overall": "pass",
                 "environment": {"profile_id": pid, "proxy_type": "socks5", "exit_ip": "203.0.113.9"},
                 "results": [], "diff": None},
            ),
            ("GET", "/api/site-checks/current"): (200, {"phase": "idle"}),
            ("GET", f"/api/profiles/{pid}/fingerprint-report"): (200, {"items": []}),
            ("GET", f"/api/profiles/{pid}/warmup"): (
                200, {"enabled": True, "daily_max": 1, "targets": ["google"], "age": {}, "runs": [], "warming": False},
            ),
            ("GET", f"/api/profiles/{pid}/warmup/scripts"): (
                200,
                {"llm_configured": True, "generating": False, "last_generation": None,
                 "batches": [{
                     "batch_id": "b1", "created_at": "2026-10-23T00:00:00+08:00",
                     "status": "draft", "model": "m", "persona": PERSONA_SECRET,
                     "scripts": [{"id": "s1", "theme": "露营",
                                  "steps": [{"kind": "search", "platform": "google",
                                             "platform_name": "Google", "search_query": "露营装备",
                                             "dwell": "medium", "follow_link": False}]}],
                 }]},
            ),
            ("GET", "/api/evolution/status"): (200, {"busy": False, "pending_proposals": 1}),
            ("GET", "/api/evolution/proposals"): (
                200,
                [{"id": "prop1", "profile_id": pid, "profile_name": "秘密画像",
                  "knob": "fingerprint_options.noise", "label": "关闭指纹噪声",
                  "from_value": True, "to_value": False, "targets": [], "evidence": {},
                  "status": "pending"}],
            ),
            ("GET", "/api/evolution/logs"): (200, []),
            ("GET", "/api/kernel"): (
                200,
                {"cache_dir": "/tmp/k", "wrapper_version": "1.0", "platform": "darwin",
                 "license": {"tier": "free", "plan": None, "expires": None,
                             "can_pin": False, "key_stored": True},
                 "settings": {"auto_update": True, "release_channel": "stable", "pinned_version": None},
                 "version": "155", "installed": True, "pinned": False,
                 "bundled_version": None, "installed_kernels": [], "running_count": 1},
            ),
            ("POST", f"/api/profiles/{pid}/launch"): (
                200,
                {"profile_id": pid, "status": "running", "runtime_mode": "native",
                 "viewer_mode": "native-window", "vnc_ws_port": 6080, "display": ":0",
                 "cdp_url": "/api/profiles/p-secret/cdp", "browser_engine": "cloak",
                 "launch_mode": "debug"},
            ),
            ("POST", f"/api/profiles/{pid}/stop"): (200, {"ok": True}),
            ("POST", f"/api/profiles/{pid}/site-check"): (200, {"phase": "launching", "profile_id": pid}),
            ("POST", f"/api/profiles/{pid}/warmup/run"): (200, {"ok": True, "started": True}),
            ("POST", f"/api/profiles/{pid}/evolution/run"): (200, {"ok": True, "started": True}),
        }
    )
    return fake


async def test_no_secret_appears_in_any_tool_output(tmp_path):
    fake = secret_fake(tmp_path)
    client = fake.client()
    pid = "p-secret"
    calls = [
        ("manager_status", {}),
        ("list_profiles", {}),
        ("get_profile", {"profile_id": pid}),
        ("get_profile_preflight", {"profile_id": pid}),
        ("list_device_templates", {}),
        ("get_linkability", {}),
        ("list_site_check_reports", {}),
        ("get_site_check_report", {"report_id": "rep1"}),
        ("get_current_site_check", {}),
        ("get_fingerprint_report", {"profile_id": pid}),
        ("get_warmup_state", {"profile_id": pid}),
        ("list_warmup_scripts", {"profile_id": pid}),
        ("get_evolution", {}),
        ("get_kernel_info", {}),
        ("launch_profile", {"profile_id": pid}),
        ("stop_profile", {"profile_id": pid}),
        ("run_site_check", {"profile_id": pid}),
        ("run_warmup", {"profile_id": pid}),
        ("run_evolution", {"profile_id": pid}),
    ]
    results = {}
    for name, args in calls:
        results[name] = await mcp_server.dispatch(client, name, args)
        assert results[name]["ok"] is True, (name, results[name])
    blob = json.dumps(results, ensure_ascii=False)
    audit_blob = json.dumps(fake.audits, ensure_ascii=False)
    for secret in (PROXY_PASSWORD, "agentuser", NOTE_SECRET, PERSONA_SECRET, COOKIE_VALUE, LICENSE_KEY):
        assert secret not in blob, secret
        assert secret not in audit_blob, secret
    assert "/cdp" not in blob
    assert ".cloak" not in blob
    # Positive controls: the shaping kept the useful, non-secret facts.
    assert results["list_profiles"]["profiles"][0]["proxy"] == "socks5://10.0.0.8:1080"
    steps = results["list_warmup_scripts"]["batches"][0]["scripts"][0]["steps"]
    assert steps[0]["search_query"] == "露营装备"  # intents are work material
    assert results["get_kernel_info"]["kernel"]["license"]["key_stored"] is True
    assert "cdp_url" not in json.dumps(results["launch_profile"])
    assert results["get_profile"]["live_status"]["status"] == "running"


# ── Automation tier: launch_mode, get_cdp_endpoint, open_browser ─────────────

PID = "p-auto"
CDP_PATH = f"/api/profiles/{PID}/cdp"


def debug_running_status(**overrides) -> dict:
    return {
        "status": "running",
        "runtime_mode": "native",
        "viewer_mode": "native-window",
        "vnc_ws_port": 6080,
        "display": ":0",
        "cdp_url": CDP_PATH,
        "browser_engine": "cloak",
        "launch_mode": "debug",
        **overrides,
    }


def automation_fake() -> FakeManager:
    fake = FakeManager(mode="automation")
    fake.routes[("GET", "/api/profiles")] = (
        200,
        [{"id": PID, "name": "店铺A"}, {"id": "p-b", "name": "重名"}, {"id": "p-c", "name": "重名"}],
    )
    fake.routes[("GET", f"{CDP_PATH}/json/list")] = (
        200,
        [
            {"id": "T1", "type": "page", "title": "Example", "url": "https://example.com/",
             "webSocketDebuggerUrl": f"ws://127.0.0.1:9999{CDP_PATH}/devtools/page/T1"},
            {"id": "SW", "type": "service_worker", "title": "sw", "url": "https://example.com/sw.js"},
        ],
    )
    return fake


async def test_browser_tools_are_rejected_below_automation_mode():
    for mode in ("read-only", "full"):
        fake = automation_fake()
        fake.mode = mode
        for name, args in (("get_cdp_endpoint", {"profile_id": PID}), ("open_browser", {"profile": PID})):
            result = await mcp_server.dispatch(fake.client(), name, args)
            assert result["ok"] is False
            assert result["reason"] == "mode_not_automation", (mode, name, result)
        # Nothing reached the Manager's profile endpoints, and each was audited.
        assert not any(path.startswith("/api/profiles") for _, path in fake.requests)
        assert [a["reason"] for a in fake.audits] == ["mode_not_automation"] * 2


async def test_launch_debug_needs_automation_mode():
    fake = automation_fake()
    fake.mode = "full"
    result = await mcp_server.dispatch(
        fake.client(), "launch_profile", {"profile_id": PID, "launch_mode": "debug"}
    )
    assert result["reason"] == "mode_not_automation"
    assert not fake.hit("POST", f"/api/profiles/{PID}/launch")


async def test_launch_manual_never_hands_out_cdp_even_in_automation_mode():
    fake = automation_fake()
    fake.routes[("POST", f"/api/profiles/{PID}/launch")] = (
        200, {"profile_id": PID, "status": "running", "cdp_url": None, "launch_mode": "manual"},
    )
    result = await mcp_server.dispatch(fake.client(), "launch_profile", {"profile_id": PID})
    assert result["ok"] is True
    assert fake.bodies[("POST", f"/api/profiles/{PID}/launch")] == {"launch_mode": "manual"}
    assert "cdp" not in json.dumps(result)


async def test_launch_rejects_unknown_launch_mode():
    fake = automation_fake()
    result = await mcp_server.dispatch(
        fake.client(), "launch_profile", {"profile_id": PID, "launch_mode": "headless"}
    )
    assert result["reason"] == "invalid_argument"
    assert not fake.hit("POST", f"/api/profiles/{PID}/launch")


async def test_launch_debug_in_automation_mode_returns_cdp_info():
    fake = automation_fake()
    fake.routes[("POST", f"/api/profiles/{PID}/launch")] = (
        200, {"profile_id": PID, "status": "running", "cdp_url": CDP_PATH, "launch_mode": "debug"},
    )
    fake.routes[("GET", f"/api/profiles/{PID}/status")] = (200, debug_running_status())
    result = await mcp_server.dispatch(
        fake.client(), "launch_profile", {"profile_id": PID, "launch_mode": "debug"}
    )
    assert result["ok"] is True
    assert fake.bodies[("POST", f"/api/profiles/{PID}/launch")] == {"launch_mode": "debug"}
    assert result["cdp_http_endpoint"] == f"http://127.0.0.1:9999{CDP_PATH}"
    assert result["cdp_ws_endpoint"] == f"ws://127.0.0.1:9999{CDP_PATH}"


async def test_get_cdp_endpoint_returns_endpoints_and_page_tabs_only():
    fake = automation_fake()
    fake.routes[("GET", f"/api/profiles/{PID}/status")] = (200, debug_running_status())
    result = await mcp_server.dispatch(fake.client(), "get_cdp_endpoint", {"profile_id": PID})
    assert result["ok"] is True
    assert result["cdp_http_endpoint"] == f"http://127.0.0.1:9999{CDP_PATH}"
    assert result["cdp_ws_endpoint"] == f"ws://127.0.0.1:9999{CDP_PATH}"
    assert result["tabs"] == [{"id": "T1", "title": "Example", "url": "https://example.com/"}]
    assert result["auth_required"] is False
    assert "auth_hint" not in result
    assert "--cdp-endpoint" in result["usage"]["playwright_mcp"]
    # Local access paths other than the Manager proxy stay hidden.
    blob = json.dumps(result)
    assert "6080" not in blob and '":0"' not in blob


async def test_get_cdp_endpoint_auth_hint_never_echoes_the_token():
    fake = automation_fake()
    fake.routes[("GET", f"/api/profiles/{PID}/status")] = (200, debug_running_status())
    client = mcp_server.RestClient(
        "http://127.0.0.1:9999", transport=fake.transport, token="SECRET_AUTH_TOKEN_XYZ"
    )
    result = await mcp_server.dispatch(client, "get_cdp_endpoint", {"profile_id": PID})
    assert result["auth_required"] is True
    assert "Bearer" in result["auth_hint"]
    assert "SECRET_AUTH_TOKEN_XYZ" not in json.dumps(result)


async def test_get_cdp_endpoint_error_states():
    fake = automation_fake()
    status_path = ("GET", f"/api/profiles/{PID}/status")
    fake.routes[status_path] = (200, {"status": "stopped"})
    result = await mcp_server.dispatch(fake.client(), "get_cdp_endpoint", {"profile_id": PID})
    assert result["reason"] == "not_running"
    fake.routes[status_path] = (200, debug_running_status(cdp_url=None, launch_mode="manual"))
    result = await mcp_server.dispatch(fake.client(), "get_cdp_endpoint", {"profile_id": PID})
    assert result["reason"] == "cdp_unavailable"
    assert "stop_profile" in result["detail"]
    result = await mcp_server.dispatch(fake.client(), "get_cdp_endpoint", {"profile_id": "missing"})
    assert result["reason"] == "not_found"
    result = await mcp_server.dispatch(fake.client(), "get_cdp_endpoint", {})
    assert result["reason"] == "invalid_argument"


async def test_open_browser_launches_in_debug_mode_when_stopped():
    fake = automation_fake()
    status_path = f"/api/profiles/{PID}/status"
    # First status: stopped; after launch: running with CDP.
    responses = [(200, {"status": "stopped"}), (200, debug_running_status())]

    def handle_status(request):
        status, payload = responses[0] if len(responses) == 1 else responses.pop(0)
        return httpx.Response(status, json=payload)

    original = fake._handle

    def handle(request):
        if request.url.path == status_path:
            fake.requests.append((request.method, request.url.path))
            return handle_status(request)
        return original(request)

    fake.transport = httpx.MockTransport(handle)
    fake.routes[("POST", f"/api/profiles/{PID}/launch")] = (200, {"profile_id": PID, "status": "running"})
    result = await mcp_server.dispatch(fake.client(), "open_browser", {"profile": "店铺A"})
    assert result["ok"] is True
    assert result["started"] is True
    assert result["profile_id"] == PID
    assert fake.bodies[("POST", f"/api/profiles/{PID}/launch")] == {"launch_mode": "debug"}
    assert result["cdp_http_endpoint"].endswith(CDP_PATH)


async def test_open_browser_reuses_a_running_debug_browser():
    fake = automation_fake()
    fake.routes[("GET", f"/api/profiles/{PID}/status")] = (200, debug_running_status())
    result = await mcp_server.dispatch(fake.client(), "open_browser", {"profile": PID})
    assert result["ok"] is True
    assert result["started"] is False
    assert not fake.hit("POST", f"/api/profiles/{PID}/launch")
    assert not fake.hit("POST", f"/api/profiles/{PID}/stop")


async def test_open_browser_never_restarts_a_manual_browser():
    fake = automation_fake()
    fake.routes[("GET", f"/api/profiles/{PID}/status")] = (
        200, debug_running_status(cdp_url=None, launch_mode="manual")
    )
    result = await mcp_server.dispatch(fake.client(), "open_browser", {"profile": PID})
    assert result["ok"] is False
    assert result["reason"] == "already_running"
    assert not fake.hit("POST", f"/api/profiles/{PID}/launch")
    assert not fake.hit("POST", f"/api/profiles/{PID}/stop")


async def test_open_browser_resolution_errors():
    fake = automation_fake()
    result = await mcp_server.dispatch(fake.client(), "open_browser", {"profile": "重名"})
    assert result["reason"] == "invalid_argument"
    assert "p-b" in result["detail"] and "p-c" in result["detail"]
    result = await mcp_server.dispatch(fake.client(), "open_browser", {"profile": "没有这个"})
    assert result["reason"] == "not_found"
    result = await mcp_server.dispatch(fake.client(), "open_browser", {"profile": "  "})
    assert result["reason"] == "invalid_argument"


async def test_open_browser_maps_seat_busy():
    fake = automation_fake()
    fake.routes[("GET", f"/api/profiles/{PID}/status")] = (200, {"status": "stopped"})
    fake.routes[("POST", f"/api/profiles/{PID}/launch")] = (409, {"detail": "license seat in use (session limit)"})
    result = await mcp_server.dispatch(fake.client(), "open_browser", {"profile": PID})
    assert result["reason"] == "seat_busy"


# ── Manager-side endpoints ───────────────────────────────────────────────────


def test_mcp_settings_default_read_only_and_update(app_client):
    resp = app_client.get("/api/settings/mcp")
    assert resp.status_code == 200
    assert resp.json() == {"mode": "read-only"}
    resp = app_client.put("/api/settings/mcp", json={"mode": "full"})
    assert resp.status_code == 200
    assert resp.json() == {"mode": "full"}
    assert app_client.get("/api/settings/mcp").json() == {"mode": "full"}
    resp = app_client.put("/api/settings/mcp", json={"mode": "automation"})
    assert resp.status_code == 200
    assert app_client.get("/api/settings/mcp").json() == {"mode": "automation"}
    resp = app_client.put("/api/settings/mcp", json={"mode": "bogus"})
    assert resp.status_code == 422


def test_mcp_audit_endpoints_roundtrip(app_client):
    resp = app_client.post(
        "/api/mcp/audit",
        json={
            "client_name": "Claude Desktop",
            "client_version": "1.0",
            "tool": "list_profiles",
            "args_summary": {"profile_id": "p1"},
            "ok": True,
            "reason": None,
            "duration_ms": 12,
        },
    )
    assert resp.status_code == 201
    resp = app_client.post(
        "/api/mcp/audit",
        json={"tool": "launch_profile", "args_summary": {}, "ok": False, "reason": "mode_read_only"},
    )
    assert resp.status_code == 201
    rows = app_client.get("/api/mcp/audit").json()
    assert len(rows) == 2
    # Newest first.
    assert rows[0]["tool"] == "launch_profile"
    assert rows[0]["ok"] is False
    assert rows[0]["reason"] == "mode_read_only"
    assert rows[1]["tool"] == "list_profiles"
    assert rows[1]["ok"] is True
    assert rows[1]["args_summary"] == {"profile_id": "p1"}
    assert rows[1]["client_name"] == "Claude Desktop"
    assert rows[1]["duration_ms"] == 12


def test_mcp_audit_db_roundtrip(tmp_db):
    audit_id = db.record_mcp_audit(
        tool="manager_status", args_summary={"a": 1}, ok=True, duration_ms=3
    )
    assert audit_id
    rows = db.list_mcp_audit()
    assert len(rows) == 1
    assert rows[0]["tool"] == "manager_status"
    assert rows[0]["ok"] is True
    assert rows[0]["args_summary"] == {"a": 1}
    assert db.list_mcp_audit(limit=0)  # clamped, still returns the row
