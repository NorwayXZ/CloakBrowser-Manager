# 1-9 项工程验收矩阵

这份清单记录可以重复执行的证据。它验证配置一致性、兼容性和管理功能，不保证任何第三方网站一定无法识别自动化或异常环境。

## 1. Windows / macOS 跨平台验证

- macOS 只能选择 macOS 画像，Windows 只能选择 Windows 画像；后端启动前检查会阻止跨系统画像。
- GitHub Actions 在 macOS 和 Windows 上运行 `scripts/native_runtime_smoke.py`。
- 冒烟测试会真实执行 Xray，确认 `geoip.dat`、`geosite.dat`，再通过 CloakBrowser 官方启动 API创建 renderer、加载测试页并核对运行版本。
- 托管运行器不能证明实体 Windows 显卡和可见桌面窗口兼容性，这部分仍属于实机验收。

## 2. 画像运行自检

- 默认起始页自动采集 main、iframe、Worker 的语言、时区、UA、平台、CPU、内存和存储状态。
- 同时检查 WebGL、Canvas/Audio 稳定性、字体基线、Cookie、WebRTC 和外部网络探针。
- 日常无外部 CDP 启动被动提交报告；调试模式可以由 Manager 主动采集。
- 报告只显示有检测依据的通过、警告和失败。

## 3. 设备画像一致性

- macOS 与 Windows 画像目录分开，只向用户展示当前系统画像。
- 画像关联平台、GPU、CPU、内存和逻辑分辨率；启动前检查 UA、内核主版本、GPU 和平台冲突。
- 自检会比较 main、iframe、Worker 以及 UA-CH；Canvas 和 Audio 在同一页面变化会直接失败。
- 系统 Chrome 明确使用真实硬件，不把 CloakBrowser 画像参数伪装成已生效。

## 4. DNS / TLS / WebRTC 外部诊断

- 有代理时启用代理主机解析策略，并禁止非代理 UDP WebRTC 路径。
- Cloudflare 外部探针报告浏览器出口 IP、HTTP 协议、TLS 版本、加密套件和请求头。
- HTTP 探针无法证明操作系统最终使用的具体 DNS 解析器，所以 DNS 只报告“策略已启用、未经外部解析器验证”。

## 5. 无 CDP Cookie 导入

- 日常模式为每个画像生成独立 MV3 本地扩展，通过 `chrome.cookies` 导入编辑页保存的 Cookie JSON。
- Cookie payload 使用内容哈希，已经导入的相同内容不会反复覆盖浏览器里的新会话。
- `hostOnly` Cookie 会按主机 Cookie 方式导入；之后继续由固定用户数据目录持久化。
- 调试模式仍使用浏览器上下文导入，日常模式不为 Cookie 导入开放外部 CDP。

## 6. Xray 数据文件补齐

- Xray 官方压缩包安装时必须同时取得可执行文件、`geoip.dat` 和 `geosite.dat`。
- 已有 Xray 但缺数据文件时会自动重新下载完整运行包。
- 启动 Xray 时设置资源目录和工作目录；macOS/Windows CI 都真实执行 `xray version`。

## 7. 内核升级与版本验证

- 面板升级读取 CloakBrowser 的有效版本标记，而不是只读取 wrapper 内置默认版本。
- 下载后核对缓存目录版本、二进制文件存在性和大小；状态栏显示 wrapper、平台、已安装版本和验证结果。
- macOS/Windows CI 启动实际浏览器，比较运行时 Chromium 前四段版本与有效版本。
- 免费版和付费版可能取得不同版本，Manager 不硬编码一个无法取得的“最新版本”。

## 8. 专业启动预检 UI

- 单个启动和批量启动都先展示同一预检弹窗。
- 错误会阻止继续；警告和能力限制要求用户明确确认。
- 弹窗展示启动模式、外部 CDP、画像参数、DNS 策略和 TLS 验证状态，并明确说明 System 时区不会被修改。

## 9. 本地产品管理能力

- 浏览器环境：创建、编辑、搜索、分组、批量启动/关闭、备注自动保存和退出原因。
- 代理：HTTP、HTTPS、SOCKS5（含账号密码）、VLESS、VMess、Trojan、Shadowsocks，支持命名保存和批量导入。
- 数据：7 天回收站、恢复/彻底删除、配置导入导出、固定画像目录和完整数据迁移说明。
- 运维：可选管理员登录、账号密码修改、Manager/浏览器升级、扩展目录和启动参数。
- 当前产品定位是本地单管理员工具，不包含云端多租户、团队 RBAC、订阅计费或远程浏览器托管；这些不应在本地版本中被宣称为已实现。

## 重复验收命令

```bash
.venv/bin/python -m pytest backend/tests -q
cd frontend && npm test -- --run && npm run build
```

macOS 原生运行环境还可以执行：

```bash
.venv/bin/python scripts/native_runtime_smoke.py
```

Windows PowerShell 使用：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe scripts/native_runtime_smoke.py
cd frontend
npm test -- --run
npm run build
```
