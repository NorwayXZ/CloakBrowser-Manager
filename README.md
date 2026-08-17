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

如果你要备份或迁移，关闭所有浏览器后，直接复制整个 `CloakBrowser Manager` 文件夹。

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

Git 安装版可以先在面板右上角点击 `升级`。如果提示升级完成，关闭当前运行 Manager 的终端窗口，再重新启动 Manager。

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

## 开发者说明

普通用户不需要看这一节。

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

## 许可证

- 本应用 GUI 源码：MIT，见 [LICENSE](LICENSE)
- CloakBrowser 二进制：免费使用，不能重新分发，见 [BINARY-LICENSE.md](BINARY-LICENSE.md)
