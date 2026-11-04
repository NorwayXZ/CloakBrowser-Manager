# 工具参考（自动生成，请勿手改）

由 `python scripts/gen_skill_reference.py` 从 Manager 的工具注册表生成；`pytest` 会检查它没有过期。

共 72 个工具。每个工具的“触发词”是用户常用说法，用来对上你该选哪个工具。

## 只读工具（21）

`read-only` 档以上都能用

### `manager_status`

Manager 总览：应用版本、内核版本、运行中的浏览器数、画像总数，以及当前正在跑的自动化（检测/养号/进化）。接通后先调这个。

*Overview: versions, running browsers, profile count, active automation. Call this first.*

触发词：状态,概览,版本,先看看,status,overview,health

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `include_automation_hours` | boolean |  | 是否一并返回自动化时段设置（默认 False） |

### `list_profiles`

列出画像的摘要（id、名称、平台、设备模板、时区/语言、指纹配置、养号与进化开关、运行状态），默认每页 200 个，可按分组、名称、运行状态筛选。total_pages 大于 1 时必须翻完所有页再对“全部画像”做事。代理只回出口端点不带账密，备注与 Cookie 不回。

*List profiles, 200 per page (page/limit; filter by group_name, query, status). Walk every page before acting on "all". Proxy shown as endpoint only; no notes or cookies.*

触发词：列出环境,所有画像,搜索环境,查询环境,list profiles,search profiles,show all

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | integer |  | 第几页（从 1 开始）（默认 1） |
| `limit` | integer |  | 每页多少个，默认 200（默认 200） |
| `group_name` | string |  | 只看这个分组 |
| `query` | string |  | 名称里包含这段文字（不区分大小写） |
| `status` | running / stopped |  | 只看运行中或已停止的 |

### `get_profile`

看单个画像的完整配置（含备注 notes 和养号人设）加实时运行状态。代理只显示地址，不显示账号密码。

*One profile's full config (same field policy) plus live run state.*

触发词：环境详情,画像配置,查看配置,profile details,show config

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `get_profile_preflight`

启动前一致性检查：这个画像现在能不能启动、有哪些问题。launch 之前可以先看它。

*Pre-launch consistency check: can this profile launch now, and what is wrong.*

触发词：能不能启动,启动前检查,preflight,can it launch

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `list_device_templates`

列出设备模板库（104 个真实 Windows 设备）的摘要：id、名称、屏幕、GPU、CPU、核数、内存。

*Device template library summary (id, screen, GPU, CPU, cores, memory).*

触发词：设备模板,设备型号,device templates

无参数。

### `get_linkability`

关联分析：哪些画像看起来像同一个人（共用代理出口/设备/指纹种子等），附原因与改进建议。

*Which profiles look like the same person (shared proxy exit / device / seed), with reasons and fixes.*

触发词：关联,会不会被关联,同一个人,linkability,linked accounts

无参数。

### `list_site_check_reports`

列出已保存的指纹检测报告的元数据与通过计数（不含逐项明细，明细用 get_site_check_report）。

*Saved fingerprint site-check reports (metadata and pass counts).*

触发词：检测报告列表,历史检测,check reports

无参数。

### `get_site_check_report`

读一份完整的指纹检测报告（含与上一份的 diff、是否无头运行的标记）。

*One full fingerprint site-check report, with diff against the previous one.*

触发词：检测报告详情,对比上一次,check report

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `report_id` | string | 是 | 报告 id（先用 list_site_check_reports 查） |

### `get_current_site_check`

看正在进行中的指纹检测的进度快照（run_site_check 之后轮询这个）。

*Progress of the running site check (poll after run_site_check).*

触发词：检测进度,检测到哪了,check progress

无参数。

### `get_fingerprint_report`

读画像的本地指纹探针报告（逐项一致性检查结果，不访问外部检测站）。

*A profile's local fingerprint probe report (per-item consistency; no external sites).*

触发词：指纹自检,指纹报告,本地探针,fingerprint report

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `get_warmup_state`

看画像的养号状态：开关、每日上限、目标平台、身份年龄、最近运行记录。

*Warm-up state: switch, daily cap, targets, identity age, recent runs.*

触发词：养号状态,养号进度,warmup state

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `list_warmup_scripts`

看画像的 AI 养号剧本批次：状态、主题与意图（搜索词）。persona 快照不回。批准/驳回用 approve_warmup_batch / reject_warmup_batch。

*Warm-up script batches awaiting or past review (intents and search terms only).*

触发词：养号剧本,待审核剧本,warmup scripts

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `get_evolution`

