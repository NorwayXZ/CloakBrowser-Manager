"""End-to-end check of the agent tools, over real HTTP MCP, against a real Manager.

Unit tests prove each tool builds the right request. This proves the whole
chain an AI client uses: MCP handshake -> tool list -> tool call -> Manager ->
database / real Chromium -> answer. It starts its own Manager on a temporary
data directory and a spare port, so it never touches your real profiles.

    .venv/bin/python scripts/agent_e2e.py                # everything, including a real headless browser
    .venv/bin/python scripts/agent_e2e.py --no-browser   # skip cases that need a Chromium kernel (CI)
    .venv/bin/python scripts/agent_e2e.py --url http://127.0.0.1:8080
                                                         # use a Manager that is already running instead;
                                                         # it only creates and purges "e2e-" profiles

Exit code 0 when every case passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Awaitable, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

from backend import agent_tools  # noqa: E402

TEST_PAGE = """<!doctype html><meta charset="utf-8"><title>e2e start</title>
<body style="margin:0;font:16px sans-serif">
<h1>Agent e2e page</h1>
<input id="name" placeholder="Your name">
<button id="go" onclick="document.title = 'hello ' + document.getElementById('name').value">Say hello</button>
<div id="menu" style="padding:20px;background:#eee;width:200px"
     onmouseover="this.textContent = 'menu open'">hover me</div>
