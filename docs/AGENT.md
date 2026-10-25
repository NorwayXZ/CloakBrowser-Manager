# 给 AI agent 的使用说明

这份文档写给要操作 CloakBrowser Manager 的 AI agent（Codex、DeepSeek harness、Claude 等），也写给负责把它们接进来的人。MCP 接入细节在 [MCP.md](MCP.md)，这里讲「是什么」和「怎么用」。

## 它是什么

CloakBrowser Manager 在本机管理一批**指纹浏览器画像（profile）**。每个画像是一个独立的浏览器身份：

- 自己的指纹（UA、平台、GPU、CPU、屏幕、时区、语言）、代理出口、Cookie 和登录状态，互相隔离。
- 画像数据在本机 `profiles/<profile-id>/`，不在项目目录里。
- 画像有两种内核：`系统 Chrome 原生模式`（更稳，不应用底层指纹参数）和 `CloakBrowser 画像模式`（应用设备画像、GPU 等参数）。看 `list_profiles` 返回的 `browser_engine`。

你（agent）不直接碰浏览器进程：所有操作都经 Manager，工具是它的翻译层。

## 三种接入方式

| 方式 | 适合 | 怎么接 |
| --- | --- | --- |
| **stdio MCP** | Codex、Claude Desktop、Muse | `python -m backend.mcp_server`，见 [MCP.md](MCP.md) |
| **HTTP MCP** | 不想起子进程、远程或容器里的 Manager | MCP 客户端指向 `http://127.0.0.1:8080/api/agent/mcp`（streamable HTTP，无状态） |
| **REST / CLI** | 不支持 MCP 的 harness（function calling + shell） | `GET /api/agent/tools?format=openai` 拿工具定义，`POST /api/agent/tools/{name}` 调用；或 `bin/cloak` / `python -m backend.cli` |

三者背后是同一套工具、同一个权限闸门、同一份审计。

### function calling（DeepSeek harness 等）

```bash
# 工具定义，直接塞进 chat completions 的 tools 参数（format 可选 raw / openai / anthropic）
curl http://127.0.0.1:8080/api/agent/tools?format=openai

# 执行 harness 返回的 tool_call
curl -X POST http://127.0.0.1:8080/api/agent/tools/open_browser \
  -H 'Content-Type: application/json' \
  -d '{"arguments": {"profile": "店铺A"}, "client": {"name": "my-harness"}}'
```

返回永远是 JSON：成功 `{"ok": true, ...}`，失败 `{"ok": false, "reason": "...", "detail": "...", "next_step": "..."}`。给模型的 system prompt 可以直接取 `GET /api/agent/guide`（本文档）。截图随结果里的 `image.data`（base64）返回。

### 命令行

```bash
./bin/cloak info                         # 总览
./bin/cloak profiles --json
./bin/cloak open "店铺A"                  # debug 模式打开，stdout 只输出 CDP 端点
./bin/cloak call browser_navigate '{"profile":"店铺A","url":"https://example.com"}'
./bin/cloak call browser_snapshot '{"profile":"店铺A"}'
./bin/cloak call browser_screenshot '{"profile":"店铺A"}' --out /tmp/shot.jpg
./bin/cloak close "店铺A"
./bin/cloak tools --format openai        # 当前可用工具的函数定义
./bin/cloak mode automation              # 查看/设置 mcp.mode
```

`<profile>` 是 id 或完全一致的名称。退出码：`0` 成功，`1` 工具报告了问题（原因在输出里），`2` 用法错误，`3` 连不上 Manager。Windows 用 `python -m backend.cli ...`。

## 两种启动模式

| `launch_mode` | 用途 | CDP / 页面控制 |
| --- | --- | --- |
| `manual`（默认） | 打开给人看、人手动操作 | 没有 |
| `debug` | 给 agent 操作页面 | 有 |

`open_browser` 永远用 `debug`。已经以 `manual` 启动的画像**不会被自动重启**（可能有人在用），需要先 `stop_profile`。

## 权限档位

由人在 Manager 里设置（面板左侧「AI 接入」，或命令行 `cloak mode`、API `PUT /api/settings/mcp`），决定你看到哪些工具。MCP 客户端改完模式要重启，工具列表是连接时协商的。