看自对抗进化：引擎状态、待人工批准的提案、实验战报。section 可选 status/proposals/logs/all（默认 all）。批准提案用 approve_evolution_proposal，驳回用 dismiss_evolution_proposal。

*Evolution state, pending proposals and logs.*

触发词：进化状态,进化提案,evolution

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `section` | all / status / proposals / logs |  | （默认 all） |

### `get_kernel_info`

看浏览器内核信息：版本、已安装内核、授权状态（只有 tier/plan/到期/key 是否已存，key 值本身任何接口都不返回）。

*Browser kernel info: versions, installed kernels, license tier (never the key).*

触发词：内核版本,授权信息,kernel,license tier

无参数。

### `list_proxies`

列出已保存代理及换 IP 能力；仅返回端点，不返回账号密码或刷新链接。

*List saved proxy endpoints and their rotation capabilities without credentials.*

触发词：代理列表,代理库,list proxies

无参数。

### `get_proxy_capabilities`

查看代理或环境是否支持一键换 IP、冷却时间及受影响环境。不会暴露切换链接。

*Discover IP rotation support, cooldown and affected profiles.*

触发词：能否换 IP,换 IP 冷却,rotation support

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `proxy_id` | string |  | list_proxies 返回的代理编号 |
| `profile_id` | string |  | 可改用环境编号，检查该环境真实绑定的代理 |

### `check_proxy_exit_ip`

经代理/环境的实际直连或中转路径，建立新连接检测最终出口 IP；不触发换 IP，不代表旧网页连接已重连。

*Check a new connection through the selected proxy route without rotating its IP.*

触发词：检测代理,出口 IP,代理通不通,check proxy,exit ip

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `proxy_id` | string |  | list_proxies 返回的代理编号 |
| `profile_id` | string |  | 可改用环境编号，检查该环境真实绑定的代理 |

### `get_proxy_rotation_result`

查看一次换 IP 操作的进度/结果。pending 时继续查询，不要重新触发切换。verified 才表示已确认改变。

*Read a rotation job without triggering another refresh request.*

触发词：换 IP 结果,rotation result

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `job_id` | string | 是 |  |

### `list_groups`

列出全部分组（id、名称、颜色）和每个分组里有多少个画像。新建画像、移动画像前先看这里。

*List groups with how many profiles each holds.*

触发词：分组列表,有哪些分组,list groups

无参数。

### `list_running`

现在正在运行的画像（id、名称、启动模式）。想知道占了几个授权座位、要不要先关几个时看这里。

*Profiles that are running now (id, name, mode); shows how many license seats are used.*

触发词：正在运行,已打开,开着的环境,opened browsers,running profiles

无参数。

### `list_trash`

回收站里的画像（7 天内删除的，可用 restore_profile 恢复）。只回摘要。

*Profiles in the recycle bin (deleted within 7 days), recoverable with restore_profile.*

触发词：回收站,最近删除,已删除环境,recycle bin,trash

无参数。

## 动作与管理工具（23）

需要 `full` 档（令牌范围 `control`）

### `launch_profile`

启动一个画像的浏览器。已在跑会回 already_running；撞上授权单座位会回 seat_busy（座位释放需要几分钟，不要立刻重试）。launch_mode=debug 会同时开放 CDP 并回连接信息，仅 mcp.mode=automation 可用；想操作页面直接用 open_browser。

*Start a profile's browser. manual = for people, no CDP; debug = CDP for agents (automation mode only).*

触发词：打开环境,启动浏览器,启动画像,open profile,launch,start browser

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |
| `launch_mode` | manual / debug |  | manual（默认）：给人用，没有 CDP。debug：开放 CDP 供 agent 操作页面，只在 mcp.mode=automation 下可用；要操作页面更省事的是直接用 open_browser。（默认 manual） |

### `rotate_proxy_ip`

调用已配置的供应商链接切换 SOCKS5 IP，并经环境实际直连/中转路径验证。可能影响共享代理的其他环境；不会自动关闭浏览器。仅 verified 表示确认新 IP；其他结果不要盲目重试，用 job_id 查询，并复用 request_id。

*Rotate a SOCKS5 exit via its configured supplier link and verify the actual route.*

触发词：换 IP,切换 IP,刷新代理,rotate ip,change ip

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `proxy_id` | string | 是 |  |
| `profile_id` | string |  |  |
| `request_id` | string |  | 同一意图重试须复用此编号，避免再次换 IP |
| `wait_seconds` | integer |  | （默认 90） |

### `stop_profile`

关闭一个正在运行的画像浏览器。没在跑会回 not_running。

*Stop a running profile's browser and release its control lease.*

