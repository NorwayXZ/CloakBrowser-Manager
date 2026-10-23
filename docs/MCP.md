# MCP 接口（stdio 桥）

CloakBrowser Manager 带一个独立的 **stdio MCP 服务器**（`backend/mcp_server.py`）。MCP 客户端（Claude Desktop、Muse 等）按需把它拉起，它把工具调用翻译成对本机 Manager REST API 的调用——让 AI agent 能看懂面板、读检测报告，并在你允许时启动/关闭浏览器。

桥不新增任何监听端口，不直接碰浏览器；Manager 本体是唯一的执行者。

## 使用前提

1. **先打开 Manager**（面板后端在跑）。桥连不上 Manager 时，所有工具只会回结构化错误 `manager_unreachable`，不会假装成功。
2. 本机装有 Python 依赖：`pip install -r backend/requirements.txt`（含 `mcp` SDK；只有桥 import 它，面板本体不依赖它）。
3. 接通后先让 agent 调一次 **`manager_status`**——这是约定的第一声招呼，能一次看清版本、运行数和当前自动化状态。

## 模式（mcp.mode）

存在 Manager 设置里，决定桥开放到什么程度：

| 模式 | 工具面 |
| --- | --- |
| `off` | 桥拒绝服务，工具列表为空 |
| `read-only`（默认） | 只读 14 个工具；动作工具不在列表里出现，直调也会被拒绝并记审计 |
| `full` | 只读 14 个 + 动作 5 个（启动/关闭画像、跑检测、跑养号、跑进化） |

查看 / 修改（面板 UI 暂未提供，用 API）：

```bash
curl http://127.0.0.1:8080/api/settings/mcp
curl -X PUT http://127.0.0.1:8080/api/settings/mcp -H 'Content-Type: application/json' -d '{"mode": "full"}'
```

第一次让 agent 碰你的浏览器，建议先在 `read-only` 下用几天，确认它读得对、说得清，再开 `full`。

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

（在仓库目录下执行；若 Manager 开了鉴权，再加 `--env AUTH_TOKEN=<同 Manager 的值>`。）

说明：

- `command` 也可以写 venv 里 python 的绝对路径（如 `<仓库>/.venv/bin/python`），保证 `mcp` 与后端依赖可导入即可。
- 自定义端口：Manager 用 `CLOAKBROWSER_MANAGER_PORT` 改端口时，桥读的是同一个环境变量/同一套发现逻辑（`backend/runtime.py` 的 `server_port()`），在客户端配置的 `env` 里给桥同样的值即可。
- `AUTH_TOKEN`：Manager 以环境变量 `AUTH_TOKEN` 开启 Bearer 鉴权时，桥必须带同值才能调通 API；没开鉴权时删掉整个 `env` 块。

## 工具一览

只读（14）：`manager_status`、`list_profiles`、`get_profile`、`get_profile_preflight`、`list_device_templates`、`get_linkability`、`list_site_check_reports`、`get_site_check_report`、`get_current_site_check`、`get_fingerprint_report`、`get_warmup_state`、`list_warmup_scripts`、`get_evolution`、`get_kernel_info`。

动作（5，需 `full`）：`launch_profile`、`stop_profile`、`run_site_check`、`run_warmup`、`run_evolution`。

结构化错误（工具失败时回 `{ok: false, reason, detail}`，agent 能据此决定下一步）：`manager_unreachable`（Manager 没开）、`not_found`、`already_running` / `not_running`、`automation_busy`（带 `owner`，另一个自动化在跑）、`seat_busy`（撞授权单座位，等几分钟座位释放，不要立刻重试）、`mode_read_only` / `mcp_disabled`、`conflict`、`invalid_argument`。

**永远不会有的工具**（设计如此，不是没做完）：删除/焚毁画像、批准或驳回进化提案与养号剧本（批准权只留面板人工）、Cookie 读取/导出、CDP 控制、license 写入、备份恢复与应用更新。

## 字段政策（agent 看不到什么）

- 画像的 `proxy` 只回 `scheme://host:port`，账号密码段剥掉；不透明分享链接只回 `configured`。
- 画像的 `notes`、`warmup_persona`（你的自由文本）默认不回；剧本批次的 persona 快照同样不回（剧本意图/搜索词会回，那是审核材料）。
- `cookies_json` 与任何 Cookie 值不回——MCP 层没有任何 Cookie 主题工具。
- license key 的值在 REST 层就不存在（只有 tier/plan/到期/`key_stored`），桥自然也拿不到。
- `cdp_url`、VNC 端口、`user_data_dir` 等本机访问路径不回。

## 审计

桥每次工具调用后都会向 Manager 上报一条审计：`GET http://127.0.0.1:8080/api/mcp/audit` 可查（时间、客户端名/版本、工具、脱敏后的参数摘要、结果、耗时）。参数摘要按同一字段政策脱敏：自由文本只记有无与长度，代理只记端点。被模式闸门拒绝的直调同样会留一条 `ok=false` 的记录。

## 故障排查

- 工具全回 `manager_unreachable`：Manager 没开，或端口不一致（检查 `CLOAKBROWSER_MANAGER_PORT` 两边是否一致）。
- 动作工具不见了：当前是 `read-only`（默认）；改 `full` 后重启客户端（工具列表在连接时协商）。
- 桥进程一启动就退出并在 stderr 抱怨被关闭：`mcp.mode=off`，改成 `read-only`/`full` 再启动客户端。
- 回 `seat_busy`：免费授权只有一个并发座位，先 `stop_profile` 关掉在跑的浏览器，或等约 4 分钟座位释放。

## 与 Muse（自定义连接器）的关系

上面是给通用 MCP 客户端（Claude Desktop / Muse）的接入方式。若要把 Manager 接进你自己的 Muse agent，那是另一条下游路径（自定义 connector 文档），不在本桥范围内；桥本身提供的 stdio 工具面就是那条路径将来要包的同一套能力。
