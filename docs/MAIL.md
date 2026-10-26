# 域名邮箱与保险库：让 AI 自己注册账号

注册网站账号需要三样 AI 变不出来的东西：**邮箱、密码、验证码**。这套功能把它们都接进来：

- **域名邮箱**：用你自己的域名，每个环境、每个网站一个随机地址（如 `kai.moore42@你的域名`）。AI 自己新建地址、自己等验证邮件，邮件里的**验证码和验证链接已经提取好**。
- **保险库**：密码由 Manager 生成并加密保存。**AI 看不到明文**，它只拿到引用 `{{vault:…password}}`，调用 `browser_type` 时 Manager 在服务端换成真值再填进页面。你在面板里随时能查看。
- **人在回路**：遇到图形验证码或手机短信验证，AI 停下来，请你在面板里「接管」处理，处理完再还给它。

你不用再给 AI 提供邮箱、密码或验证码。

```
网站发邮件 ──▶ Cloudflare Email Routing（catch-all）──▶ 邮件 Worker ──▶ D1（只收已登记的地址）
                                                              ▲
CloakBrowser Manager ──── HTTPS + 令牌 ──────────────────────┘
   ├─ 邮箱模块：分配地址、拉信、提取验证码/链接（加密保存）
   ├─ 保险库：生成密码、加密保存、{{vault:…}} 引用
   └─ AI 工具：account_prepare / mail_wait / vault_* …
```

## 一次性准备（约 15 分钟）

前提：域名已经托管在 Cloudflare（DNS 在 Cloudflare），本机有 Node.js 18+。

**1. 开启 Email Routing**
Cloudflare 控制台 → 选你的域名 → Email → Email Routing → 启用。它会自动添加收信所需的 MX 和 SPF 记录。
（这一步和下面第 3 步的界面文案以 Cloudflare 当前页面为准，我没能代你操作你的账号，步骤按其文档整理。）

**2. 部署邮件 Worker**

```bash
cd mail-worker
npm install
npx wrangler login                              # 浏览器里授权

# 编辑 wrangler.jsonc：把 vars.MAIL_DOMAIN 改成你的域名

npx wrangler d1 create cloakbrowser-mail        # 记下输出的 database_id
# 把它填进 wrangler.jsonc 的 d1_databases[0]："database_id": "<那串 id>"

npx wrangler d1 migrations apply cloakbrowser-mail --remote
openssl rand -hex 32                            # 生成一个令牌，复制下来
npx wrangler secret put API_TOKEN               # 粘贴刚才的令牌
npx wrangler deploy                             # 得到 https://cloakbrowser-mail.<你>.workers.dev
```

**3. 把整个域名的来信交给 Worker**
Email → Email Routing → Routing rules → **Catch-all address** → 动作选 **Send to a Worker** → 选 `cloakbrowser-mail` → 保存并启用。

**4. 在 Manager 里填配置**
设置 → **邮箱与保险库** → 域名、Worker 地址、令牌 → 保存 → **测试连接**（会用令牌真的请求一次 Worker）。

**5. 打开权限**
设置 → **AI 接入** → 权限选「可操作页面」（邮箱和保险库工具和页面控制同属这一档）。

### 本地试一遍（不需要 Cloudflare 账号）

```bash
cd mail-worker && npm install
node test/integration.mjs                     # 在本地 workerd 里测 Worker 的收信、拒收、令牌、游标

npx wrangler dev --local --port 8799 --persist-to /tmp/mail-state \
  --var API_TOKEN:dev-token --var MAIL_DOMAIN:mail.test       # 另开终端先 migrations apply --local
python scripts/mail_signup_demo_site.py --port 18767 --worker http://127.0.0.1:8799
```

演示网站 `http://127.0.0.1:18767/signup` 收到注册后，会像真实网站一样通过 Worker 给注册邮箱"发"一封带验证码和链接的邮件。在 Manager 里把域名填 `mail.test`、Worker 地址填 `http://127.0.0.1:8799`、令牌填 `dev-token`，就能让 AI 走完一整套注册。

## AI 怎么用

标准流程（`docs/AGENT.md` 和 MCP 的 `instructions` 里也有）：

1. `account_prepare(profile, site)`：新建邮箱地址 + 保险库条目。返回 `email`、`username` 和三个引用 `refs`。
2. `browser_navigate` 打开注册页；`browser_batch` 或 `browser_type` 把**引用原样**填进表单：
   ```json
   {"do": "type", "ref": "label=Email", "text": "{{vault:3f9c2a61d0b84e17.email}}"}
   {"do": "type", "ref": "css=#password", "text": "{{vault:3f9c2a61d0b84e17.password}}"}
   ```