触发词：关闭环境,关闭浏览器,停止画像,close browser,stop profile

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `run_site_check`

对画像跑一轮指纹检测（异步：先关掉该画像的浏览器再以调试模式重开，测完自动关闭）。返回任务快照，进度用 get_current_site_check 轮询，报告用 list_site_check_reports 查。另一个自动化在跑时回 automation_busy。

*Run a fingerprint site check (async; relaunches the profile in debug and closes it afterwards).*

触发词：跑检测,指纹检测,验收环境,run check,fingerprint test

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `run_warmup`

立刻给画像跑一轮养号（不等定时调度）。另一个自动化在跑时回 automation_busy。

*Run one warm-up round now.*

触发词：养号,跑一轮养号,run warmup

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `run_evolution`

立刻给画像跑一轮自对抗进化实验（只在一次性克隆上实验，胜出方案变成待批提案，不直接改真画像）。另一个进化周期在跑时回 conflict/automation_busy。

*Run one evolution experiment round now (on disposable clones only).*

触发词：进化,跑一轮进化,run evolution

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `mail_get_address`

给画像一个能收信的邮箱地址，注册账号时填它。同一画像默认一直给同一个地址；new=true 再发一个新的。填进表单提交后，用 mail_wait_code 取验证码。邮箱没配置回 mail_not_configured。

*Get a receiving email address for a profile (the same one each time; new=true for another). Fill it into a sign-up form, then call mail_wait_code.*

触发词：收件邮箱,注册邮箱,get email address

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称：地址记在这个画像名下，以后再要会给同一个 |
| `new` | boolean |  | true = 给这个画像再发一个新地址（同一画像注册第二个账号时用）（默认 False） |
| `domain` | string |  | 可选：指定域名（如 example.com），不填随机选一个 |

### `mail_wait_code`

等这个地址收到新邮件（只算上次取过之后的新邮件），直接回验证码 code 和验证链接 link。提交注册表单后调用；默认最多等 120 秒，没等到回 mail_timeout。code 为空时看 text 自己找。

*Wait for a new mail to the address and return the extracted verification code / link (default 120 s, max 170 s).*

触发词：等验证码,收验证码,wait verification code

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `address` | string | 是 | mail_get_address 给的邮箱地址 |
| `timeout_s` | number |  | 最多等多少秒（默认 120，上限 170）（默认 120） |
| `from_contains` | string |  | 可选：发件人里要包含的文字，如 github.com |
| `subject_contains` | string |  | 可选：标题里要包含的文字 |

### `mail_list_messages`

列出这个地址最近收到的邮件（新的在前），每封带提取出的 code / link 和正文开头。用来回看已经取过的验证码或邮件内容。

*Recent mail to the address, newest first, with extracted code / link and a text excerpt.*

触发词：收到的邮件,看邮件,list mail

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `address` | string | 是 | mail_get_address 给的邮箱地址 |
| `limit` | integer |  | （默认 5） |

### `create_profile`

新建一个画像（环境）。只需要名称，其余有默认值；可选分组、代理（proxy_id）、设备系统、设备模板、时区、语言、账号平台、启动网址、标签。不能写 Cookie、备注，也不能直接填代理账密（要用代理先 create_proxy）。受授权环境数量限制。

*Create a profile (name required; optional group, proxy_id, platform, device template, timezone, locale, startup URLs, tags). No cookies or notes; subject to the license's profile limit.*

触发词：新建环境,创建画像,添加浏览器,新开环境,create profile,new profile,add browser

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | 画像名称（只用来自己识别） |
| `platform` | windows / macos / linux |  | 设备系统；新建时不填就用本机系统（本地版只能启动和本机同系统的画像） |
| `group_name` | string |  | 分组名称（先用 list_groups 查；没有就先 create_group） |
| `proxy_id` | string |  | list_proxies 里的 proxy_id；不填表示不改/直连 |
| `device_profile` | string |  | 设备模板 id（list_device_templates 查） |
| `timezone` | string |  | 例如 America/New_York；不填跟随出口 IP |
| `locale` | string |  | 例如 en-US；不填跟随出口 IP |
| `account_platform` | string |  | 这个画像对应的账号平台，如 Amazon |
| `startup_urls` | array<string> |  | 启动时自动打开的 http/https 网址 |
| `color_scheme` | light / dark / no-preference |  |  |
| `tags` | array<string> |  | 标签（文字） |
| `notes` | string |  | 备注（自由文本） |
| `warmup_persona` | string |  | 养号人设（一句话） |
| `cookies_json` | string |  | 要导入的 Cookie（JSON 数组字符串）；环境在运行时请用 browser_cookies |
| `proxy` | string |  | 直接写代理地址，如 socks5://user:pass@host:port；想复用代理库里的就用 proxy_id |
| `launch_args` | array<string> |  | 额外的浏览器启动参数 |
| `headless` | boolean |  |  |
| `humanize` | boolean |  | 拟人化输入/鼠标 |
| `human_preset` | default / careful |  |  |
| `geoip` | boolean |  | 时区/语言是否跟随出口 IP |
| `auto_launch` | boolean |  | Manager 启动时自动打开 |

