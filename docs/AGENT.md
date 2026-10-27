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

由人在 Manager 里设置（面板「设置 → AI 接入」，旧界面在左侧「AI 接入」，或命令行 `cloak mode`、API `PUT /api/settings/mcp`），决定你看到哪些工具。MCP 客户端改完模式要重启，工具列表是连接时协商的。

| 模式 | 你能做什么 |
| --- | --- |
| `off` | 全部拒绝 |
| `read-only`（默认） | 14 个只读工具：看画像、预检、检测报告、养号/进化状态、内核信息 |
| `full` | 再加启停画像、跑检测/养号/进化（`launch_profile` 只能 `manual`），以及 3 个邮箱工具 |
| `automation` | 再加 `open_browser`、`get_cdp_endpoint` 和 15 个页面工具，`launch_profile` 可用 `debug` |

**为什么页面控制单独成档**：CDP 能读取页面的全部 Cookie，而桥在其他档位刻意不提供任何 Cookie 读取。开 `automation` 等于允许 agent 接触该画像的登录态，请只在需要操作页面时开，用完改回 `full` 或 `read-only`。

## 标准流程

1. `manager_status`：版本、运行数、有没有自动化在跑。第一声招呼。
2. `list_profiles`：找到画像，拿 `id`（工具里也可以直接用名称）。
3. `get_profile_preflight`（可选）：现在能不能启动，有什么冲突。
4. `open_browser(profile)`：启动并返回 CDP 连接信息。已经以 `debug` 在跑则直接返回，`started=false`。
5. 操作页面（见下）。
6. 做完 `stop_profile`（同时释放控制租约）。

只想打开浏览器给人用：`launch_profile`（`manual`，没有 CDP）。

## 邮箱：注册时要邮箱和验证码

用户在 Manager 的「邮箱」页接好自己的邮箱服务器（Cloud Mail）后，`full` 档起就有这三个工具。**不要向用户要邮箱地址或验证码。**

1. `mail_get_address(profile)`：给画像一个能收信的地址。同一画像默认一直给同一个；要再注册一个账号时传 `new=true`。
2. 把地址填进注册表单并提交。
3. `mail_wait_code(address)`：等这个地址的新邮件（默认 120 秒，最多 170），直接回 `code`（验证码）和 `link`（验证链接）。只算上次取过之后的新邮件，所以同一封不会给两次。`code` 为空时读 `text` 自己找；要点链接就 `browser_navigate(link)`。
4. 没等到（`mail_timeout`）：确认表单真的提交了、地址没填错，必要时点页面上的「重新发送」，再等一次。

`mail_list_messages(address)` 可以回看这个地址最近的邮件。可以用 `from_contains` / `subject_contains` 只等某个网站的邮件，避免拿错。

## 操作页面：内置页面工具

`automation` 档下，不用再装别的工具就能操作页面。它们跑在 Manager 里，复用 Manager 已有的浏览器连接，不会额外在页面上多开一个 CDP 客户端。