3. 提交后 `mail_wait(profile, address, subject_contains?)`：返回发件人、标题、正文摘要、`codes`（验证码）、`links`（验证链接，`likely_verification` 标出最像的）。
4. 把验证码填回页面，或 `browser_navigate` 打开验证链接。
5. `vault_mark(entry_id, "verified")`。以后登录同一个网站，同样用引用填用户名和密码。

其他工具：`mail_new_address`（只要地址）、`mail_list`、`mail_read`（完整正文）、`vault_create`、`vault_list`。

| 失败原因 | 含义 |
| --- | --- |
| `mail_not_configured` | 还没在设置里配置域名邮箱 |
| `mail_timeout` | 等待时间内没收到符合条件的新邮件，可以再等一次 |
| `mail_provider_unreachable` / `mail_provider_error` | 连不上 Worker / 令牌不对或 Worker 报错，用「测试连接」排查 |
| `quota_exceeded` | 24 小时内新建的地址或条目超过上限（默认 30，设置里可调） |
| `vault_ref_invalid` | 引用的条目不存在，或不属于当前环境 |

## 它怎么保护你的密码和邮件

- **密码不经过 AI**：生成、存储、填写都在 Manager 里。工具返回里没有密码；引用只在拥有该条目的环境里有效，别的环境用它会被拒绝。
- **页面回显也会被抹掉**：如果网站有"显示密码"之类的开关，快照或页面文字里出现了已保存的密码，会在返回给 AI 之前被替换回引用。（截图里的像素无法处理。）
- **审计里不记输入的文字**：`browser_type` 的 `text` 在审计日志里只记长度。
- **加密保存**：密码、邮件正文、验证码、链接都用本机的加密密钥加密（和 Cookie、代理账号同一套），备份里也是加密的。
- **只收登记过的地址**：Worker 在 SMTP 阶段就拒收没登记的收件人，库里只有 AI 正在等的邮件。邮件默认保留 7 天后自动删除。
- **AI 只能读自己创建的地址**：每个地址属于一个环境，其他环境的 AI 读不到。
- **邮件是不可信内容**：正文可能夹带冲着 AI 来的"指示"。返回的邮件都带 `untrusted_content` 标记和提示，不含原始 HTML，只给文字摘要、验证码和链接。
- **有数量上限**：每天新建地址和条目各有上限，防止 AI 失控循环。

### 必须知道的一条

**没设管理员密码时，本机任何程序都能调用「查看密码」接口**，包括有命令行权限的 AI（它可以直接 `curl` 本机接口）。AI 的工具看不到密码，但绕开工具直接调接口就不受这层保护。如果你让有命令行权限的 AI 工作，请先在「账号与安全」里设置管理员密码；设置后，AI 的范围化令牌（`read` / `control` / `cdp`）不能访问保险库和邮箱设置，这些接口只有管理员能用。

## 做不到的和要留意的

- **图形验证码、手机短信、人机验证**：做不到。AI 会停下来，你在面板里「接管」处理，然后「归还给 AI」继续。
- **不发信**：只收信。需要从这个地址回复或发信的场景不在范围内。
- **有的网站不接受陌生域名**：个别网站会拦截它认为是一次性邮箱的域名，或要求企业邮箱/大厂邮箱。自己的域名一般没问题，但全新域名没有信誉，偶尔会被风控多看一眼。
- **输入速度**：环境开着"拟人化"（默认）时，`browser_type` 每个字符都带人类打字的延迟，一个 12 字符的邮箱要 3~4 秒，密码更久。这是指纹浏览器有意保留的行为（不容易被识别）。想让注册快，把这个环境的「拟人化」关掉，输入就是毫秒级；用 `browser_batch` 能把一整张表单合成一次调用。
- **邮件延迟**：从网站发出到 Manager 拿到通常几秒；`mail_wait` 每 2.5 秒向 Worker 拉一次。MCP 客户端的单次工具调用常有 60 秒超时，所以 `timeout_s` 默认 45，没等到就再调一次。
- **域名 DNS 必须在 Cloudflare**，因为收信靠 Cloudflare Email Routing。

## 排错

- **测试连接失败，提示令牌不对**：设置里填的令牌要和 `wrangler secret put API_TOKEN` 的一致；重新 `secret put` 之后记得在设置里也更新。
- **测试连接通过，但收不到邮件**：①Email Routing 的 catch-all 是否指向这个 Worker 并已启用；②该地址是不是 AI 通过工具新建的（只有登记过的地址才收，别的会被拒收）；③`npx wrangler tail` 看 Worker 日志；④发件方可能还没发出，或进了对方的重试队列。
- **提示 `mail_not_configured`**：设置里域名、Worker 地址、令牌三项缺一不可。
- **重建过 Worker 的数据库**：Manager 会发现序号回退并自动开启新一轮，不会丢新邮件，也不会重复。
- **想看 AI 都做了什么**：设置 → AI 接入 → 最近的 agent 操作。
