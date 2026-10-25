"""Command-line front end for agents (and people) that prefer a shell to MCP.

Every command is a thin wrapper over the same tools the MCP bridge exposes, run
through the Manager's tool API, so the permission modes, field policy, leases
and audit trail apply exactly as they do for MCP.

    python -m backend.cli info
    python -m backend.cli profiles [--json]
    python -m backend.cli open <profile> [--json]          # debug mode + CDP endpoint
    python -m backend.cli cdp <profile>                    # print the CDP endpoint
    python -m backend.cli close <profile>
    python -m backend.cli tools [--format raw|openai|anthropic]
    python -m backend.cli call <tool> ['{"json":"args"}'|-] [--out FILE]
    python -m backend.cli mode [off|read-only|full|automation]
    python -m backend.cli token create <name> <read|control|cdp> | list | revoke <id>

``<profile>`` is a profile id or its exact name. Add ``--json`` to any command
for machine-readable output on stdout (diagnostics go to stderr). Exit codes:
0 success, 1 the tool reported a problem (``reason`` is in the output),
2 bad usage, 3 the Manager is unreachable.

Environment: ``AUTH_TOKEN`` (an admin token or an agent token) when the Manager
has authentication on; ``CLOAKBROWSER_MANAGER_PORT`` for a non-default port.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .agent_tools import (
    MODES_FOR_CLI,
    AutoBackend,
    ManagerUnreachable,
    RestClient,
    tool_specs,
)

EXIT_OK, EXIT_TOOL, EXIT_USAGE, EXIT_UNREACHABLE = 0, 1, 2, 3
CLIENT_NAME = "cloak-cli"


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _save_image(result: dict[str, Any], out: str | None) -> dict[str, Any]:
    """Write an inline screenshot to a file; the output keeps a path, not base64."""
    image = result.get("image")
    if not isinstance(image, dict) or not image.get("data"):
        return result
    ext = "png" if image.get("mime") == "image/png" else "jpg"
    path = Path(out) if out else Path(tempfile.gettempdir()) / f"cloak-shot-{int(time.time() * 1000)}.{ext}"
    path.write_bytes(base64.b64decode(image["data"]))
    return {**result, "image": {"mime": image.get("mime"), "bytes": image.get("bytes"), "path": str(path)}}


class Cli:
    def __init__(self, client: RestClient | None = None) -> None:
        self.client = client or RestClient()
        # One stable holder: every `cloak` invocation is a new process, but they
        # are the same agent session as far as the profile lease goes.
        self.backend = AutoBackend(self.client, holder=CLIENT_NAME)

    async def tool(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.backend.call(name, args or {}, CLIENT_NAME, None)

    async def resolve_id(self, ref: str) -> tuple[str | None, dict[str, Any] | None]:
        listing = await self.tool("list_profiles")
        if not listing.get("ok"):
            return None, listing
        profiles = listing.get("profiles", [])
        for profile in profiles:
            if profile.get("id") == ref:
                return ref, None
        matches = [p for p in profiles if p.get("name") == ref]
        if len(matches) == 1:
            return str(matches[0]["id"]), None
        reason = "invalid_argument" if matches else "not_found"
        detail = (
            f"有多个画像叫「{ref}」，请改用 id：{', '.join(str(p['id']) for p in matches)}"
            if matches
            else f"没有 id 或名称是「{ref}」的画像。"
        )
        return None, {"ok": False, "reason": reason, "detail": detail}

    # ── commands; each returns (exit_code) after printing ──────────────────

    def report(self, result: dict[str, Any], as_json: bool, render: Any = None) -> int:
        ok = result.get("ok") is not False
        if as_json:
            _print_json(result)
        elif not ok:
            _err(f"失败：{result.get('reason')} — {result.get('detail', '')}")
            if result.get("next_step"):
                _err(f"下一步：{result['next_step']}")
        elif render is not None:
            render(result)
        else:
            _print_json(result)
        if result.get("reason") == "manager_unreachable":
            return EXIT_UNREACHABLE
        return EXIT_OK if ok else EXIT_TOOL

    async def cmd_info(self, args: argparse.Namespace) -> int:
        def render(result: dict[str, Any]) -> None:
            status = result.get("status", {})
            print(
                f"运行中 {status.get('running_count')} / 画像 {status.get('profiles_total')}"
                f"  内核 {status.get('binary_version')}  版本 {status.get('app_version') or '源码'}"
            )

        return self.report(await self.tool("manager_status"), args.json, render)

    async def cmd_profiles(self, args: argparse.Namespace) -> int:
        def render(result: dict[str, Any]) -> None:
            for p in result.get("profiles", []):
                print(f"{p.get('id')}\t{p.get('status')}\t{p.get('platform')}\t{p.get('name')}")

        return self.report(await self.tool("list_profiles"), args.json, render)

    async def cmd_open(self, args: argparse.Namespace) -> int:
        def render(result: dict[str, Any]) -> None:
            print(result["cdp_http_endpoint"])
            _err(f"画像 {result['profile_id']} {'已启动' if result.get('started') else '已在运行'}；"
                 f"标签页 {len(result.get('tabs', []))} 个。")

        return self.report(await self.tool("open_browser", {"profile": args.profile}), args.json, render)

    async def cmd_cdp(self, args: argparse.Namespace) -> int:
        profile_id, err = await self.resolve_id(args.profile)
        if err:
            return self.report(err, args.json)
        return self.report(
            await self.tool("get_cdp_endpoint", {"profile_id": profile_id}),
            args.json,
            lambda r: print(r["cdp_http_endpoint"]),
        )

    async def cmd_close(self, args: argparse.Namespace) -> int:
        profile_id, err = await self.resolve_id(args.profile)
        if err:
            return self.report(err, args.json)
        return self.report(
            await self.tool("stop_profile", {"profile_id": profile_id}),
            args.json,
            lambda r: print(f"已关闭 {r['profile_id']}"),
        )

    async def cmd_tools(self, args: argparse.Namespace) -> int:
        status, payload = await self.client.get(f"/api/agent/tools?format={args.format}")
        if status == 200 and isinstance(payload, dict):
            _print_json(payload["tools"])
            return EXIT_OK
        specs = await AutoBackend(self.client).local.list_tools()  # older Manager
        if args.format == "raw":
            _print_json(specs)
            return EXIT_OK
        mode = "automation" if any(s.get("layer") == "browser" for s in specs) else "full"
        _print_json(tool_specs(mode, fmt=args.format))
        return EXIT_OK

    async def cmd_call(self, args: argparse.Namespace) -> int:
        raw = args.arguments
        if raw == "-":
            raw = sys.stdin.read()
        try:
            arguments = json.loads(raw) if raw else {}
        except ValueError as exc:
            _err(f"参数不是合法 JSON：{exc}")
            return EXIT_USAGE
        if not isinstance(arguments, dict):
            _err("参数必须是 JSON 对象。")
            return EXIT_USAGE
        result = _save_image(await self.tool(args.tool, arguments), args.out)
        return self.report(result, True)

    async def cmd_mode(self, args: argparse.Namespace) -> int:
        if args.value is None:
            status, payload = await self.client.get("/api/settings/mcp")
        else:
            status, payload = await self.client.request("PUT", "/api/settings/mcp", json_body={"mode": args.value})
        if status >= 300:
            _err(f"失败（HTTP {status}）：{payload}")
            return EXIT_TOOL
        print(payload["mode"])
        return EXIT_OK

    async def cmd_token(self, args: argparse.Namespace) -> int:
        if args.action == "list":
            status, payload = await self.client.get("/api/agent/tokens")
        elif args.action == "create":
            if not (args.name and args.scope):
                _err("用法：token create <name> <read|control|cdp>")
                return EXIT_USAGE
            status, payload = await self.client.post(
                "/api/agent/tokens", json_body={"name": args.name, "scope": args.scope}
            )
        else:
            if not args.name:
                _err("用法：token revoke <id>")
                return EXIT_USAGE
            status, payload = await self.client.request("DELETE", f"/api/agent/tokens/{args.name}")
        if status >= 300:
            _err(f"失败（HTTP {status}）：{payload}")
            return EXIT_TOOL
        _print_json(payload)
        if args.action == "create":
            _err("token 只显示这一次，请立刻保存。")
        return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cloak", description="CloakBrowser Manager 命令行（给 agent 和人用）。")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help: str, json_flag: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help)
        if json_flag:
            p.add_argument("--json", action="store_true", help="输出 JSON")
        return p

    add("info", "Manager 总览（版本、运行数、自动化）")
    add("profiles", "列出画像")
    for name, text in (("open", "以 debug 模式打开画像并打印 CDP 端点"), ("cdp", "打印运行中画像的 CDP 端点"), ("close", "关闭画像")):
        add(name, text).add_argument("profile", help="画像 id 或名称")
    tools = add("tools", "列出当前可用的工具定义", json_flag=False)
    tools.add_argument("--format", choices=("raw", "openai", "anthropic"), default="raw")
    call = add("call", "按名字调用任意工具", json_flag=False)
    call.add_argument("tool")
    call.add_argument("arguments", nargs="?", default="", help="JSON 对象，或 - 从 stdin 读")
    call.add_argument("--out", help="截图保存路径")
    mode = add("mode", "查看或设置 mcp.mode", json_flag=False)
    mode.add_argument("value", nargs="?", choices=MODES_FOR_CLI)
    token = add("token", "管理 agent token（需要管理员权限）", json_flag=False)
    token.add_argument("action", choices=("create", "list", "revoke"))
    token.add_argument("name", nargs="?", help="create: 名称；revoke: token id")
    token.add_argument("scope", nargs="?", choices=("read", "control", "cdp"))
    return parser


async def run(argv: list[str], client: RestClient | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:  # argparse exits on usage errors
        return EXIT_USAGE if exc.code else EXIT_OK
    cli = Cli(client)
    handler = getattr(cli, f"cmd_{args.command}")
    try:
        return await handler(args)
    except ManagerUnreachable as exc:
        _err(f"连不上 Manager：{exc}")
        return EXIT_UNREACHABLE


def main() -> None:
    raise SystemExit(asyncio.run(run(sys.argv[1:])))


if __name__ == "__main__":
    main()