| 模式 | 你能做什么 |
| --- | --- |
| `off` | 全部拒绝 |
| `read-only`（默认） | 14 个只读工具：看画像、预检、检测报告、养号/进化状态、内核信息 |
| `full` | 再加启停画像、跑检测/养号/进化（`launch_profile` 只能 `manual`） |
| `automation` | 再加 `open_browser`、`get_cdp_endpoint` 和 10 个页面工具，`launch_profile` 可用 `debug` |

**为什么页面控制单独成档**：CDP 能读取页面的全部 Cookie，而桥在其他档位刻意不提供任何 Cookie 读取。开 `automation` 等于允许 agent 接触该画像的登录态，请只在需要操作页面时开，用完改回 `full` 或 `read-only`。

## 标准流程

1. `manager_status`：版本、运行数、有没有自动化在跑。第一声招呼。
2. `list_profiles`：找到画像，拿 `id`（工具里也可以直接用名称）。
3. `get_profile_preflight`（可选）：现在能不能启动，有什么冲突。
4. `open_browser(profile)`：启动并返回 CDP 连接信息。已经以 `debug` 在跑则直接返回，`started=false`。
5. 操作页面（见下）。
6. 做完 `stop_profile`（同时释放控制租约）。

只想打开浏览器给人用：`launch_profile`（`manual`，没有 CDP）。

## 操作页面：内置页面工具

`automation` 档下，不用再装别的工具就能操作页面。它们跑在 Manager 里，复用 Manager 已有的浏览器连接，不会额外在页面上多开一个 CDP 客户端。

| 工具 | 作用 |
| --- | --- |
| `browser_navigate(profile, url)` | 当前标签页打开网址。**只允许 http/https**，`file:` `chrome:` `javascript:` `data:` 一律拒绝 |
| `browser_snapshot(profile)` | 读页面：文字轮廓，可交互元素带 `ref`，如 `[e3] button "登录"` |
| `browser_click(profile, ref)` | 点击；若打开了新标签页会自动切过去 |
| `browser_type(profile, ref, text, submit?)` | 填输入框（下拉框按选项文字选）；`submit` 填完按回车 |
| `browser_press_key(profile, key)` | 按键或组合键，如 `Enter`、`Control+A` |
| `browser_scroll(profile, direction?, amount?)` | 滚动 |
| `browser_screenshot(profile, full_page?, format?)` | 截图（默认 jpeg）；MCP 里作为图片内容返回，CLI 存成文件 |
| `browser_wait_for(profile, text?, ms?)` | 等文字出现，或等一会儿（最多 30 秒） |
| `browser_back(profile)` | 后退 |
| `browser_tabs(profile, action, index?, url?)` | `list` / `new` / `select` / `close` |

典型循环：`browser_navigate` → `browser_snapshot` → 用 snapshot 里的 `ref` 做 `browser_click` / `browser_type` → 页面变了就**重新** `browser_snapshot`。

要点：

- `ref` 只在最近一次快照内有效。页面变化后点旧 `ref` 会得到 `stale_ref`，重新快照即可。
- 快照不改页面：元素引用保存在 Manager 里，不会在页面 DOM 里写任何属性。密码框的值不显示。
- 快照读不到 iframe 里的内容（会在 `frames` 里报数量），也不展开关闭的 shadow DOM。
- 没有执行任意 JS 的工具，这是有意的。

### 或者把 CDP 交给别的工具

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

端点指向 Manager 自己的 CDP 代理，不是 Chrome 的原始调试端口。Playwright 的 `connect_over_cdp` 已在真实 Chrome 上验证；`--cdp-endpoint`（playwright-mcp）和 `--browser-url`（chrome-devtools-mcp）两个参数名已对照两个项目当前的官方文档核对过，但没有真的用这两个工具连过。

如果 Manager 开了鉴权（`auth_required: true`），CDP 客户端连接时要带 `Authorization: Bearer <token>` 请求头；返回里不会回显 token，`usage` 里的写法用 `<TOKEN>` 占位：

