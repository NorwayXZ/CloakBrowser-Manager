# 常见流程

## 新建一个带代理的环境并打开

1. `list_groups`：确认分组存在，没有就 `create_group`。
2. `list_proxies`：找 `proxy_id`；库里没有就 `create_proxy`（账密只写不读）。
3. `create_profile(name, group_name, proxy_id)`。
4. 先 `get_profile_preflight(profile_id)`，没问题再 `launch_profile`（给人看用默认 `manual`）。

## 批量关闭 / 整理

1. `list_running` 看有哪些在跑，向用户说明数量。
2. 用户同意后 `stop_all_profiles`，逐个核对返回的 `failed`。
3. 整理分组：`list_profiles(group_name=…)` 翻完所有页，再 `move_profiles`（一次最多 100 个）。

## 检查一批环境是否干净

1. `run_site_check(profile_id)`（异步，同一时间只能有一个自动化）。
2. 用 `get_current_site_check` 轮询进度，不要重复触发。
3. `list_site_check_reports` → `get_site_check_report`，报告里带和上一份的对比。
4. 想快速看本机一致性：`get_fingerprint_report`（不访问外部网站）。

## 操作网页

1. `open_browser(profile)`：确保以 debug 模式运行，返回 CDP 信息。
2. `browser_navigate` → `browser_snapshot` 读结构（元素引用形如 `e3`）→ `browser_click` / `browser_type`。
3. 页面变化后引用会失效，重新 `browser_snapshot`；步骤多时用 `browser_batch` 和语义选择器（`text=…`、`role=button[name=…]`）。
4. 出现 JS 对话框用 `browser_dialog`。结束后 `stop_profile` 释放座位和租约。

## 注册账号（要邮箱验证码）

1. `account_prepare(profile)`：拿到邮箱地址、用户名和 `{{vault:…}}` 密码引用（你看不到明文）。
2. 在表单里用 `browser_type` 填邮箱、用户名；密码字段直接填 `{{vault:…}}`，由 Manager 换成真值。
3. 提交后 `mail_wait_code(address)` 等验证码，填回页面。
4. 成功后 `vault_mark(…, status=registered)`。

## 换 IP

1. `get_proxy_capabilities(proxy_id)`：看是否支持、冷却时间、受影响的环境。
2. `rotate_proxy_ip(proxy_id, request_id=…)`：同一意图重试要复用同一个 `request_id`。
3. `pending` 时用 `get_proxy_rotation_result` 轮询，`verified` 才算换成功。
