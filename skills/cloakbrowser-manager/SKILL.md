---
name: cloakbrowser-manager
description: "Operate CloakBrowser Manager, a local fingerprint-browser manager: create/update/list browser profiles (环境、画像、profile), open/close them, manage groups, proxies and the recycle bin, run fingerprint checks, and drive pages (navigate, click, type, screenshot) inside a profile. Use when the user says 打开环境、新建环境、换代理、换 IP、指纹检测、批量关闭、操作网页, or mentions CloakBrowser / 指纹浏览器 / profile."
---

# CloakBrowser Manager

CloakBrowser Manager runs on the user's own computer and manages many isolated browser identities ("profiles", 环境 / 画像). Each profile has its own fingerprint, proxy, cookies and login state. You never touch the browser process: every action goes through the Manager's tools, which apply permissions, field redaction, control leases and an audit log.

## Connect (pick one)

The Manager must be open. The default address is `http://127.0.0.1:8080`.

**HTTP MCP (nothing to install)**

```bash
# Claude Code
claude mcp add --transport http cloakbrowser-manager http://127.0.0.1:8080/api/agent/mcp
# Codex: add to ~/.codex/config.toml
#   [mcp_servers.cloakbrowser-manager]
#   url = "http://127.0.0.1:8080/api/agent/mcp"
```

If the Manager has a password / token on, send `Authorization: Bearer <token>` (Claude Code: add `--header "Authorization: Bearer <token>"`; Codex: `bearer_token_env_var = "CLOAK_AGENT_TOKEN"`). Create a scoped token with `./bin/cloak token create <name> <read|control|cdp>`; never ask for the admin password.

**No MCP (shell or function calling)**

```bash
curl -s http://127.0.0.1:8080/api/agent/tools                       # tool list for the current mode
curl -s -X POST http://127.0.0.1:8080/api/agent/tools/list_profiles -H 'Content-Type: application/json' -d '{}'
```

From a repo checkout, `./bin/cloak call <tool> '<json>'` does the same.

## Always start here

1. Call `manager_status`. It tells you the version, how many browsers run, and whether another automation is busy.
2. By default every tool is open (mode `automation`): reads, start/stop, create/update/delete profiles, approvals, page control, cookies and page JavaScript. If a tool you expect is missing, the user narrowed the mode (`read-only` shows reads only; `full` drops page control and deletion). **Do not try to work around a missing tool**: tell the user which mode is needed and let them switch it in 设置 → API 与 MCP.

## When the user says … use …

| The user wants | Tool |
| --- | --- |
| see / search environments | `list_profiles` (paged), `get_profile` |
| create an environment | `create_profile` (then `launch_profile` if asked to open it) |
| change name, proxy, timezone, group, tags… | `update_profile` |
| switch the proxy or change IP | `update_profile(proxy_id)` / `rotate_proxy_ip` |
| check a proxy works | `check_proxy_exit_ip` |
| new fingerprint / different device | `regenerate_fingerprint` / `apply_device_template` |
| open / close an environment | `launch_profile` / `open_browser` / `stop_profile` / `stop_all_profiles` |
| what is running | `list_running` |
| groups | `list_groups`, `create_group`, `move_profiles` |
| delete an environment | `delete_profile` (recycle bin, restorable) / `purge_profile` (permanent) |
| deleted environment back | `list_trash`, `restore_profile` |
| read / import cookies | `browser_cookies` (get / set / clear) |
| run JavaScript, read raw HTML | `browser_evaluate`, `browser_get_html` |
| hover, drag a slider | `browser_hover`, `browser_drag` |
| approve warm-up scripts / evolution proposals | `approve_warmup_batch`, `approve_evolution_proposal` (and the reject / dismiss pair) |
| is the fingerprint clean | `run_site_check`, `get_site_check_report`, `get_fingerprint_report` |
| operate a website | `open_browser` then the `browser_*` tools |
| sign up an account | `account_prepare` + `mail_wait_code` (see references/workflows.md) |

Every tool's trigger words and parameters are in [references/tool-reference.md](references/tool-reference.md) (generated, always current).

## Rules that are not negotiable

- **Listing:** `list_profiles` returns 200 per page. When `total_pages > 1`, read every page before acting on "all environments".
- **Confirm before changing many things:** a bulk move, bulk proxy change or `stop_all_profiles` touches the user's work. Say what you are about to do and how many items.
- **Cookies and secrets:** `browser_cookies` reads and writes cookies; use it when the task needs it and do not paste cookie values or proxy passwords into chat. Proxy passwords are write-only. Passwords for sign-ups live in the vault and reach pages only as `{{vault:…}}` references.
- **Deleting:** `delete_profile` goes to the recycle bin and is recoverable. `purge_profile` is permanent and takes the profile's whole data directory with it: use it only when the user clearly asks to delete for good.
- Do not change the fingerprint of a profile whose account is already live (`regenerate_fingerprint`, `apply_device_template`): sites see "the device changed".
- A profile opened with `launch_mode=manual` is for a person and has no CDP. Use `open_browser` (debug mode) for page work, and never restart a profile a person may be using without asking.
- If a result says `profile_leased`, someone else (often the user) is controlling that profile. Wait or ask; do not force it.
- If a result says `seat_busy`, the license seat is taken. Wait a few minutes or stop another profile; do not retry in a loop.

## Reading results

Every tool answers JSON: `{"ok": true, ...}` or `{"ok": false, "reason": "...", "detail": "...", "next_step": "..."}`. Follow `next_step`. The full list of reasons and what to do is in [references/errors.md](references/errors.md). Typical workflows are in [references/workflows.md](references/workflows.md).