- playwright-mcp：`--cdp-endpoint <http 端点> --cdp-header 'Authorization: Bearer <TOKEN>'`
- chrome-devtools-mcp：改用 `--wsEndpoint=<ws 端点> --wsHeaders='{"Authorization":"Bearer <TOKEN>"}'`（`--browser-url` 不能带头）
- Playwright 代码：`connect_over_cdp(endpoint, headers={"Authorization": "Bearer <TOKEN>"})`

用 `cdp` 档的 agent token 就够了，不需要管理员 token。

## 控制租约与人工接管

画像可能同时有人在用。每次页面类调用（`open_browser`、`get_cdp_endpoint`、所有 `browser_*`）都会为你拿下或续上这个画像的**控制租约**：

- 默认 5 分钟，每次调用续期；`stop_profile` 或画像关闭时释放。
- 别人（另一个 agent，或用户）持有时，你会得到 `profile_leased`。**停下来等**，不要重试轰炸，也不要绕过。
- 面板里，画像一行会显示「AI 控制中：<名字>」，旁边有**接管**按钮：用户点了之后租约转给用户，并**立刻断开所有外部 CDP 连接**；你再调用会得到 `profile_leased`，直到用户点「归还给 AI」或 30 分钟过期。

租约是协作机制，不是安全边界；真正的权限边界是下面的 token 与模式。

## 范围化 token（Manager 开了鉴权时）

管理员可以签发只给 agent 用的 token，比 `AUTH_TOKEN` 权限小。面板左侧「AI 接入」里可以签发、撤销，也能看到最近的 agent 操作记录；命令行同样可以：

```bash
./bin/cloak token create "codex 笔记本" control     # 输出的 token 只显示一次
./bin/cloak token list
./bin/cloak token revoke <id>
```

| scope | 能用的工具 | 模式上限 |
| --- | --- | --- |
| `read` | 只读工具 | `read-only` |
| `control` | 只读 + 启停/检测/养号/进化 | `full` |
| `cdp` | 再加页面控制与 CDP 代理 | `automation` |

有效模式 = Manager 设置的 `mcp.mode` 与 token 上限中较低的一个。agent token **不能访问原始 REST**（那里有画像的 Cookie 和代理账密），只能用 `/api/agent/*`（字段已按脱敏策略处理），`cdp` 档另外开放 CDP 代理。token 不能管理 token。

用法：把 token 填进 `AUTH_TOKEN` 环境变量（stdio 桥、CLI），或作为 `Authorization: Bearer cbm_...` 头（REST、HTTP MCP）。stdio 桥遇到不带 `/api/agent/tools` 的旧 Manager 会回退为直接调原始 REST，这时 agent token 不够用，需要管理员 token。

没开鉴权的 Manager 不检查 token：本机任何进程本来就等同管理员。

## 在 Codex 里配置

`~/.codex/config.toml`，二选一：

```toml
# 方式一：stdio（需要仓库里的 venv）
[mcp_servers.cloakbrowser-manager]
command = "<仓库>/.venv/bin/python"
args = ["-m", "backend.mcp_server"]
env = { PYTHONPATH = "<仓库的绝对路径>" }
# Manager 开了鉴权时再加：env = { PYTHONPATH = "...", AUTH_TOKEN = "cbm_..." }
```

```toml
# 方式二：HTTP（Manager 在跑就行，不需要 venv）
[mcp_servers.cloakbrowser-manager]
url = "http://127.0.0.1:8080/api/agent/mcp"
# 开了鉴权时加 bearer_token_env_var = "CLOAK_AGENT_TOKEN"（环境变量里放 cbm_... token）
```

字段名（`command`、`args`、`env`、`cwd`、`url`、`bearer_token_env_var`）已对照 Codex 的配置参考核对；Codex 也支持 `cwd`，这里用 `PYTHONPATH` 只是少依赖一个字段。没有真的在 Codex 里跑过。其他客户端（Claude Desktop、Muse）见 [MCP.md](MCP.md)。HTTP MCP 需要 Manager 所在环境装了 `mcp` 包，没装时该端点不可用，其余接口不受影响。

## MCP 资源与提示

MCP 客户端除了工具，还能读到：

