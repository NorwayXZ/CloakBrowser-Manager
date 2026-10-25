# MCP 接口

CloakBrowser Manager 有三条 agent 入口，背后是同一套工具、同一个权限闸门和同一份审计：

- **stdio MCP 桥**（`backend/mcp_server.py`）：MCP 客户端（Codex、Claude Desktop、Muse 等）按需把它拉起。桥不新增监听端口，也不直接碰浏览器，只把工具调用转给 Manager——优先调 Manager 的工具接口 `/api/agent/tools`（字段脱敏、审计都在 Manager 里做，一个范围化 token 就够用）；遇到没有这个接口的旧 Manager 会自动回退为直接调 REST（那时需要管理员 token）。
- **HTTP MCP**：Manager 自己提供 `POST /api/agent/mcp`（streamable HTTP，无状态），MCP 客户端直接填 URL，不需要起子进程、不需要 venv。要求 Manager 所在环境装了 `mcp` 包，没装时只有这个端点不可用。
- **REST / CLI**：`/api/agent/tools`（OpenAI / Anthropic / 原始格式的工具定义）+ `POST /api/agent/tools/{name}`，以及 `bin/cloak`、`python -m backend.cli`。给不支持 MCP 的 harness 用。

Manager 本体是唯一的执行者。

> 给 agent 看的使用说明（概念、标准流程、禁忌、错误码）在 [AGENT.md](AGENT.md)；桥连接时也会通过 MCP `instructions` 把要点发给 agent。

## 使用前提

1. **先打开 Manager**（面板后端在跑）。桥连不上 Manager 时，所有工具只会回结构化错误 `manager_unreachable`，不会假装成功。
2. stdio 桥要求本机装有 Python 依赖：`pip install -r backend/requirements.txt`（含 `mcp` SDK；只有桥和 HTTP MCP 端点 import 它，面板本体不依赖它）。
3. 接通后先让 agent 调一次 **`manager_status`**——这是约定的第一声招呼，能一次看清版本、运行数和当前自动化状态。

## 模式（mcp.mode）

存在 Manager 设置里，决定桥开放到什么程度：

| 模式 | 工具面 |
| --- | --- |
| `off` | 桥拒绝服务，工具列表为空 |
| `read-only`（默认） | 只读 14 个工具；动作工具不在列表里出现，直调也会被拒绝并记审计 |
| `full` | 只读 14 个 + 动作 5 个（启动/关闭画像、跑检测、跑养号、跑进化）；`launch_profile` 只能 `manual` 模式 |
| `automation` | `full` 的全部，再加浏览器工具 12 个（`open_browser`、`get_cdp_endpoint` 和 10 个页面工具），`launch_profile` 可用 `debug` 模式——这一档会把页面控制和 CDP 端点交给 agent |

查看 / 修改（面板 UI 暂未提供，用命令行或 API）：

```bash
./bin/cloak mode                # 查看
./bin/cloak mode full           # 修改
curl http://127.0.0.1:8080/api/settings/mcp
curl -X PUT http://127.0.0.1:8080/api/settings/mcp -H 'Content-Type: application/json' -d '{"mode": "full"}'
```

有效模式还会被 agent token 的 scope 压低，见 [AGENT.md](AGENT.md) 的「范围化 token」。

第一次让 agent 碰你的浏览器，建议先在 `read-only` 下用几天，确认它读得对、说得清，再开 `full`。

**`automation` 的风险**：CDP 能读取页面的全部 Cookie，等于把该画像的登录态交给了 agent。所以它单独成档，不并进 `full`。只在需要 agent 操作页面时开，用完改回 `full`。

## 客户端配置

两种客户端同构：命令都是 `python -m backend.mcp_server`，`cwd` 指向本仓库根目录。

### Claude Desktop