| 工具 | 作用 |
| --- | --- |
| `browser_navigate(profile, url)` | 当前标签页打开网址。**只允许 http/https**，`file:` `chrome:` `javascript:` `data:` 一律拒绝 |
| `browser_snapshot(profile, viewport_only?)` | 读页面：文字轮廓，可交互元素带 `ref`，如 `[e3] button "登录"`；iframe 里的内容会列在 `--- iframe ... ---` 段，ref 全局连续编号，可以直接点；`viewport_only=true` 只列当前屏 |
| `browser_get_text(profile, ref?, offset?, max_chars?, whole_page?)` | 读纯文字，分页返回（`next_offset` 接着读）；默认只读页面主体内容，跳过菜单页脚 |
| `browser_click(profile, ref)` | 点击；若打开了新标签页会自动切过去。`ref` 可以是快照里的 `e3`，也可以是语义选择器（见下） |
| `browser_type(profile, ref, text, submit?)` | 填输入框（下拉框按选项文字选）；`submit` 填完按回车 |
| `browser_press_key(profile, key)` | 按键或组合键，如 `Enter`、`Control+A` |
| `browser_scroll(profile, direction?, amount?)` | 滚动 |
| `browser_screenshot(profile, full_page?, format?)` | 截图（默认 jpeg）；MCP 里作为图片内容返回，CLI 存成文件 |
| `browser_wait_for(profile, text?, text_gone?, url?, selector?, ms?, timeout_ms?)` | 等条件成立：文字出现 / 消失、网址包含某段、选择器可见（给几个就全部要满足），或单纯等 `ms`。每个条件最多等 `timeout_ms`（默认 15 秒，最大 30 秒） |
| `browser_dialog(profile, action, text?)` | 处理 JS 对话框（alert / confirm / prompt / beforeunload）：`accept` 或 `dismiss`，prompt 用 `text` 填内容 |
| `browser_batch(profile, steps, snapshot_after?, viewport_only?, stop_on_error?)` | 一次调用按顺序做最多 20 步（见下） |
| `browser_upload(profile, ref, paths)` | 上传文件到文件输入框，或点一个会弹出文件选择器的按钮；**只允许 agent 文件目录里的文件**（见下） |
| `browser_downloads(profile)` | 列出这个画像下载过的文件和 agent 文件目录的位置 |
| `browser_back(profile)` | 后退 |
| `browser_tabs(profile, action, index?, url?)` | `list` / `new` / `select` / `close` |

典型循环：`browser_navigate` → `browser_snapshot` → 用 snapshot 里的 `ref` 做 `browser_click` / `browser_type` → 页面变了就**重新** `browser_snapshot`。

读长页面：快照最多列约 2 万字符（`truncated=true` 时最后一行会告诉你）。要看后面的内容，`browser_scroll` 往下，再用 `viewport_only=true` 快照，只看当前一屏（在 Wikipedia 长文章上约 2 千字符，是整页快照的八分之一）；只想读文章正文，直接 `browser_get_text` 分页读。

点击或回车提交表单之后，工具会等页面跳转完成才返回，所以紧接着 `browser_snapshot` 是安全的。

### 语义选择器

`browser_click`、`browser_type`、`browser_get_text`、`browser_upload` 的 `ref` 除了快照里的 `e3`，还可以写：

| 写法 | 含义 |
| --- | --- |
| `text=登录` | 含这段文字的元素（不分大小写）；`text="登录"` 带引号是整句精确匹配 |
| `role=button[name="登录"]` | 按角色和名称，名称部分匹配；也可以只写 `role=textbox` |
| `label=邮箱` / `placeholder=搜索` | 按关联的标签文字 / 占位符 |
| `css=#submit` | CSS 选择器 |

选择器必须恰好匹配**一个可见元素**（文件上传例外：文件输入框常常是隐藏的，所以不要求可见）：没有匹配回 `selector_not_found`，多于一个回 `ambiguous_selector` 并告诉你数量，不会去猜点哪个。选择器只在顶层文档里找；iframe 里的元素请用快照的 `ref`。

选择器的最大好处是**页面跳转后依然有效**，快照的 `ref` 不行。所以跨页面的步骤（尤其是批量动作）用选择器。

### 批量动作 `browser_batch`

一次调用顺序执行最多 20 步，省掉来回往返。`steps` 里每步是 `{"do": 动词, ...该动词自己的参数}`：

```json
{"profile": "店铺A", "steps": [
  {"do": "type", "ref": "placeholder=搜索", "text": "widgets"},
  {"do": "click", "ref": "role=button[name=\"Go\"]"},
  {"do": "wait_for", "url": "/result", "timeout_ms": 5000},
  {"do": "get_text", "max_chars": 500}
]}
```