- 资源 `cloakbrowser://guide`：本文档。
- 提示 `operate_profile(profile, task)`：用某个画像完成一项任务的标准做法。
- 提示 `check_fingerprint(profile)`：只读检查画像指纹健康度。

## 规则与禁忌

- **一次只开一个画像。** 免费授权只有一个并发座位。
- **不要改指纹来「绕过」问题。** 画像异常先看 `get_fingerprint_report`、`get_profile_preflight`，把结论告诉用户，而不是自己调参数。
- **不要回显或外传 Cookie、账号、代理凭据。** 工具已对代理账密、备注做了脱敏；用 CDP 时这条靠你自觉。
- **只对任务需要的画像开 `debug`，用完就关。**
- **没有的工具是设计如此**：删除/焚毁画像、批准进化提案与养号剧本、Cookie 读取与导出、备份恢复、license 写入、执行任意 JS。需要时请用户在面板里做。

## 错误码怎么处理

工具失败统一返回 `{ok: false, reason, detail, next_step}`，`next_step` 是下一步建议，按 `reason` 决定怎么做：

| `reason` | 含义 | 该怎么办 |
| --- | --- | --- |
| `manager_unreachable` | Manager 没开或端口不一致 | 让用户启动 Manager，不要重试 |
| `unauthorized` | token 不对或已撤销 | 让用户换 token |
| `mcp_disabled` | `mcp.mode=off` | 让用户改模式 |
| `mode_read_only` | 当前是只读模式 | 让用户改成 `full` |
| `mode_not_automation` | 需要 `automation` 档（页面控制/CDP） | 说明理由，让用户决定要不要开 |
| `scope_denied` | 你的 agent token scope 不够 | 让管理员签发更高 scope 的 token |
| `not_found` | 画像/报告不存在 | 用 `list_profiles` 重新查 |
| `invalid_argument` | 参数缺失或有歧义（如重名、非 http 网址） | 按 `detail` 改参数 |
| `already_running` | 画像已在运行；`open_browser` 遇到 `manual` 模式在跑也回这个 | 确认可以关后 `stop_profile` 再重试 |
| `not_running` | 画像没在跑 | `open_browser` |
| `cdp_unavailable` | 画像是 `manual` 模式启动的，没有 CDP | `stop_profile` 后 `open_browser` |
| `profile_leased` | 画像被别人（常是用户）控制，带 `lease` | 等租约过期或用户归还 |
| `unknown_ref` / `stale_ref` | 元素引用无效 / 页面变了 | 重新 `browser_snapshot` |
| `no_page` | 没有打开的标签页 | `browser_tabs(action=new)` 或 `browser_navigate` |
| `navigation_failed` / `timeout` | 网址打不开 / 操作超时 | `browser_snapshot` 看现状，检查代理出口 |
| `seat_busy` | 授权单座位被占 | 等几分钟，**不要立刻重试**；或先关掉别的画像 |
| `automation_busy` | 另一个自动化（检测/养号/进化）在跑，带 `owner` | 等它结束 |
| `conflict` / `manager_error` / `bridge_error` | 其他冲突或错误 | 读 `detail`，不要盲目重试 |

## 检查自动化痕迹

改动 agent 层之后，可以跑回归脚本，看页面自己能观察到什么：

```bash
.venv/bin/python scripts/agent_cdp_check.py --profile "店铺A" --external-cdp
```

它在本机起一个探测页，用 `open_browser` + `browser_navigate`（以及可选的外部 Playwright 客户端）访问，输出 `navigator.webdriver`、自动化全局变量、HeadlessChrome 标记。在 Chrome 155（系统 Chrome 模式）上两条路径都是干净的。脚本里还有一个「Runtime.enable 栈 getter」探测，但它在当前 Chrome 上不会触发（显式开 `Runtime.enable` 的对照实验也是 false），所以它为 false 不能说明页面看不到 DevTools 客户端。脚本只报告，不下结论；结论要结合 `get_fingerprint_report` / `run_site_check`。

## 审计

每次工具调用都会记一条审计：`GET /api/mcp/audit`（时间、客户端名、工具、脱敏后的参数、结果、耗时）。被模式或 scope 闸门拒绝的调用也会记录。