编辑 `claude_desktop_config.json`（macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`；Windows：`%APPDATA%\Claude\claude_desktop_config.json`），加入：

```json
{
  "mcpServers": {
    "cloakbrowser-manager": {
      "command": "python",
      "args": ["-m", "backend.mcp_server"],
      "cwd": "<本仓库的绝对路径>",
      "env": { "AUTH_TOKEN": "<与 Manager 相同，仅在 Manager 开了鉴权时填>" }
    }
  }
}
```

保存后重启 Claude Desktop，工具列表里会出现 `cloakbrowser-manager` 的工具。

### Muse

在仓库根目录放 `.mcp.json`（内容同上），或用命令添加：

```bash
Muse mcp add cloakbrowser-manager -- python -m backend.mcp_server
```

### Codex、HTTP MCP

Codex 的配置见 [AGENT.md](AGENT.md#在-codex-里配置)（stdio 和 HTTP 两种写法）。任何支持 streamable HTTP 的 MCP 客户端都可以直接填 `http://127.0.0.1:8080/api/agent/mcp`；Manager 开了鉴权时带 `Authorization: Bearer <AUTH_TOKEN 或 agent token>`。可选请求头 `X-Agent-Id` 用来区分同一个 token 下的不同 agent 会话（影响控制租约的持有者名）。

（在仓库目录下执行；若 Manager 开了鉴权，再加 `--env AUTH_TOKEN=<同 Manager 的值>`。）

说明：

- `command` 也可以写 venv 里 python 的绝对路径（如 `<仓库>/.venv/bin/python`），保证 `mcp` 与后端依赖可导入即可。
- 自定义端口：Manager 用 `CLOAKBROWSER_MANAGER_PORT` 改端口时，桥读的是同一个环境变量/同一套发现逻辑（`backend/runtime.py` 的 `server_port()`），在客户端配置的 `env` 里给桥同样的值即可。
- `AUTH_TOKEN`：Manager 以环境变量 `AUTH_TOKEN` 开启 Bearer 鉴权时，桥必须带同值才能调通 API；没开鉴权时删掉整个 `env` 块。

## 工具一览

只读（14）：`manager_status`、`list_profiles`、`get_profile`、`get_profile_preflight`、`list_device_templates`、`get_linkability`、`list_site_check_reports`、`get_site_check_report`、`get_current_site_check`、`get_fingerprint_report`、`get_warmup_state`、`list_warmup_scripts`、`get_evolution`、`get_kernel_info`。

动作（5，需 `full` 或 `automation`）：`launch_profile`、`stop_profile`、`run_site_check`、`run_warmup`、`run_evolution`。