### `update_profile`

修改画像的名称、分组、代理、设备系统/模板、时区、语言、账号平台、启动网址、颜色模式或标签。只给要改的字段。运行中的画像改动要先 stop_profile。备注、养号人设、Cookie（cookies_json）、直连代理地址也能改。

*Change a profile's name, group, proxy, platform, device template, timezone, locale, startup URLs, color scheme or tags. Stop it first if it is running.*

触发词：修改环境,改配置,改代理,改时区,编辑画像,update profile,edit settings,change proxy

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |
| `name` | string |  | 画像名称（只用来自己识别） |
| `platform` | windows / macos / linux |  | 设备系统；新建时不填就用本机系统（本地版只能启动和本机同系统的画像） |
| `group_name` | string |  | 分组名称（先用 list_groups 查；没有就先 create_group） |
| `proxy_id` | string |  | list_proxies 里的 proxy_id；不填表示不改/直连 |
| `device_profile` | string |  | 设备模板 id（list_device_templates 查） |
| `timezone` | string |  | 例如 America/New_York；不填跟随出口 IP |
| `locale` | string |  | 例如 en-US；不填跟随出口 IP |
| `account_platform` | string |  | 这个画像对应的账号平台，如 Amazon |
| `startup_urls` | array<string> |  | 启动时自动打开的 http/https 网址 |
| `color_scheme` | light / dark / no-preference |  |  |
| `tags` | array<string> |  | 标签（文字） |
| `notes` | string |  | 备注（自由文本） |
| `warmup_persona` | string |  | 养号人设（一句话） |
| `cookies_json` | string |  | 要导入的 Cookie（JSON 数组字符串）；环境在运行时请用 browser_cookies |
| `proxy` | string |  | 直接写代理地址，如 socks5://user:pass@host:port；想复用代理库里的就用 proxy_id |
| `launch_args` | array<string> |  | 额外的浏览器启动参数 |
| `headless` | boolean |  |  |
| `humanize` | boolean |  | 拟人化输入/鼠标 |
| `human_preset` | default / careful |  |  |
| `geoip` | boolean |  | 时区/语言是否跟随出口 IP |
| `auto_launch` | boolean |  | Manager 启动时自动打开 |

### `apply_device_template`

把一个设备模板（屏幕、显卡、CPU、内存）套到画像上；模板 id 用 list_device_templates 查。运行中的画像要先 stop_profile。

*Apply a device template (screen, GPU, CPU, memory) to a profile.*

触发词：套用设备模板,换设备型号,apply template,change device

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id |
| `template_id` | string | 是 | list_device_templates 里的模板 id |

### `regenerate_fingerprint`

给画像换一个新的指纹种子（Canvas、WebGL、音频、字体等噪声随之变化）。账号已经在用的画像别随便换：网站会看到“设备变了”。运行中的画像要先 stop_profile。

*Give a profile a new fingerprint seed. Do not use it on profiles whose account is already live.*

触发词：换新指纹,重新生成指纹,new fingerprint,regenerate fingerprint

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `reset_profile`

一键重置环境：把这个画像变成一个全新的浏览器——Cookie、登录状态、LocalStorage/IndexedDB、历史、缓存、Service Worker 全部删除（不可恢复），并重新随机生成指纹（种子、设备、分辨率、显卡、CPU、内存、UA）；时区和语言清空，下次启动按代理出口 IP 自动匹配。名称、分组、备注、标签、代理绑定和换 IP 链接都保留。运行中会先正常关闭。注册失败想换个干净环境、又要留着同一个代理 IP 时用它。必须带 confirm=true。bindings 决定这个画像的邮箱地址和保险库账号：unbind（默认，保留但解绑）/ keep（仍绑在这个画像）/ delete（删除记录）。

*Turn a profile into a brand-new browser: wipe cookies, logins, storage, history and cache (not recoverable) and roll a new fingerprint, keeping name, group, notes and the proxy. Needs confirm=true.*

