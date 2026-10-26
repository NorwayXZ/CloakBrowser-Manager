"""Tests for the agent CLI (backend/cli.py) against a fake Manager."""

from __future__ import annotations

import base64
import json

from backend import cli
from backend.tests.test_mcp_server import (
    CDP_PATH,
    PID,
    FakeManager,
    automation_fake,
    debug_running_status,
    unreachable_client,
)


async def test_profiles_json_and_table(capsys):
    fake = FakeManager(mode="read-only")
    fake.routes[("GET", "/api/profiles")] = (200, [{"id": "p1", "name": "店铺A", "platform": "macos", "status": "stopped"}])
    assert await cli.run(["profiles"], fake.client()) == 0
    assert capsys.readouterr().out.strip() == "p1\tstopped\tmacos\t店铺A"
    assert await cli.run(["profiles", "--json"], fake.client()) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 1


async def test_open_prints_only_the_endpoint_on_stdout(capsys):
    fake = automation_fake()
    fake.routes[("GET", f"/api/profiles/{PID}/status")] = (200, debug_running_status())
    assert await cli.run(["open", "店铺A"], fake.client()) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == f"http://127.0.0.1:9999{CDP_PATH}"
    assert "已在运行" in captured.err


async def test_tool_failure_exits_1_and_explains_on_stderr(capsys):
    fake = FakeManager(mode="read-only")
    assert await cli.run(["open", "x"], fake.client()) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "mode_not_automation" in captured.err and "下一步" in captured.err


async def test_unreachable_manager_exits_3(capsys):
    assert await cli.run(["info"], unreachable_client()) == 3
    assert "manager_unreachable" in capsys.readouterr().err


async def test_usage_errors_exit_2(capsys):
    fake = FakeManager()
    assert await cli.run(["nonsense"], fake.client()) == 2
    assert await cli.run(["call", "list_profiles", "{not json"], fake.client()) == 2
    assert await cli.run(["call", "list_profiles", "[1]"], fake.client()) == 2
    assert await cli.run(["token", "create"], fake.client()) == 2


async def test_close_resolves_a_name_to_an_id(capsys):
    fake = FakeManager(mode="full")
    fake.routes[("GET", "/api/profiles")] = (200, [{"id": "p1", "name": "店铺A"}])
    fake.routes[("POST", "/api/profiles/p1/stop")] = (200, {"ok": True})
    assert await cli.run(["close", "店铺A"], fake.client()) == 0
    assert fake.hit("POST", "/api/profiles/p1/stop")
    assert await cli.run(["close", "没有"], fake.client()) == 1


async def test_call_saves_screenshots_to_a_file_instead_of_printing_base64(tmp_path, capsys):
    fake = automation_fake()
    fake.routes[("POST", f"/api/profiles/{PID}/page/screenshot")] = (
        200, {"url": "u", "image": {"mime": "image/jpeg", "data": base64.b64encode(b"JPEGDATA").decode(), "bytes": 8}},
    )
    out = tmp_path / "shot.jpg"
    code = await cli.run(
        ["call", "browser_screenshot", json.dumps({"profile": PID}), "--out", str(out)], fake.client()
    )
    assert code == 0
    assert out.read_bytes() == b"JPEGDATA"
    printed = capsys.readouterr().out
    # Compare parsed JSON, not the raw text: JSON escapes the backslashes of a Windows path.
    assert json.loads(printed)["image"]["path"] == str(out)
    assert base64.b64encode(b"JPEGDATA").decode() not in printed


async def test_mode_get_and_set(capsys):
    fake = FakeManager(mode="full")
    assert await cli.run(["mode"], fake.client()) == 0
    assert capsys.readouterr().out.strip() == "full"
    assert await cli.run(["mode", "automation"], fake.client()) == 0
    assert capsys.readouterr().out.strip() == "automation"
    assert await cli.run(["mode", "root"], fake.client()) == 2
