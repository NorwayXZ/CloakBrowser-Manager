# 给 AI agent 的使用说明

这份文档写给要操作 CloakBrowser Manager 的 AI agent（Codex、DeepSeek harness、Claude 等），也写给负责把它们接进来的人。接入细节在 [MCP.md](MCP.md)，这里讲「是什么」和「怎么用」。

## 它是什么

CloakBrowser Manager 在本机管理一批**指纹浏览器画像（profile）**。每个画像是一个独立的浏览器身份：

- 自己的指纹（UA、平台、GPU、CPU、屏幕、时区、语言）、代理出口、Cookie 和登录状态，互相隔离。
- 画像数据在本机 `profiles/<profile-id>/`，不在项目目录里。
- 画像有两种内核：`系统 Chrome 原生模式`（更稳，不应用底层指纹参数）和 `CloakBrowser 画像模式`（应用设备画像、GPU 等参数）。看 `list_profiles` 返回的 `browser_engine`。

你（agent）不直接碰浏览器进程：所有操作都经 Manager 的 REST API，MCP 桥只是它的翻译层。

## 两种启动模式

| `launch_mode` | 用途 | CDP |
| --- | --- | --- |
| `manual`（默认） | 打开给人看、人手动操作 | 没有 |
| `debug` | 给 agent 操作页面 | 有，经 Manager 的 CDP 代理 |

`open_browser` 永远用 `debug`。已经以 `manual` 启动的画像**不会被自动重启**（会话可能是人在用），需要先 `stop_profile`。

## 权限档位（`mcp.mode`）

由人在 Manager 里设置，决定你看到哪些工具。改完要**重启 MCP 客户端**，工具列表是连接时协商的。

| 模式 | 你能做什么 |
| --- | --- |
| `off` | 桥拒绝服务 |
| `read-only`（默认） | 只读 14 个工具：看画像、预检、检测报告、养号/进化状态、内核信息 |
| `full` | 再加启停画像、跑检测/养号/进化（`launch_profile` 只能 `manual`） |
| `automation` | 再加 `open_browser`、`get_cdp_endpoint`，`launch_profile` 可用 `debug`，拿到 CDP 去操作页面 |

**为什么 CDP 单独成档**：CDP 能读取页面的全部 Cookie（`Storage.getCookies`），而桥在其他档位刻意不提供任何 Cookie 读取。开 `automation` 等于允许 agent 接触该画像的登录态，请只在需要操作页面时开，用完改回 `full` 或 `read-only`。

改模式（面板 UI 暂未提供）：

```bash
curl -X PUT http://127.0.0.1:8080/api/settings/mcp \
  -H 'Content-Type: application/json' -d '{"mode": "automation"}'
```

## 标准流程

1. `manager_status`：版本、运行数、有没有自动化在跑。第一声招呼。
2. `list_profiles`：找到画像，拿 `id`（也可以用名称）。
3. `get_profile_preflight`（可选）：现在能不能启动，有什么冲突。
4. `open_browser(profile)`：启动并返回 CDP 连接信息。已经以 `debug` 在跑则直接返回，`started=false`。
5. 用返回的 `cdp_http_endpoint` 接页面操作工具（见下）。
6. 做完 `stop_profile`。

只想打开浏览器给人用：`launch_profile`（`manual`，没有 CDP）。

## 接入页面操作工具

`open_browser` / `get_cdp_endpoint` 返回：

```json
{
  "ok": true,
  "profile_id": "...",
  "started": true,
  "cdp_http_endpoint": "http://127.0.0.1:8080/api/profiles/<id>/cdp",
  "cdp_ws_endpoint": "ws://127.0.0.1:8080/api/profiles/<id>/cdp",
  "auth_required": false,
  "tabs": [{"id": "...", "title": "...", "url": "..."}],
  "usage": {
    "playwright": "chromium.connect_over_cdp('http://127.0.0.1:8080/api/profiles/<id>/cdp')",
    "playwright_mcp": "npx @playwright/mcp@latest --cdp-endpoint http://127.0.0.1:8080/api/profiles/<id>/cdp",
    "chrome_devtools_mcp": "npx chrome-devtools-mcp@latest --browser-url http://127.0.0.1:8080/api/profiles/<id>/cdp"
  }
}
```