<div id="box" style="position:absolute;left:40px;top:300px;width:70px;height:36px;background:#7af;user-select:none">drag</div>
<div id="slot" style="position:absolute;left:320px;top:280px;width:120px;height:80px;border:2px dashed #888">slot</div>
<script>
let dragging = false;
document.getElementById('box').addEventListener('mousedown', () => { dragging = true; });
document.addEventListener('mouseup', (e) => {
  if (!dragging) return;
  dragging = false;
  const r = document.getElementById('slot').getBoundingClientRect();
  if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
    document.getElementById('slot').textContent = 'dropped';
  }
});
</script></body>"""


class _PageHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        body = TEST_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http_json(method: str, url: str, body: dict | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


class Manager:
    """A throwaway Manager process on a temp data dir, or an already running one."""

    def __init__(self, url: str | None) -> None:
        self.external = url is not None
        self.port = free_port() if url is None else 0
        self.url = url or f"http://127.0.0.1:{self.port}"
        self.data_dir: str | None = None
        self.process: subprocess.Popen | None = None
        self.log_path: Path | None = None

    def start(self) -> None:
        if self.external:
            return
        self.data_dir = tempfile.mkdtemp(prefix="cloak-e2e-")
        self.log_path = Path(self.data_dir) / "manager.log"
        env = {
            **os.environ,
            "CLOAKBROWSER_MANAGER_DATA_DIR": self.data_dir,
            "CLOAKBROWSER_MANAGER_PORT": str(self.port),
            "PYTHONPATH": str(ROOT),
        }
        env.pop("AUTH_TOKEN", None)
        with open(self.log_path, "wb") as log:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(self.port)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )

    def wait_ready(self, timeout: float = 90.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(f"Manager exited early:\n{self.log_tail()}")
            try:
                http_json("GET", f"{self.url}/api/status")
                return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError(f"Manager did not start within {timeout:.0f}s:\n{self.log_tail()}")

    def log_tail(self) -> str:
        if self.log_path and self.log_path.exists():
            return "\n".join(self.log_path.read_text(errors="replace").splitlines()[-25:])
        return ""

    def stop(self) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.data_dir:
            shutil.rmtree(self.data_dir, ignore_errors=True)


class Agent:
    """What an AI client sees: MCP tools over HTTP, answers parsed from their JSON."""

    def __init__(self, session: ClientSession) -> None:
        self.session = session

    async def call(self, tool: str, /, **arguments: Any) -> dict[str, Any]:
        result = await self.session.call_tool(tool, arguments)
        for block in result.content:
            if getattr(block, "type", "") == "text":
                try:
                    payload = json.loads(block.text)
                except ValueError:
                    return {"ok": not result.isError, "text": block.text}
                return payload if isinstance(payload, dict) else {"ok": True, "value": payload}
        images = [b for b in result.content if getattr(b, "type", "") == "image"]
        return {"ok": not result.isError, "images": len(images)}

    async def tool_names(self) -> list[str]:
        return [tool.name for tool in (await self.session.list_tools()).tools]


class Failed(AssertionError):
    pass


def check(condition: Any, message: str) -> None:
    if not condition:
        raise Failed(message)


def ok(result: dict[str, Any], what: str) -> dict[str, Any]:
    check(result.get("ok") is not False, f"{what}: {json.dumps(result, ensure_ascii=False)[:300]}")
    return result


CASES: list[tuple[str, bool, Callable[..., Awaitable[None]]]] = []


def case(name: str, *, browser: bool = False):
    def wrap(fn: Callable[..., Awaitable[None]]):
        CASES.append((name, browser, fn))
        return fn

    return wrap


class Context:
    def __init__(self, manager: Manager, agent: Agent, page_url: str) -> None:
        self.manager = manager
        self.agent = agent
        self.page_url = page_url
        self.tag = uuid.uuid4().hex[:6]
        self.created: list[str] = []  # profile ids to purge at the end

    def name(self, label: str) -> str:
        return f"e2e-{self.tag}-{label}"

    async def new_profile(self, label: str, **extra: Any) -> str:
        made = ok(await self.agent.call("create_profile", name=self.name(label), **extra), "create_profile")
        profile_id = made["profile"]["id"]
        self.created.append(profile_id)
        return profile_id


# ── Cases ────────────────────────────────────────────────────────────────────


@case("handshake lists every registered tool, open by default")
async def handshake(ctx: Context) -> None:
    names = await ctx.agent.tool_names()
    missing = sorted(set(agent_tools.TOOLS) - set(names))
    check(not missing, f"tools missing from the MCP list: {missing}")
    status = ok(await ctx.agent.call("manager_status"), "manager_status")
    check("version" in json.dumps(status) or status.get("ok"), "manager_status gave nothing useful")


@case("groups: create and list")
async def groups(ctx: Context) -> None:
    group = ctx.name("group")
    ok(await ctx.agent.call("create_group", name=group), "create_group")
    listed = ok(await ctx.agent.call("list_groups"), "list_groups")
    check(group in json.dumps(listed, ensure_ascii=False), "new group is not listed")


@case("profile lifecycle: create, read, update, delete, restore, purge")
async def lifecycle(ctx: Context) -> None:
    agent = ctx.agent
    profile_id = await ctx.new_profile("life", notes="first note")
    shown = ok(await agent.call("get_profile", profile_id=profile_id), "get_profile")["profile"]
    check(shown["notes"] == "first note", f"notes not readable: {shown.get('notes')!r}")
    ok(await agent.call("update_profile", profile_id=profile_id, notes="second note", account_platform="Example"), "update_profile")
    shown = ok(await agent.call("get_profile", profile_id=profile_id), "get_profile after update")["profile"]
    check(shown["notes"] == "second note" and shown["account_platform"] == "Example", "update did not stick")
    listing = ok(await agent.call("list_profiles", query=ctx.tag), "list_profiles")
    check(any(p["id"] == profile_id for p in listing["profiles"]), "profile missing from list_profiles")
    check("notes" not in listing["profiles"][0], "list_profiles should stay compact")

    ok(await agent.call("delete_profile", profile_id=profile_id), "delete_profile")
    trash = ok(await agent.call("list_trash"), "list_trash")
    check(profile_id in json.dumps(trash), "deleted profile is not in the recycle bin")
    ok(await agent.call("restore_profile", profile_id=profile_id), "restore_profile")
    check(
        profile_id not in json.dumps(ok(await agent.call("list_trash"), "list_trash again")),
        "restored profile is still in the recycle bin",
    )

    ok(await agent.call("delete_profile", profile_id=profile_id), "delete_profile again")
    ok(await agent.call("purge_profile", profile_id=profile_id), "purge_profile")
    ctx.created.remove(profile_id)
    gone = await agent.call("get_profile", profile_id=profile_id)
    check(gone.get("ok") is False and gone.get("reason") == "not_found", f"purged profile still readable: {gone}")


@case("approvals answer cleanly for ids that do not exist")
async def approvals(ctx: Context) -> None:
    for name, args in (
        ("approve_warmup_batch", {"profile_id": "nope", "batch_id": "nope"}),
        ("reject_warmup_batch", {"profile_id": "nope", "batch_id": "nope"}),
        ("approve_evolution_proposal", {"proposal_id": "nope"}),
        ("dismiss_evolution_proposal", {"proposal_id": "nope"}),
    ):
        answer = await ctx.agent.call(name, **args)
        check(answer.get("ok") is False and answer.get("reason") == "not_found", f"{name}: {answer}")


@case("narrowing the mode hides tools; reopening restores them")
async def narrowing(ctx: Context) -> None:
    url = f"{ctx.manager.url}/api/settings/mcp"
    check(http_json("GET", url)["mode"] == "automation", "default mode is not automation")
    try:
        http_json("PUT", url, {"mode": "read-only"})
        listed = await ctx.agent.tool_names()
        check("launch_profile" not in listed and "list_profiles" in listed, "read-only should hide action tools")
        denied = await ctx.agent.call("create_group", name=ctx.name("denied"))
        check(denied.get("reason") == "mode_read_only", f"read-only call was not refused: {denied}")
    finally:
        http_json("PUT", url, {"mode": "automation"})
    check("delete_profile" in await ctx.agent.tool_names(), "automation tools did not come back")


@case("real browser: open, type, click, hover, drag, HTML, JavaScript, cookies, screenshot", browser=True)
async def real_browser(ctx: Context) -> None:
    agent = ctx.agent
    profile_id = await ctx.new_profile("browser")
    opened = ok(await agent.call("open_browser", profile=profile_id), "open_browser")
    check(opened.get("cdp_http_endpoint") or opened.get("cdp"), f"no CDP info from open_browser: {list(opened)}")
    try:
        nav = ok(await agent.call("browser_navigate", profile=profile_id, url=ctx.page_url), "browser_navigate")
        check("e2e" in json.dumps(nav), "navigate did not report the page")
        snap = ok(await agent.call("browser_snapshot", profile=profile_id), "browser_snapshot")
        check("Say hello" in json.dumps(snap, ensure_ascii=False), "snapshot is missing the button")

        ok(await agent.call("browser_type", profile=profile_id, ref="placeholder=Your name", text="Ada"), "browser_type")
        ok(await agent.call("browser_click", profile=profile_id, ref='role=button[name="Say hello"]'), "browser_click")
        title = ok(await agent.call("browser_evaluate", profile=profile_id, script="() => document.title"), "evaluate")
        check(title["result"] == "hello Ada", f"typing and clicking did not work: {title['result']!r}")

        ok(await agent.call("browser_hover", profile=profile_id, ref="css=#menu"), "browser_hover")
        menu = ok(await agent.call("browser_evaluate", profile=profile_id, script="() => document.getElementById('menu').textContent"), "evaluate")
        check(menu["result"] == "menu open", f"hover did not fire: {menu['result']!r}")

        ok(await agent.call("browser_drag", profile=profile_id, ref="css=#box", to_ref="css=#slot"), "browser_drag")
        slot = ok(await agent.call("browser_evaluate", profile=profile_id, script="() => document.getElementById('slot').textContent"), "evaluate")
        check(slot["result"] == "dropped", f"drag did not land: {slot['result']!r}")

        html = ok(await agent.call("browser_get_html", profile=profile_id, ref="css=#go"), "browser_get_html")
        check("Say hello" in html["html"] and html["html"].startswith("<button"), f"unexpected HTML: {html['html'][:80]!r}")

        element = ok(
            await agent.call("browser_evaluate", profile=profile_id, ref="css=#name", script="el => el.value"), "evaluate on element"
        )
        check(element["result"] == "Ada", "element evaluate did not receive the element")

        cookie = {"name": "e2e", "value": "1", "url": ctx.page_url}
        ok(await agent.call("browser_cookies", profile=profile_id, action="set", cookies=[cookie]), "cookies set")
        got = ok(await agent.call("browser_cookies", profile=profile_id, action="get", domain="127.0.0.1"), "cookies get")
        check(any(c["name"] == "e2e" and c["value"] == "1" for c in got["cookies"]), f"cookie not read back: {got}")
        ok(await agent.call("browser_cookies", profile=profile_id, action="clear"), "cookies clear")
        after = ok(await agent.call("browser_cookies", profile=profile_id, action="get", domain="127.0.0.1"), "cookies get again")
        check(after["count"] == 0, "cookies were not cleared")

        shot = await agent.call("browser_screenshot", profile=profile_id)
        check(shot.get("images") == 1 or shot.get("ok"), f"screenshot gave no image: {shot}")
        tabs = ok(await agent.call("browser_tabs", profile=profile_id, action="list"), "browser_tabs")
        check(ctx.page_url in json.dumps(tabs), "tab list does not show the page")
    finally:
        await agent.call("stop_profile", profile_id=profile_id)


# ── Runner ───────────────────────────────────────────────────────────────────


async def run(args: argparse.Namespace) -> int:
    manager = Manager(args.url)
    page_server = HTTPServer(("127.0.0.1", 0), _PageHandler)
    threading.Thread(target=page_server.serve_forever, daemon=True).start()
    page_url = f"http://127.0.0.1:{page_server.server_address[1]}/"
    failures: list[str] = []
    ctx: Context | None = None
    try:
        manager.start()
        manager.wait_ready()
        print(f"Manager ready at {manager.url}" + ("" if manager.external else f" (data dir {manager.data_dir})"))
        async with streamable_http_client(f"{manager.url}/api/agent/mcp") as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                ctx = Context(manager, Agent(session), page_url)
                for name, needs_browser, fn in CASES:
                    if needs_browser and args.no_browser:
                        print(f"SKIP  {name}")
                        continue
                    started = time.time()
                    try:
                        await fn(ctx)
                        print(f"PASS  {name}  ({time.time() - started:.1f}s)")
                    except Exception as exc:  # noqa: BLE001 - report every failure, keep going
                        failures.append(name)
                        print(f"FAIL  {name}\n      {type(exc).__name__}: {exc}")
                for profile_id in list(ctx.created):
                    await ctx.agent.call("stop_profile", profile_id=profile_id)
                    await ctx.agent.call("delete_profile", profile_id=profile_id)
                    await ctx.agent.call("purge_profile", profile_id=profile_id)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"setup: {type(exc).__name__}: {exc}")
        print(f"FAIL  setup\n      {type(exc).__name__}: {exc}")
    finally:
        page_server.shutdown()
        if failures and not manager.external:
            print("--- Manager log (tail) ---\n" + manager.log_tail())
        manager.stop()
    print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {', '.join(failures)}"))
    return 0 if not failures else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="use this running Manager instead of starting a throwaway one")
    parser.add_argument("--no-browser", action="store_true", help="skip the cases that launch a real Chromium")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