浏览器（12，需 `automation`）：
- `open_browser(profile)`：画像 id 或名称。确保以 `debug` 模式在跑并返回 CDP 连接信息；已经以 `debug` 在跑就直接返回（`started=false`），以 `manual` 在跑则回 `already_running`，不会替你重启。
- `get_cdp_endpoint(profile_id)`：对已在 `debug` 模式运行的画像返回 CDP 连接信息（HTTP/WebSocket 端点、页面标签、接入写法）。
- 页面工具 10 个（都以 `profile`=id 或名称为第一个参数）：`browser_navigate`、`browser_snapshot`、`browser_click`、`browser_type`、`browser_press_key`、`browser_scroll`、`browser_screenshot`、`browser_wait_for`、`browser_back`、`browser_tabs`。它们跑在 Manager 里，复用 Manager 已有的浏览器连接；用法见 [AGENT.md](AGENT.md#操作页面内置页面工具)。

端点指向 Manager 自己的 CDP 代理 `/api/profiles/{id}/cdp`，不是 Chrome 的原始调试端口；开了鉴权时返回里只有 `auth_required` 和提示，不回显 token。

页面类工具每次调用都会拿下或续上画像的控制租约；别人（用户接管或另一个 agent）持有时回 `profile_leased`。

另外，MCP 客户端还能读到资源 `cloakbrowser://guide`（使用指南）和提示 `operate_profile`、`check_fingerprint`。每个工具的描述是「中文 + 英文摘要」。

`launch_profile` 另有可选参数 `launch_mode`（`manual` 默认 / `debug`）。`debug` 需要 `automation` 档，成功时一并返回 CDP 连接信息。

结构化错误（工具失败时回 `{ok: false, reason, detail, next_step}`，agent 能据此决定下一步）：`manager_unreachable`（Manager 没开）、`unauthorized`、`not_found`、`already_running` / `not_running`、`cdp_unavailable`（画像是 `manual` 模式启动的，没有 CDP）、`profile_leased`（被用户或别的 agent 控制，带 `lease`）、`automation_busy`（带 `owner`，另一个自动化在跑）、`seat_busy`（撞授权单座位，等几分钟座位释放，不要立刻重试）、`mode_read_only` / `mode_not_automation` / `scope_denied` / `mcp_disabled`、`unknown_ref` / `stale_ref` / `no_page` / `navigation_failed` / `timeout`（页面工具）、`conflict`、`invalid_argument`。完整对照表见 [AGENT.md](AGENT.md#错误码怎么处理)。

**永远不会有的工具**（设计如此，不是没做完）：删除/焚毁画像、批准或驳回进化提案与养号剧本（批准权只留面板人工）、Cookie 读取/导出、license 写入、备份恢复与应用更新、执行任意 JS。页面控制和 CDP 只在 `automation` 档开放；页面工具只允许打开 http/https 网址。

## 字段政策（agent 看不到什么）

- 画像的 `proxy` 只回 `scheme://host:port`，账号密码段剥掉；不透明分享链接只回 `configured`。
- 画像的 `notes`、`warmup_persona`（你的自由文本）默认不回；剧本批次的 persona 快照同样不回（剧本意图/搜索词会回，那是审核材料）。
- `cookies_json` 与任何 Cookie 值不回——MCP 层没有任何 Cookie 主题工具。
- license key 的值在 REST 层就不存在（只有 tier/plan/到期/`key_stored`），桥自然也拿不到。
- VNC 端口、显示号、`user_data_dir` 等本机访问路径不回。`cdp_url` 只在 `automation` 档以 Manager 代理端点的形式交出（见上）。
- 页面快照里的密码输入框不显示值；快照用的元素引用保存在 Manager 里，不会往页面 DOM 写属性。
- 范围化的 agent token 不能访问原始 REST（画像的 Cookie、代理账密在那里），只能走上面已脱敏的 `/api/agent/*`。

## 审计

每次工具调用都会在 Manager 里记一条审计（旧版桥直调 REST 时由桥上报）：`GET http://127.0.0.1:8080/api/mcp/audit` 可查（时间、客户端名/版本、工具、脱敏后的参数摘要、结果、耗时）。参数摘要按同一字段政策脱敏：自由文本只记有无与长度，代理只记端点。被模式闸门拒绝的直调同样会留一条 `ok=false` 的记录。

## 故障排查

- 工具全回 `manager_unreachable`：Manager 没开，或端口不一致（检查 `CLOAKBROWSER_MANAGER_PORT` 两边是否一致）。
- 动作工具不见了：当前是 `read-only`（默认）；改 `full` 后重启客户端（工具列表在连接时协商）。
- `open_browser` / `get_cdp_endpoint` 不见了：需要 `automation` 档，同样改完要重启客户端。
- `open_browser` 回 `already_running`：画像是以 `manual` 模式开着的（可能人在用），确认可以关后 `stop_profile` 再调。
- 桥进程一启动就退出并在 stderr 抱怨被关闭：`mcp.mode=off`，改成 `read-only`/`full` 再启动客户端。
- 回 `seat_busy`：免费授权只有一个并发座位，先 `stop_profile` 关掉在跑的浏览器，或等约 4 分钟座位释放。
- 回 `profile_leased`：用户在面板里点了「接管」，或另一个 agent 在用这个画像。租约默认 5 分钟、每次调用续期；用户点「归还给 AI」后即可继续。agent 重启后换了会话名，可能要等上一个会话的租约过期。
- 回 `scope_denied` / 403：agent token 的 scope 不够，或在访问 `/api/agent/*` 以外的原始 REST。
- HTTP MCP 端点 404 / 503：Manager 所在环境没装 `mcp` 包，或 Manager 版本太旧。

## 与 Muse（自定义连接器）的关系

上面是给通用 MCP 客户端（Claude Desktop / Muse）的接入方式。若要把 Manager 接进你自己的 Muse agent，那是另一条下游路径（自定义 connector 文档），不在本桥范围内；桥本身提供的 stdio 工具面就是那条路径将来要包的同一套能力。
