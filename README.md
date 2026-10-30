# CloakBrowser Manager 本地版

这是一个在自己电脑上运行的浏览器环境管理器，支持 Windows 和 macOS。它不是服务器部署版，普通用户只需要在本机安装依赖，然后打开 `http://127.0.0.1:8080` 使用。

> 如果你完全不懂代码，也可以照着下面一步一步做。不要跳步骤。

## 先搞清楚要安装什么

你需要先安装这些东西：

1. **Google Chrome**
   - Windows / macOS 稳定原生模式会调用你电脑里的 Chrome。
   - 下载地址：[https://www.google.com/chrome/](https://www.google.com/chrome/)

2. **Python 3.10 或更高版本**
   - 后端服务用 Python 运行。
   - 下载地址：[https://www.python.org/downloads/](https://www.python.org/downloads/)

3. **Node.js 18 或更高版本**
   - 前端界面需要 Node.js 构建。
   - 下载 LTS 版本即可。
   - 下载地址：[https://nodejs.org/](https://nodejs.org/)

4. **Git**
   - 用来从 GitHub 下载项目。
   - 不会 Git 的用户也可以直接下载 ZIP。
   - 下载地址：[https://git-scm.com/downloads](https://git-scm.com/downloads)

## macOS 安装教程

### 第 1 步：安装 Chrome

先安装 Google Chrome，并且至少打开过一次 Chrome。

### 第 2 步：安装 Python、Node.js、Git

如果你会用 Homebrew，可以在终端执行：

```bash
brew install python node git
```

如果你不会 Homebrew，就分别去官网下载并安装：

- Python：[https://www.python.org/downloads/](https://www.python.org/downloads/)
- Node.js：[https://nodejs.org/](https://nodejs.org/)
- Git：[https://git-scm.com/downloads](https://git-scm.com/downloads)

安装完后，在终端检查：

```bash
python3 --version
node --version
npm --version
git --version
```

只要每个命令都能显示版本号，就说明依赖装好了。

### 第 3 步：下载项目

会用 Git 的用户执行：

```bash
cd ~/Documents
git clone https://github.com/NorwayXZ/CloakBrowser-Manager.git
cd CloakBrowser-Manager
```

不会 Git 的用户：

1. 打开 GitHub 项目页面。
2. 点击绿色 `Code` 按钮。
3. 点击 `Download ZIP`。
4. 解压 ZIP。
5. 打开终端，进入解压后的文件夹，例如：

```bash
cd ~/Downloads/CloakBrowser-Manager-main
```

### 第 4 步：第一次安装并启动

在项目文件夹里执行：

```bash
chmod +x install-macos.sh run-macos.sh uninstall-macos.sh bin/cloak
./install-macos.sh
```

第一次运行会自动做这些事：

1. 创建 Python 虚拟环境 `.venv`
2. 安装后端依赖
3. 安装前端依赖
4. 构建网页界面
5. 启动 Manager
6. 自动打开浏览器

打开地址是：

```text
http://127.0.0.1:8080
```

### 第 5 步：以后怎么启动

每次要用时，进入项目文件夹执行：

```bash
./run-macos.sh
```

然后打开：

```text
http://127.0.0.1:8080
```

### 第 6 步：怎么关闭

运行窗口不要直接乱关。推荐在终端按：

```text
Control + C
```

如果你使用 `bin/cloak`：

```bash
./bin/cloak start
./bin/cloak stop
./bin/cloak status
./bin/cloak restart
```

### 可选：安装包版，双击就能用

不想每次开终端的话，可以直接用安装包版。安装包版自带 Python 运行环境，不需要再装 Python、Node.js。

**下载**：打开 GitHub 的 [Releases 页面](https://github.com/NorwayXZ/CloakBrowser-Manager/releases/latest)，按电脑选择：

- Apple 芯片 Mac（M1/M2/M3/M4…）：`CloakBrowser-Manager-<版本>-<提交>-arm64.dmg`
- Intel 芯片 Mac：`CloakBrowser-Manager-<版本>-<提交>-x86_64.dmg`
- Windows：`CloakBrowser-Manager-<版本>-windows-x64-setup.exe`

也可以自己打包 macOS 版：`./packaging/macos/build-dmg.sh`，结果在 `build/macos/`。

**macOS 使用**：双击 DMG，把 `CloakBrowser Manager` 拖到「应用程序」。安装包没有 Apple 开发者签名，从网上下载的第一次打开时要在 App 上右键选「打开」。

- 双击 App，面板显示在 App 自己的窗口里（不再借用 Chrome）。Dock 上只有一个 CloakBrowser Manager。
- 关掉面板窗口只是隐藏，点 Dock 图标或菜单「打开管理面板」会把同一个窗口调回来，不会多开。
- 按 `Command + Q` 或在 Dock 上右键「退出」，会先关闭所有正在运行的浏览器，再退出 Manager，窗口一起关闭。
- 每个指纹浏览器的窗口以画像名称命名（Dock 图标右键、「窗口」菜单、调度中心里能看到）。关掉它的最后一个窗口，这个浏览器就会正常退出，下次打开时自动恢复之前的标签。
- 菜单栏里有「检查更新…」「登录时自动启动（不弹出面板）」「打开画像数据目录」「打开日志目录」，以及「编辑」「显示 → 重新载入面板」「窗口」菜单。日志在 `~/Library/Logs/CloakBrowser Manager/manager.log`。
- 启动后会自动检查一次新版本，有新版本时可以「立即更新」：自动备份、下载校验、替换并重启。

**Windows 使用**：运行 `setup.exe` 安装（不需要管理员权限）。之后从开始菜单或桌面打开 `CloakBrowser Manager`，右下角托盘会出现图标，右键可以打开面板、检查更新、设置开机自启、退出（退出会先关闭所有浏览器）。日志在 `%LOCALAPPDATA%\CloakBrowser Manager\Logs\manager.log`。

说明：

- 安装包版和终端版共用同一个数据目录，画像、Cookie、登录状态都还在，不需要迁移；卸载安装包版也不会删除数据。
- 如果终端版已经在运行，打开安装包版只会打开已有面板，不会重复启动。

**发布新版本（维护者）**：推送一个 `v` 开头的标签，GitHub Actions 会自动打出三个安装包并发布到 Releases：

```bash
git tag v0.2.0
git push origin v0.2.0
```

## Windows 安装教程

### 第 1 步：安装 Chrome

先安装 Google Chrome：

[https://www.google.com/chrome/](https://www.google.com/chrome/)

### 第 2 步：安装 Python

下载 Python：

[https://www.python.org/downloads/](https://www.python.org/downloads/)

安装时一定要勾选：

```text
Add Python to PATH
```

安装完打开 `命令提示符` 或 `PowerShell`，检查：

```text
py -3 --version
python --version
```

有一个能显示版本号即可。

### 第 3 步：安装 Node.js

下载 Node.js LTS：

[https://nodejs.org/](https://nodejs.org/)

安装完检查：

```text
node --version
npm --version
```

### 第 4 步：下载项目

会用 Git 的用户：

```text
git clone https://github.com/NorwayXZ/CloakBrowser-Manager.git
cd CloakBrowser-Manager
```

不会 Git 的用户：

1. 打开 GitHub 项目页面。
2. 点击绿色 `Code`。
3. 点击 `Download ZIP`。
4. 解压 ZIP。
5. 进入解压后的文件夹。

### 第 5 步：第一次安装并启动

双击：

```text
install-windows.bat
```

如果 Windows 弹出安全提示，确认你下载的是本项目后，选择继续运行。

第一次运行会自动：

1. 创建 Python 虚拟环境
2. 安装后端依赖
3. 安装前端依赖
4. 构建网页界面
5. 启动 Manager
6. 打开本地网页

打开地址：

```text
http://127.0.0.1:8080
```

### 第 6 步：以后怎么启动

双击：

```text
run-windows.bat
```

然后访问：

```text
http://127.0.0.1:8080
```

### 第 7 步：怎么关闭

关闭运行中的命令窗口，或在窗口里按：

```text
Ctrl + C
```

## 第一次打开网页后怎么用

1. 打开 `http://127.0.0.1:8080`
2. 点击左侧 `新建浏览器`
3. 填写浏览器名称
4. 选择分组，可不选
5. 选择代理，支持 HTTP / HTTPS / SOCKS5 / VLESS / VMess / Trojan / Shadowsocks
6. 点击 `测试代理`，确认出口 IP、国家、时区、语言
7. 选择浏览器模式：
   - `系统 Chrome 原生模式`：更稳，优先使用本机真实 Chrome
   - `CloakBrowser 画像模式`：可以使用设备画像、GPU、CPU 等参数
   - macOS 电脑只显示 macOS 画像；Windows 电脑只显示 Windows 画像，不跨系统混用
8. 点击保存
9. 回到首页，点击 `打开`

点击 `打开` 前，Manager 会先做启动前检查：

- macOS 只允许启动 macOS 画像，Windows 只允许启动 Windows 画像。
- 检查自定义 UA、平台、GPU、逻辑分辨率是否明显冲突。
- 提醒系统 Chrome 不会应用 CloakBrowser 的 GPU、CPU、内存、Canvas 等底层画像参数。
- 提醒无 CDP 日常模式通过当前画像专用的本地扩展导入 Cookie JSON，并继续复用同一用户数据目录。

启动后的本地信息页会检查主页面、iframe 和 Worker 的语言、时区、UA、平台、CPU 和内存，还会检查 WebGL、Canvas/Audio 稳定性、字体基线、Cookie 和常见网页存储。报告只显示有证据的通过、警告或失败，不承诺任何网站都无法识别自动化。

### SOCKS5 服务器中转（v0.9.1）

在「代理 → 中转服务器」添加 VLESS TLS/REALITY、Trojan、VMess TLS 或 Shadowsocks 加密入口；编辑环境的 SOCKS5 时，可选择「直接连接 SOCKS5」或「通过中转服务器」。多个环境可共用中转，各自保留最终 SOCKS5。旧环境默认直接连接。

支持完整链路检查及直连/中转对比；中转失败时停止，不自动更换路径。本版中转使用 TCP 并关闭 QUIC。修改中转后需重新打开相关环境。配置备份会带上中转设置；数据库布局升至 2，降级需使用升级前完整备份。

详见 [SOCKS5 中转配置与验证范围](docs/PROXY_RELAY.md)。

网络报告中的含义：

- `proxy_host_resolver`：浏览器已启用通过代理解析域名的启动策略。
- `disable_non_proxied_udp`：浏览器已禁止非代理 UDP 的 WebRTC 路径。
- `browser_native`：TLS 由实际浏览器内核发起，不是 Python 请求代测。
- 外部网络探针会显示浏览器真实出口 IP、HTTP 协议、TLS 版本和加密套件；探针失败时会明确显示“未完成外部检查”。
- DNS 只能确认浏览器启用了代理解析策略，当前 HTTP 探针不能证明操作系统实际使用了哪台 DNS 解析器，因此报告会保持“未经外部 DNS 解析器验证”。

## 让 AI agent 使用

Codex、Claude、DeepSeek harness 等 AI agent 可以通过 MCP（stdio 或 HTTP）、REST 工具接口或 `bin/cloak` 命令行使用指纹浏览器，包括打开画像、读取和点击页面、截图。页面控制默认关闭，在 `mcp.mode=automation` 下才开放；用户可以在面板里随时「接管」。接入方式、权限档位和规则见 [docs/AGENT.md](docs/AGENT.md)，MCP 接入细节见 [docs/MCP.md](docs/MCP.md)。

## 配置备份和扩展

- 左侧 `数据备份` → `立即完整备份`：关闭所有浏览器后点一下，生成一个 `.zip`，包含所有浏览器的 Cookie、登录状态、历史记录、本地存储、标签页，以及画像列表、分组、代理和加密密钥（网页缓存不备份）。文件保存在数据目录的 `backups/full/`，同时会下载一份，建议再复制到移动硬盘或网盘。
- 恢复：在同一页选择备份 `.zip`，或在 `备份记录` 里点 `恢复`。恢复前，当前数据会先移到 `backups/before-restore-<时间>/`，不会被删除；确认恢复无误后可以手动删掉这个目录释放空间。
- 每次启动 Manager 会自动保存一份画像数据库快照到 `backups/auto/`（保留最近 10 份），误删或误改画像时可以回滚。快照不含 Cookie 等浏览器数据。
- 换电脑恢复时，使用 CloakBrowser 内核的画像登录状态可以直接带过去；使用系统 Chrome 内核的画像，Cookie 由 macOS 钥匙串加密，换电脑后可能需要重新登录。
- `只导出配置（JSON）` 只包含浏览器配置、分组、代理和 Cookie JSON，不含登录状态，适合迁移设置。备份文件都包含敏感信息，不要公开上传。
- 编辑浏览器时可以在 `高级设置 -> 扩展目录` 中每行填写一个已解压扩展目录，Manager 会自动生成 Chrome 启动参数。
- 浏览器意外退出时，环境列表会保留异常退出代码，便于区分正常关闭和内核崩溃。
- macOS CloakBrowser 若因旧 Chromium 的 `Sync Data` 元数据触发 `SIGTRAP/-5`，下次启动会把该目录备份到画像内的 `.manager-recovery/` 后自动重建；Cookie、历史、密码、LocalStorage 和标签会话不会被删除。

## 浏览器数据保存在哪里

项目代码放在哪里都可以，但浏览器数据不会保存在项目文件夹里。

macOS 数据目录：

```text
~/Library/Application Support/CloakBrowser Manager
```

Windows 数据目录：

```text
%LOCALAPPDATA%\CloakBrowser Manager
```

重要文件：

- `profiles.db`：浏览器配置数据库
- `profiles/<profile-id>/`：每个浏览器自己的用户数据目录
- 浏览器 Cookie、登录状态、历史记录、扩展数据都在 `profiles/<profile-id>/` 里

如果你要备份或迁移，推荐用面板里的 `数据备份` → `立即完整备份`；也可以关闭所有浏览器后，直接复制整个 `CloakBrowser Manager` 文件夹。

## CloakBrowser 二进制保存在哪里

CloakBrowser 浏览器内核会缓存到：

macOS：

```text
~/.cloakbrowser
```

Windows：

```text
%USERPROFILE%\.cloakbrowser
```

注意：这不是你的浏览器数据目录。真正的 Cookie 和登录状态在上面的 `CloakBrowser Manager/profiles/` 里。

## 升级教程

Git 安装版可以先在面板右上角点击 `升级`。按钮会依次检查 Manager 的 Git 代码和当前平台官方可用的 CloakBrowser 内核。内核检查使用实际生效版本标记，并在下载后核对缓存目录版本和文件大小；页面还会显示“已验证”状态。不同系统、免费/付费渠道可用版本可能不同；页面只显示官方检查实际返回的版本，不会硬写一个并不存在的版本号。如果提示升级完成，关闭当前运行 Manager 的终端窗口，再重新启动 Manager。

如果你是 Git 下载的：

```bash
cd CloakBrowser-Manager
git pull
./install-macos.sh
```

Windows：

```text
进入 CloakBrowser-Manager 文件夹
git pull
双击 install-windows.bat
```

如果你是 ZIP 下载的：

1. 下载新的 ZIP。
2. 解压到新的文件夹。
3. 运行安装脚本。
4. 原来的浏览器数据仍然在系统数据目录里，不会因为换项目文件夹丢失。

## 卸载教程

macOS：

```bash
./uninstall-macos.sh
```

Windows：

```text
双击 uninstall-windows.bat
```

默认卸载只删除项目里的运行环境，不删除浏览器数据。

如果你想彻底删除所有浏览器数据：

macOS：

```bash
python3 run.py --uninstall --purge-data
```

Windows：

```text
py -3 run.py --uninstall --purge-data
```

彻底删除前请先备份。

## 常见问题

### 打开提示 8080 被占用

说明 Manager 已经在运行，或者别的程序占用了 8080。

先打开：

```text
http://127.0.0.1:8080
```

如果能打开，就不用重复启动。

macOS 可以检查：

```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

Windows 可以检查：

```text
netstat -ano | findstr :8080
```

### 提示找不到 Python

重新安装 Python，并确认 Windows 安装时勾选 `Add Python to PATH`。

### 提示找不到 npm 或 Node.js

重新安装 Node.js LTS，然后重新打开终端。

### 第一次安装很慢

第一次会下载 Python 和 Node 依赖，网络慢时需要等几分钟。以后启动不会重复安装已经装好的依赖。

### 页面打不开

确认终端里没有报错，然后手动打开：

```text
http://127.0.0.1:8080
```

注意这是本机地址，不是公网网站。

### 用局域网地址或自定义域名打开提示 403

为了防止恶意网页偷偷操作 Manager，本地版只接受 `127.0.0.1`、`localhost` 访问，并会拒绝其他网站发起的修改请求。确实需要用别的地址访问时，启动前设置允许的主机名（多个用逗号分隔），同时建议在面板里设置登录密码：

```bash
CLOAKBROWSER_MANAGER_ALLOWED_HOSTS=mac-mini.local ./run-macos.sh
```

## 开发者说明

普通用户不需要看这一节。

完整的逐项实现、证据和限制见 [1-9 项工程验收矩阵](docs/verification-matrix.zh-CN.md)。

后端：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8080
```

前端：

```bash
cd frontend
npm install
npm run dev
```

GitHub Actions 会在 Ubuntu、macOS 和 Windows 上运行后端测试，并在 macOS/Windows 托管运行器上真实下载并验证 Xray 可执行文件、`geoip.dat`、`geosite.dat`，再启动 CloakBrowser 无界面运行端点，核对运行端点返回的 Chromium 版本与有效版本一致。托管 CI 不能替代真实 Windows 显卡和桌面窗口测试，因此 GPU/GUI 兼容性仍需在实体 Windows 电脑上验收。

## 许可证

- 本应用 GUI 源码：MIT，见 [LICENSE](LICENSE)
- CloakBrowser 二进制：免费使用，不能重新分发，见 [BINARY-LICENSE.md](BINARY-LICENSE.md)