触发词：重置环境,一键重置,换环境,清空环境,全新环境,注册失败,reset profile,fresh browser,wipe profile,new environment

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |
| `confirm` | boolean | 是 | 必须为 true：浏览器数据删除后不可恢复 |
| `bindings` | unbind / keep / delete |  | 邮箱地址和保险库账号怎么处理，默认 unbind |

### `create_group`

新建一个分组。名称已存在会回 conflict。

*Create a group.*

触发词：新建分组,创建分组,create group,new group

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | 分组名称（1~64 个字） |
| `color` | string |  | 可选：十六进制颜色，如 #3b82f6 |

### `move_profiles`

把一批画像移到某个分组（先用 list_groups 确认分组存在）。单个失败不影响其他，结果里逐个说明。

*Move up to 100 profiles into a group; per-profile results.*

触发词：移动分组,换组,归类,move to group,regroup

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_ids` | array<string> | 是 |  |
| `group_name` | string | 是 | 目标分组名称 |

### `restore_profile`

把回收站里的画像恢复回来（先用 list_trash 查 id）。

*Restore a profile from the recycle bin.*

触发词：恢复环境,还原回收站,找回已删除,restore profile,undelete

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `create_proxy`

保存一个代理到代理库（之后用 proxy_id 绑定到画像）。账号密码只写不读：保存后任何工具都看不到它。格式如 socks5://user:pass@host:port。

*Save a proxy to the proxy library (credentials are write-only); bind it to profiles via proxy_id.*

触发词：添加代理,保存代理,新建代理,add proxy,save proxy

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | 代理名称（1~64 个字） |
| `proxy` | string | 是 | 代理地址，如 socks5://user:pass@host:port 或 http://host:port |

### `stop_all_profiles`

关闭所有正在运行的画像浏览器（逐个关，结果里逐个说明）。有人在接管的画像会被跳过并说明。

*Stop every running profile browser; per-profile results.*

触发词：全部关闭,关掉所有浏览器,close all,stop all

无参数。

### `approve_warmup_batch`

批准一批 AI 养号剧本，之后 run_warmup 才会用它们。

*Approve a batch of AI warm-up scripts so run_warmup can use them.*

触发词：批准养号剧本,通过剧本,approve warmup

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id |
| `batch_id` | string | 是 | list_warmup_scripts 里的批次 id |

### `reject_warmup_batch`

驳回一批 AI 养号剧本。

*Reject a batch of AI warm-up scripts.*

触发词：驳回养号剧本,拒绝剧本,reject warmup

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id |
| `batch_id` | string | 是 | list_warmup_scripts 里的批次 id |

### `approve_evolution_proposal`

批准一条自对抗进化提案，让它生效。

*Approve a pending self-adversarial evolution proposal.*

触发词：批准进化提案,通过提案,approve proposal

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `proposal_id` | string | 是 | get_evolution 里待批准的提案 id |

### `dismiss_evolution_proposal`

驳回一条自对抗进化提案。

*Dismiss a pending evolution proposal.*

触发词：驳回进化提案,忽略提案,dismiss proposal

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `proposal_id` | string | 是 | get_evolution 里待批准的提案 id |

## 浏览器、页面与删除工具（28）

需要 `automation` 档（令牌范围 `cdp`，默认档）；含 Cookie 读写、执行 JS、删除画像

### `get_cdp_endpoint`

拿一个正在运行（debug 模式）的画像的 CDP 连接信息：HTTP/WebSocket 端点、当前标签页、Playwright / playwright-mcp / chrome-devtools-mcp 的接入写法。没在跑回 not_running，是 manual 模式启动的回 cdp_unavailable。

*CDP connection info for a running debug profile (HTTP/WS endpoints, tabs, client snippets). Automation mode.*

触发词：CDP 地址,调试端口,playwright 连接,cdp endpoint

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `open_browser`

一步到位：确保画像的浏览器以 debug 模式在跑，并回 CDP 连接信息（同 get_cdp_endpoint）。画像参数可以是 id 或名称。已经以 debug 模式在跑就直接回信息（started=false），不会重启；是 manual 模式在跑回 already_running，需要先 stop_profile。撞授权单座位回 seat_busy。

*Ensure a profile runs in debug mode and return CDP info. Idempotent; never restarts a manual session. Automation mode.*

触发词：打开并接管,调试模式打开,open for automation

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或画像名称（名称需完全一致且唯一） |

### `browser_navigate`

让画像当前标签页打开一个网址（只允许 http/https）。返回最终 url、标题、HTTP 状态。之后用 browser_snapshot 看页面。

*Open an http(s) URL in the profile's current tab.*

触发词：打开网址,访问网页,go to url,navigate

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `url` | string | 是 | 要打开的 http(s) 网址 |

### `browser_snapshot`

读当前页面：返回文字轮廓，可交互元素带 ref（如 [e3] button "登录"）。点击/输入都要用最近一次快照里的 ref。页面变化后要重新快照。长页面会被截断（truncated=true）：往下 browser_scroll 后用 viewport_only=true 只看当前屏；要读正文用 browser_get_text。

*Read the page: text outline with refs (e.g. [e3]) for interactive elements. Re-snapshot after the page changes. Long pages truncate: scroll, then viewport_only=true.*

触发词：看页面,页面快照,读取页面结构,snapshot,read page

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `viewport_only` | boolean |  | 只列出当前视口内的内容（滚动后翻页用）（默认 False） |

### `browser_get_text`

读当前页面（或某个 ref 元素）的纯文字，分页返回：用返回的 next_offset 作为下次的 offset 接着读。读文章、结果列表正文用它，比快照省。默认只读页面的主体内容（跳过菜单和页脚），要整页文字设 whole_page=true。

*Read the page's (or an element's) plain text in pages; pass next_offset back as offset to continue.*

触发词：读文字,页面文字,get text

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `ref` | string |  | 可选：只读这个元素（快照 ref 或语义选择器） |
| `offset` | integer |  | 从第几个字符开始（默认 0） |
| `max_chars` | integer |  | 本次最多返回多少字符，100~20000（默认 6000） |
| `whole_page` | boolean |  | 读整页文字（含菜单页脚），默认只读主体内容（默认 False） |

### `browser_click`

点击一个元素：最近一次 browser_snapshot 里的 ref（如 e3），或语义选择器（text=登录、role=button[name="登录"] 等，页面跳转后依然有效）。点击若打开新标签页会自动切过去。

*Click an element by its ref from the latest snapshot.*

触发词：点击,点按钮,click

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `ref` | string | 是 | 快照里的元素引用（如 e3），或语义选择器：text=登录 / role=button[name="登录"] / label=邮箱 / placeholder=… / css=…（必须恰好匹配一个可见元素） |

### `browser_type`

往输入框（或下拉框，按选项文字选）填内容。默认替换原有内容；submit=true 填完按回车。

*Fill an input (or pick a select option by text); submit=true presses Enter.*

触发词：输入,填表单,type,fill input

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `ref` | string | 是 | 快照里的元素引用（如 e3），或语义选择器：text=登录 / role=button[name="登录"] / label=邮箱 / placeholder=… / css=…（必须恰好匹配一个可见元素） |
| `text` | string | 是 | 要填的文字 |
| `submit` | boolean |  | 填完是否按回车提交（默认 False） |

### `browser_press_key`

按一个键或组合键，如 Enter、Tab、Escape、ArrowDown、Control+A。作用在当前焦点上。

*Press a key or combo (Enter, Tab, Control+A) on the focused element.*

触发词：按键,回车,press key

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `key` | string | 是 | 键名，如 Enter / Control+A |

### `browser_scroll`

滚动当前页面。direction 为 up/down/left/right，amount 是像素（默认 600）。

*Scroll the page up/down/left/right by pixels.*

触发词：滚动,scroll

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `direction` | up / down / left / right |  | （默认 down） |
| `amount` | integer |  | 滚动像素，1~5000（默认 600） |

### `browser_screenshot`

给当前页面截图（默认 jpeg，视口范围；full_page=true 截整页）。图片随结果返回。

*Screenshot the current page (jpeg default; full_page for the whole page).*

触发词：截图,screenshot

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `full_page` | boolean |  | （默认 False） |
| `format` | jpeg / png |  | （默认 jpeg） |

### `browser_wait_for`

等条件成立再往下走（给了几个就全部要满足）：text 出现、text_gone 消失、url 包含某段、selector（语义选择器）出现，或单纯等 ms 毫秒。每个条件最多等 timeout_ms（默认 15000，最大 30000）。比固定等待可靠。

*Wait until text appears / disappears, the URL contains a string, or a selector is visible (or just wait ms). Each condition is bounded by timeout_ms.*

触发词：等待,等出现,wait for

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `text` | string |  | 等它出现的文字 |
| `text_gone` | string |  | 等它消失的文字（如加载提示） |
| `url` | string |  | 等当前网址包含这段文字 |
| `selector` | string |  | 等它可见：text=… / role=button[name="…"] / css=… |
| `ms` | integer |  | 单纯等待的毫秒数 |
| `timeout_ms` | integer |  | 每个条件的最长等待，100~30000（默认 15000） |

### `browser_dialog`

处理页面弹出的 JS 对话框（alert / confirm / prompt / beforeunload）。动作返回里出现 dialog 字段就必须先处理它，否则页面被冻住、其他操作都会回 dialog_open。accept=确定，dismiss=取消；prompt 可用 text 填内容。2 分钟没人处理会自动取消。

*Accept or dismiss a JS dialog (alert/confirm/prompt/beforeunload) that froze the page. Required when an action result carries `dialog`.*

触发词：弹窗,确认框,dialog,alert

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `action` | accept / dismiss | 是 |  |
| `text` | string |  | prompt 对话框要填的内容（仅 accept 时有效） |

### `browser_batch`

一次调用按顺序做最多 20 步，省掉来回往返。steps 是数组，每步 {"do": 动词, ...该动词自己的参数}，动词：navigate(url) click(ref) type(ref,text,submit?) press_key(key) scroll(direction?,amount?) wait_for(text/text_gone/url/selector/ms) back get_text(ref?,offset?,max_chars?) dialog(answer=accept|dismiss,text?) tabs(tab_action,index?,url?) upload(ref,paths)。页面跳转后 ref 会失效，所以跨页面的步骤请用语义选择器（text=… / role=…[name=…]）。某步出错或弹出对话框就停（stopped/stopped_at 会说明），最后默认附一次快照（snapshot_after=false 关闭）。

*Run up to 20 page steps in one call ({do: click|type|navigate|...}); stops on an error or a dialog and appends a snapshot. Use semantic selectors across page changes.*

触发词：批量步骤,一次做多步,batch steps

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `steps` | array<object> | 是 | 按顺序执行的步骤 |
| `snapshot_after` | boolean |  | 做完后附一次快照（默认 True） |
| `viewport_only` | boolean |  | 附带的快照只看当前屏（默认 False） |
| `stop_on_error` | boolean |  | 某步失败就停（false 则继续后面的步骤）（默认 True） |

### `browser_upload`

往文件输入框上传文件（ref 是 input[type=file]，或点它会弹出文件选择器的按钮）。为防止把本机文件传给网站，只允许上传「agent 文件目录」里的文件，路径要写完整；目录位置见 browser_downloads 的 files_dir。

*Upload files to a file input or the chooser a button opens. Only files inside the agent files folder are allowed (see browser_downloads.files_dir).*

触发词：上传文件,upload file

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `ref` | string | 是 | 文件输入框或上传按钮：快照 ref 或语义选择器 |
| `paths` | array<string> | 是 | 要上传的文件的完整路径（必须在 agent 文件目录里，单个不超过 50 MB） |

### `browser_downloads`

列出这个画像下载过的文件（自动保存到 agent 文件目录，返回完整路径、大小、状态），并告诉你目录在哪。点了下载按钮之后调它。

*List files this profile downloaded (auto-saved into the agent files folder) and where that folder is.*

触发词：下载的文件,downloads

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |

### `browser_back`

当前标签页后退一步。

*Go back one step in the current tab.*

触发词：后退,返回上一页,go back

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |

### `browser_tabs`

管理标签页：list 列出；new 新开（可带 url）；select 切换到 index；close 关闭 index。

*List, open, select or close tabs.*

触发词：标签页,新开标签,tabs

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `action` | list / new / select / close |  | （默认 list） |
| `index` | integer |  | select/close 的标签页序号（从 0 开始） |
| `url` | string |  | new 时可选的网址 |

### `account_prepare`

注册新账号前一步到位：给这个画像新建一个邮箱地址（走「邮箱」页接好的邮箱服务器）+ 一个保险库条目（用户名、自动生成的强密码）。返回 email、username 和三个引用 refs（{{vault:…password}} 等）：往注册表单里填的时候，把引用原样写进 browser_type 的 text，Manager 会在服务端换成真值，密码不会经过你。提交后用 mail_wait_code(address=email) 取验证码或验证链接。

*Before a sign-up: get a mailbox address and a vault entry (generated password). Returns the email, username and {{vault:…}} references to type; the password never reaches you.*

触发词：注册准备,生成密码,准备账号,prepare sign-up

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `site` | string | 是 | 要注册的网站域名，如 example.com |
| `username` | string |  | 可选：指定用户名；不填则随机生成 |
| `password_length` | integer |  | 密码长度，12~64（默认 20） |
| `symbols` | boolean |  | 密码里是否含符号（个别网站不允许时设 false）（默认 True） |
| `domain` | string |  | 可选：邮箱域名，不填随机选一个 |

### `vault_create`

为一个网站新建保险库条目：Manager 生成强密码并加密保存，你只拿到引用（{{vault:…}}），拿不到明文。已有邮箱地址要用时通过 email 传入；要一步拿邮箱加条目就用 account_prepare。

*Create a vault entry for a site: the Manager generates and encrypts the password; you only get {{vault:…}} references.*

触发词：保险库新建,保存账号密码,vault create

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `site` | string | 是 | 网站域名 |
| `username` | string |  | 可选：用户名 |
| `email` | string |  | 可选：账号用的邮箱 |
| `password_length` | integer |  | （默认 20） |
| `symbols` | boolean |  | （默认 True） |

### `vault_list`

列出这个画像的保险库条目（网站、用户名、邮箱、状态、引用），不含密码。登录已注册的网站时用它找引用。

*List this profile's vault entries (site, username, email, status, references), never passwords.*

触发词：保险库列表,vault list

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |

### `vault_mark`

更新条目的状态：registered（已提交注册）/ verified（邮箱已验证、账号可用）/ failed；可附备注。

*Set an entry's status (registered / verified / failed) and notes.*

触发词：标记账号状态,vault mark

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `entry_id` | string | 是 | 条目 id |
| `status` | new / registered / verified / failed |  |  |
| `notes` | string |  | 可选备注（不要写密码） |

### `delete_profile`

删除画像：先停掉浏览器，再放进回收站（7 天内可用 restore_profile 恢复）。要彻底删掉用 purge_profile。

*Stop the profile and move it to the recycle bin (restorable for 7 days).*

触发词：删除环境,删掉画像,放进回收站,delete profile,remove profile,trash

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `purge_profile`

彻底删除画像：数据库记录和整个用户数据目录（登录态、Cookie）一并清除，不可恢复。普通删除用 delete_profile。

*Permanently delete a profile and its whole data directory. Not recoverable.*

触发词：彻底删除,永久删除,清除数据,purge profile,delete forever,wipe

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | string | 是 | 画像 id（先用 list_profiles 查） |

### `browser_hover`

把鼠标移到元素上（弹出菜单、悬浮提示）。ref 同 browser_click。

*Move the mouse over an element (menus, tooltips).*

触发词：悬停,鼠标移上去,hover

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `ref` | string | 是 | 快照 ref（如 e3）或语义选择器 |

### `browser_drag`

按住 ref 元素拖到 to_ref 元素上松开（滑块、排序、拖放上传区）。

*Drag one element onto another (sliders, sorting, drop zones).*

触发词：拖拽,拖动,滑块,drag and drop,drag

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `ref` | string | 是 | 起点：快照 ref 或语义选择器 |
| `to_ref` | string | 是 | 终点：快照 ref 或语义选择器 |

### `browser_get_html`

读页面（或某个元素）的原始 HTML，分页返回（offset/max_chars，看 next_offset）。找不到元素、要看隐藏属性时用；平时读 browser_snapshot 更省。

*Raw HTML of the page or one element, paged. Prefer browser_snapshot for reading.*

触发词：读 HTML,页面源码,看源码,get html,page source

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `ref` | string |  | 可选：只读这个元素的 outerHTML |
| `offset` | integer |  | （默认 0） |
| `max_chars` | integer |  | 100~20000（默认 6000） |

### `browser_evaluate`

在页面里执行 JavaScript 并返回结果（可 JSON 化的值，超过 2 万字符会截断）。script 写表达式或箭头函数，如 () => document.title；给了 ref 时函数的参数就是那个元素，如 el => el.value。

*Run JavaScript in the page and return its JSON result; with ref the function receives that element.*

触发词：执行脚本,执行 JS,运行 JavaScript,evaluate,run script

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `script` | string | 是 | JS 表达式或箭头函数 |
| `ref` | string |  | 可选：函数的第一个参数是这个元素 |

### `browser_cookies`

读、写或清空这个画像的 Cookie（整个浏览器，不是单个标签页）。action=get 可用 domain 过滤或 urls 限定；set 传 cookies 数组（每项 name、value，加 url 或 domain+path）；clear 清空全部。

*Read, write or clear the profile's cookies (get / set / clear).*

触发词：读 Cookie,导出 Cookie,导入 Cookie,清 Cookie,cookies,export cookies,import cookies

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile` | string | 是 | 画像 id 或名称（需已用 open_browser 以 debug 模式打开） |
| `action` | get / set / clear |  | （默认 get） |
| `domain` | string |  | get：只返回域名包含它的 Cookie |
| `urls` | array<string> |  | get：只返回对这些网址生效的 Cookie |
| `cookies` | array<object> |  | set：要写入的 Cookie |