端点指向 Manager 自己的 CDP 代理，不是 Chrome 的原始调试端口。常见做法：

- 代码里用 Playwright / Puppeteer：直接 `connect_over_cdp(cdp_http_endpoint)`。
- 作为工具使用：再挂一个 [playwright-mcp](https://github.com/microsoft/playwright-mcp) 或 [chrome-devtools-mcp](https://github.com/ChromeDevTools/chrome-devtools-mcp)，把上面的端点交给它。命令行参数名以对应工具当前版本为准。

如果 Manager 开了鉴权（`auth_required: true`），CDP 客户端连接时要带 `Authorization: Bearer <AUTH_TOKEN>` 请求头，token 与 Manager 的 `AUTH_TOKEN` 相同；返回里不会回显 token。客户端不支持自定义请求头时，只能在不开鉴权的本机环境使用。

## 在 Codex 里配置

`~/.codex/config.toml`：

```toml
[mcp_servers.cloakbrowser-manager]
command = "<仓库>/.venv/bin/python"
args = ["-m", "backend.mcp_server"]
env = { PYTHONPATH = "<仓库的绝对路径>" }
# Manager 开了鉴权时再加：env = { PYTHONPATH = "...", AUTH_TOKEN = "..." }
```

用 `PYTHONPATH` 代替 `cwd`，这样不依赖客户端是否支持工作目录。其他客户端（Claude Desktop、Muse）见 [MCP.md](MCP.md)。

## 规则与禁忌

- **一次只开一个画像。** 免费授权只有一个并发座位。
- **不要改指纹来「绕过」问题。** 画像异常先看 `get_fingerprint_report`、`get_profile_preflight`，把结论告诉用户，而不是自己调参数。
- **不要回显或外传 Cookie、账号、代理凭据。** 桥已经对代理账密、备注做了脱敏；用 CDP 时这条靠你自觉。
- **只对任务需要的画像开 `debug`，用完就关。**
- **没有的工具是设计如此**：删除/焚毁画像、批准进化提案与养号剧本、Cookie 读取与导出、备份恢复、license 写入。需要时请用户在面板里做。

## 错误码怎么处理

工具失败统一返回 `{ok: false, reason, detail}`，按 `reason` 决定下一步：

| `reason` | 含义 | 该怎么办 |
| --- | --- | --- |
| `manager_unreachable` | Manager 没开或端口不一致 | 让用户启动 Manager，不要重试 |
| `mcp_disabled` | `mcp.mode=off` | 让用户改模式 |
| `mode_read_only` | 当前是只读模式 | 让用户改成 `full` |
| `mode_not_automation` | 需要 `automation` 档（CDP 相关） | 说明理由，让用户决定要不要开 |
| `not_found` | 画像/报告不存在 | 用 `list_profiles` 重新查 |
| `invalid_argument` | 参数缺失或有歧义（如重名） | 按 `detail` 改参数 |
| `already_running` | 画像已在运行；`open_browser` 遇到 `manual` 模式在跑也回这个 | 确认可以关后 `stop_profile` 再重试 |
| `not_running` | 画像没在跑 | `open_browser` |
| `cdp_unavailable` | 画像是 `manual` 模式启动的，没有 CDP | `stop_profile` 后 `open_browser` |
| `seat_busy` | 授权单座位被占 | 等几分钟，**不要立刻重试**；或先关掉别的画像 |
| `automation_busy` | 另一个自动化（检测/养号/进化）在跑，带 `owner` | 等它结束 |
| `conflict` / `manager_error` / `bridge_error` | 其他冲突或错误 | 读 `detail`，不要盲目重试 |

## 审计

每次工具调用都会记一条审计：`GET http://127.0.0.1:8080/api/mcp/audit`。被模式闸门拒绝的调用也会记录。
