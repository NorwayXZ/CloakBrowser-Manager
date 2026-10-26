"""Stdio MCP bridge: let an MCP client (Claude Desktop / Codex / Muse) drive
the local Manager through its existing REST API.

This process is launched by the user's own MCP client and speaks MCP over
stdio. It adds no listening port. The tools themselves live in
``backend/agent_tools.py`` (SDK-free, shared with the HTTP MCP endpoint, the
REST tool API and the CLI); this module only wires them to the ``mcp`` SDK.

This module and the Manager's optional HTTP MCP mount are the only places the
``mcp`` SDK is imported; the FastAPI app never requires it, so the panel runs
unchanged where the SDK is not installed.

Run with: ``python -m backend.mcp_server`` (Manager must be running).
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Callable

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .agent_tools import *  # noqa: F401,F403 - tests and callers use mcp_server.<name>
from .agent_tools import (  # noqa: F401
    INSTRUCTIONS,
    MODE_OFF,
    MODE_READ_ONLY,
    SERVER_NAME,
    TOOLS,
    AutoBackend,
    RestClient,
    dispatch,
    fetch_mode,
    guide_text,
    tool_description,
    visible_tools,
)


def build_mcp_tools(mode: str) -> list[types.Tool]:
    return [
        types.Tool(name=tool.name, description=tool_description(tool), input_schema=tool.input_schema)
        for tool in visible_tools(mode)
    ]


def result_content(result: dict[str, Any]) -> list[types.TextContent | types.ImageContent]:
    """MCP content for a tool result: an inline image becomes real image content
    (not a wall of base64 in the text), everything else stays JSON text."""
    image = result.get("image") if isinstance(result, dict) else None
    if isinstance(image, dict) and image.get("data"):
        rest = {**result, "image": {"mime": image.get("mime"), "bytes": image.get("bytes")}}
        return [
            types.TextContent(type="text", text=json.dumps(rest, ensure_ascii=False)),
            types.ImageContent(type="image", data=image["data"], mime_type=image.get("mime") or "image/jpeg"),
        ]
    return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


GUIDE_URI = "cloakbrowser://guide"

# Ready-made task prompts: the standard flows, so a client can offer them as one-click starts.
PROMPTS: dict[str, dict[str, Any]] = {
    "operate_profile": {
        "description": "用一个画像的浏览器完成一项任务（打开、操作页面、用完关闭）。",
        "arguments": [
            ("profile", "画像 id 或名称", True),
            ("task", "要在浏览器里完成的任务", True),
        ],
        "text": (
            "请用 CloakBrowser 画像「{profile}」完成这个任务：{task}\n\n"
            "步骤：1) manager_status 看总览；2) open_browser 打开画像（需要 automation 档）；"
            "3) browser_navigate / browser_snapshot / browser_click / browser_type 完成任务，"
            "每次页面变化后重新 browser_snapshot；4) 做完 stop_profile。\n"
            "规则：一次只开一个画像；不要读取或外传 Cookie 与账号；遇到 profile_leased 说明用户在接管，"
            "停下来等；遇到 seat_busy 等几分钟，不要立刻重试；最后汇报你做了什么、结果如何。"
        ),
    },
    "check_fingerprint": {
        "description": "只读检查一个画像的指纹是否健康，并给出结论（不改任何配置）。",
        "arguments": [("profile", "画像 id 或名称", True)],
        "text": (
            "请检查 CloakBrowser 画像「{profile}」的指纹健康度，只读，不要修改任何配置：\n"
            "1) get_profile 看配置；2) get_profile_preflight 看能否启动、有什么冲突；"
            "3) get_fingerprint_report 看逐项一致性（画像没在运行时它可能为空，那就如实说明）；"
            "4) get_linkability 看它是否和别的画像过于相似。\n"
            "最后用几句话总结：哪里有问题、严重程度、建议用户在面板里怎么处理。"
        ),
    },
}


def build_server(backend_or_client: Any) -> Server:
    """An MCP server over a tool backend.

    ``backend_or_client`` is a ``RestClient`` (wrapped in an ``AutoBackend``), a
    backend object, or a zero-argument callable returning a backend (the HTTP
    endpoint builds one per request so each call carries its caller's scope).
    """
    if isinstance(backend_or_client, RestClient):
        fixed = AutoBackend(backend_or_client)
        get_backend: Callable[[], Any] = lambda: fixed
    elif callable(backend_or_client):
        get_backend = backend_or_client
    else:
        get_backend = lambda: backend_or_client

    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        try:
            specs = await get_backend().list_tools()
        except Exception:
            specs = []
        return types.ListToolsResult(
            tools=[
                types.Tool(name=spec["name"], description=spec["description"], input_schema=spec["input_schema"])
                for spec in specs
            ]
        )

    async def on_call_tool(ctx: Any, params: Any) -> types.CallToolResult:
        client_name = client_version = None
        try:
            info = ctx.session.client_params.client_info
            client_name, client_version = info.name, info.version
        except Exception:
            pass
        result = await get_backend().call(params.name, params.arguments or {}, client_name, client_version)
        return types.CallToolResult(
            content=result_content(result),
            is_error=result.get("reason") == "unknown_tool",
        )

    async def on_list_resources(ctx: Any, params: Any) -> types.ListResourcesResult:
        return types.ListResourcesResult(
            resources=[
                types.Resource(
                    name="agent-guide",
                    title="CloakBrowser Manager 使用指南",
                    uri=GUIDE_URI,
                    description="概念、标准流程、权限档位、规则与错误码处理。",
                    mime_type="text/markdown",
                )
            ]
        )

    async def on_read_resource(ctx: Any, params: Any) -> types.ReadResourceResult:
        if str(params.uri) != GUIDE_URI:
            raise ValueError(f"unknown resource: {params.uri}")
        return types.ReadResourceResult(
            contents=[types.TextResourceContents(uri=GUIDE_URI, mime_type="text/markdown", text=guide_text())]
        )

    async def on_list_prompts(ctx: Any, params: Any) -> types.ListPromptsResult:
        return types.ListPromptsResult(
            prompts=[
                types.Prompt(
                    name=name,
                    description=spec["description"],
                    arguments=[
                        types.PromptArgument(name=arg, description=desc, required=required)
                        for arg, desc, required in spec["arguments"]
                    ],
                )
                for name, spec in PROMPTS.items()
            ]
        )

    async def on_get_prompt(ctx: Any, params: Any) -> types.GetPromptResult:
        spec = PROMPTS.get(params.name)
        if spec is None:
            raise ValueError(f"unknown prompt: {params.name}")
        given = params.arguments or {}
        missing = [arg for arg, _, required in spec["arguments"] if required and not given.get(arg)]
        if missing:
            raise ValueError(f"missing arguments: {', '.join(missing)}")
        text = spec["text"].format(**{arg: given.get(arg, "") for arg, _, _ in spec["arguments"]})
        return types.GetPromptResult(
            description=spec["description"],
            messages=[types.PromptMessage(role="user", content=types.TextContent(type="text", text=text))],
        )

    return Server(
        SERVER_NAME,
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_resources=on_list_resources,
        on_read_resource=on_read_resource,
        on_list_prompts=on_list_prompts,
        on_get_prompt=on_get_prompt,
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