动词：`navigate(url)`、`click(ref)`、`type(ref, text, submit?)`、`press_key(key)`、`scroll(direction?, amount?)`、`wait_for(...)`、`back`、`get_text(ref?, offset?, max_chars?)`、`dialog(answer=accept|dismiss, text?)`、`tabs(tab_action, index?, url?)`、`upload(ref, paths)`。

- 某一步出错就停（返回里 `stopped="error"`、`stopped_at` 是第几步，每步的结果在 `steps` 里）；`stop_on_error=false` 则继续后面的步骤。
- 某一步弹出了对话框，如果下一步不是 `dialog` 就停（`stopped="dialog"`），因为页面被冻住了；下一步是 `dialog` 就接着处理。
- 默认在最后附一次快照（`snapshot_after=false` 关闭，`viewport_only=true` 只看当前屏）。

### JS 对话框

`alert`、`confirm`、`prompt`、`beforeunload` 会把页面冻住。工具不会卡死：触发它的动作会立刻返回，结果里带 `dialog`（类型、文字）和提示；这时其他操作都回 `dialog_open`，直到你调 `browser_dialog` 处理。没人处理 2 分钟后自动取消。

### 上传和下载

- **下载**：页面里触发的下载自动保存到 Manager 数据目录下的 `agent-files/downloads/<画像 id>/`。点了下载按钮之后调 `browser_downloads`，拿到文件的完整路径、大小和状态（链接里的查询参数不会回显，可能带密钥）。
- **上传**：为防止 agent 把本机任意文件传给网站，`browser_upload` **只认 `agent-files/` 里的文件**（符号链接和 `..` 逃逸都会被拒，单个最大 50 MB，一次最多 10 个）。要上传别处的文件，先复制进这个目录；目录位置在 `browser_downloads` 返回的 `files_dir` 里。

要点：

- `ref` 只在最近一次快照内有效。页面变化后点旧 `ref` 会得到 `stale_ref`，重新快照即可。
- 快照不改页面：元素引用保存在 Manager 里，不会在页面 DOM 里写任何属性。密码框的值不显示。
- 快照最多读 6 个 iframe（含跨域的）；不展开关闭的 shadow DOM；没有可访问名称的图标链接会显示成空名称 `""`。
- 页面一跳转到新文档，旧的 `ref` 立刻失效（`stale_ref`，不会卡到超时），重新快照即可。
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

管理员可以签发只给 agent 用的 token，比 `AUTH_TOKEN` 权限小。面板「设置 → AI 接入」里可以签发、撤销，也能看到最近的 agent 操作记录；命令行同样可以：

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
| `unknown_ref` / `stale_ref` | 元素引用无效 / 页面已跳转 | 重新 `browser_snapshot`，或改用语义选择器 |
| `selector_not_found` / `ambiguous_selector` | 选择器没匹配到 / 匹配到多个 | 写具体一点（加 `name=`），或用快照 `ref` |
| `dialog_open` / `no_dialog` | 页面被 JS 对话框冻住 / 现在没有对话框 | 先 `browser_dialog` 处理 |
| `path_not_allowed` / `files_disabled` | 上传的文件不在 agent 文件目录 / 没配置该目录 | 把文件复制进 `files_dir` 再传 |
| `page_navigating` | 页面还在跳转中 | 等一两秒再 `browser_snapshot` |
| `no_page` | 没有打开的标签页 | `browser_tabs(action=new)` 或 `browser_navigate` |
| `navigation_failed` / `timeout` | 网址打不开 / 操作超时 | `browser_snapshot` 看现状，检查代理出口 |
| `mail_not_configured` | 用户还没接好邮箱服务器 | 告诉用户去「邮箱」页配置，不要自己找别的邮箱 |
| `mail_timeout` | 等待时间内没收到新邮件 | 检查表单是否提交成功、地址是否填对，必要时重新发送后再等 |
| `mail_server_error` | 邮箱服务器出错或连不上 | 稍等再试一次，还不行把 `detail` 告诉用户 |
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
