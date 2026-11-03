# Agent 接入对标与“平”的新风格设计

调研对象：[AdsPower/adspower-browser](https://github.com/AdsPower/adspower-browser)（MIT 许可，Skill + MCP + CLI 三件套，对接 AdsPower LocalAPI）。
只借结构和交互做法，不搬名称、图标、文案和配色。

## 一、对方是怎么让 AI 操作浏览器的

| 层 | 做法 | 好在哪里 |
| --- | --- | --- |
| MCP | npm 包 `local-api-mcp-typescript`，`PORT` + `API_KEY` 两个环境变量；每个客户端一行安装命令（Claude Code、Codex、OpenClaw、Cursor） | 复制一行就能接，不用读文档 |
| Skill | `skills/adspower-browser/SKILL.md` + 十几份 `references/*.md`，`npx skills add <仓库> --skill <名>` 安装 | AI 先读“什么时候用、怎么用、参数长什么样”，再动手，少试错 |
| CLI | `ads start / stop / status / open-browser <id> / get-browser-list '{json}'`，单值简写 + JSON 两种传参；`ads <命令> -h` 看参数 | 没有 MCP 的 agent 也能用，shell 里最简单 |
| 工具描述 | 每个工具带 `intent`（意图句）+ `triggers`（中英文触发词，如“打开环境、启动 profile”） | 用户说法和工具名对不上也能选对工具 |
| 列表约定 | 默认 `page=1,limit=200`；总页数 >1 时必须翻完再操作，文档里明写 | 避免 agent 只处理第一页 |
| 无头 | 客户端 `--headless=true --api-key=… --api-port=…` | 服务器上也能跑 |
| 覆盖面 | 环境增删改查、移动分组、回收站、分组、标签、代理、动态代理流量、内核下载、补丁、成员、清缓存、新指纹、分享、读 Cookie | 一个 agent 能把“管理”全做了 |
| 自测 | `tests/e2e-tool-validation`：每个工具一个用例，校验参数、状态、往返一致 | 工具面改动不会悄悄坏 |

## 二、我们现在有什么（对照）

我们已有 **48 个 agent 工具**，MCP 三条入口（stdio、HTTP、REST/CLI），范围化 token、控制租约、审计、保险库、字段脱敏。**操作页面的能力比对方强**：对方只交出调试端口，让 agent 自己接 Puppeteer/Selenium；我们直接提供 15 个页面工具（快照、点击、输入、等待、批量、上传下载），不用 agent 自己写自动化代码，而且有租约防止人和 AI 抢同一个环境。

**差距（对方有、我们的 agent 接口没有）**

| 缺口 | 现状 | 建议 |
| --- | --- | --- |
| 创建 / 修改环境 | REST 有（`POST/PUT /api/profiles`），agent 工具没有 | 新增 `create_profile`、`update_profile`（`full` 档；字段白名单，代理密码走保险库式引用） |
| 分组、标签、移动 | REST 有分组，agent 没有 | 新增 `list_groups`、`create_group`、`move_profiles` |
| 代理管理 | agent 只有读、检测、换 IP | 新增 `create_proxy`（密码只写不读）、`bind_proxy` |
| 回收站 | REST 有 | 新增 `list_trash`、`restore_profile`（**不给永久删除**） |
| 新指纹 / 换设备型号 | REST 有 `apply-device-template` | 新增 `apply_device_template`、`regenerate_fingerprint` |
| 清缓存 | 没有 | 新增 `clear_profile_data`（只允许清缓存、历史记录；不清 Cookie 和登录状态，那是面板里人工的事） |
| 当前打开列表 / 全部关闭 | 只有单个 | 新增 `list_running`、`stop_all_profiles` |
| 工具意图与触发词 | 描述是“中文 + 英文摘要” | 每个工具加 `intent` 和 `triggers`，对齐用户说法 |
| Skill 包 | 没有；只有 `docs/AGENT.md` | 新增 `skills/cloakbrowser-manager/SKILL.md` + `references/`，可 `npx skills add` 安装 |
| 一行安装 | 要手写 JSON | 面板“API & MCP”页按客户端（Claude Code、Codex、Cursor、通用 JSON、HTTP）生成可复制命令，**自动带上当前端口和一个新建的范围化 token** |
| 列表翻页约定 | 无分页 | `list_profiles` 加 `page/limit/total`，文档写明“翻完再操作” |
| 工具自测 | 有单测，没有“每个工具一个用例”的清单 | 新增 `tests/test_agent_tool_matrix.py`：遍历 `tool_specs` 校验必有 intent、schema、模式归属 |
| 无头运行 | 有 `bin/cloak`，无无头面板 | 文档化 `CLOAKBROWSER_HEADLESS` 用法（先调研，不承诺） |

**永远不做（和现状一致，不因对标放宽）**：读取 / 导出 Cookie、永久删除环境、批准养号剧本和进化提案、写 license、恢复备份、执行任意 JS。对方的 `get-profile-cookies`、`delete-browser`、`share-profile` 我们不照搬。

## 三、新的“API & MCP”页（设置内一个页，非独立页）

平的版式，上下分块，标签在左、内容在右：

1. **接口状态**：Manager 地址、`mcp.mode`（四档）、开关；一句话说明每档能做什么。
2. **访问令牌**：新建（名称 + 范围 `read/control/cdp`）、列表、吊销；创建时只显示一次。
3. **MCP**：标签切换客户端（Claude Code、Codex、Cursor、Claude Desktop、HTTP），每个都是一个代码块 + “复制代码”，内容用当前真实端口和刚创建的令牌填好。
4. **Skill**：`npx skills add <仓库> --skill cloakbrowser-manager`，说明什么时候该装。
5. **命令行**：`bin/cloak` 常用命令示例。
6. **最近调用**：审计日志前 20 条（时间、工具、结果、耗时）。

## 四、整套“平”的新风格（换掉玻璃卡片和渐变）

取自对方界面的结构原则：

- **背景白**，页面用 1 像素细边框分区，不用渐变、毛玻璃、大阴影。
- **一个强调色（蓝）**；状态色只用于状态。
- **新建 / 编辑环境**：一页到底；顶部下划线标签是锚点；分区标题 + 细线；**字段名在左（右对齐）、控件在右**；选项用分段按钮；右侧固定“概要”面板实时显示最终指纹。
- **列表页**：表格为主，行高紧凑，操作按钮朴素。
- **设置 / API & MCP**：分块标题 + 说明 + 左标签右内容；代码块右上角“复制代码”。
- 设计令牌：改 `design/tokens.css` 和 `tailwind.next.config.ts` 一处，全局生效；`.glass`、`.glass-strong` 改成平面样式，不删类名，避免大改。

## 五、分步实施

| 步 | 内容 | 验证 |
| --- | --- | --- |
| 1 | Agent 接口缺口：`create/update_profile`、分组、代理、回收站、新指纹、`list_running`；意图与触发词；分页；工具矩阵测试 | 后端测试；`tests` 遍历每个工具 |
| 2 | Skill 包 + 文档（SKILL.md、references、一行安装） | 技能目录自检；文档里命令可执行 |
| 3 | 面板“API & MCP”页（令牌、客户端命令、审计） | 前端测试；截图；冒烟 |
| 4 | 平的新风格：令牌 + 组件（Button、Form、Card、Table、Tabs、Dialog） | 对比度测试；328 张截图无版面问题 |
| 5 | 新建 / 编辑环境改成左标签右控件 + 分段按钮 + 概要面板 | 编辑器测试；冒烟 |
| 6 | 其余页面逐页过一遍（环境、代理、检测、数据、设置） | 截图逐页看 |

每步完成后：测试 → 截图 → PR → CI 全绿 → 合并 → 打 tag 发版。

## 六、安全默认（需要你知道的）

- 新增的“会改动”的工具都放在 `full` 档以上，默认仍是 `read-only`。
- `update_profile` 只允许改白名单字段；不允许经 agent 写 Cookie、读代理密码。
- 创建环境受授权座位和环境数量限制，超限回结构化错误。
- 所有新工具进审计，参数同样脱敏。
- 删除只能进回收站，永久删除只在面板里人工做。
