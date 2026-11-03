# 错误码怎么处理

工具失败时回 `{"ok": false, "reason": ..., "detail": ..., "next_step": ...}`。照 `next_step` 做；下面是常见的几类。

| reason | 意思 | 怎么办 |
| --- | --- | --- |
| `manager_unreachable` | Manager 没开，或端口不对 | 让用户先打开 Manager；不要反复重试 |
| `unauthorized` / `scope_denied` | 令牌不对或范围不够 | 换范围更高的令牌，或让用户用面板操作 |
| `mcp_disabled` / `mode_read_only` / `mode_not_automation` | 当前档位不允许 | 向用户说明需要哪一档（`full` 管理与动作，`automation` 页面控制），由用户在 设置 → API 与 MCP 切换 |
| `not_found` | id / 名称 / 代理 / 分组不存在 | 用 `list_profiles` / `list_groups` / `list_proxies` 重新查 |
| `invalid_argument` | 参数不对，或带了不允许写的字段（Cookie、备注、代理账密） | 按 `detail` 改参数；不要换个名字再试写禁止的字段 |
| `conflict` | 重名、状态冲突 | 改名或先处理冲突 |
| `already_running` / `not_running` | 画像已在跑 / 没在跑 | 改前先 `stop_profile`；要页面控制用 `open_browser` |
| `cdp_unavailable` | 画像是 manual 模式开的 | 确认可关后 `stop_profile`，再 `open_browser` |
| `profile_leased` | 别人（用户或另一个 agent）在控制这个画像 | 等租约过期或让用户归还，不要强行操作 |
| `seat_busy` | 授权并发座位被占 | 等几分钟或先关掉别的画像，不要立刻重试 |
| `automation_busy` | 另一个检测 / 养号 / 进化在跑 | 等它结束，`manager_status` 能看到 |
| 页面类：`unknown_ref` `stale_ref` `page_navigating` `selector_not_found` `ambiguous_selector` `dialog_open` `timeout` | 页面状态变了或选择器不对 | 先 `browser_snapshot` 取最新状态，再重试；对话框用 `browser_dialog` |

更细的说明在仓库的 `docs/AGENT.md`。
