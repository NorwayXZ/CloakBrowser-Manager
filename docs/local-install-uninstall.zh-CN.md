# 本地安装、卸载与数据目录

这个版本只面向本地 Windows / macOS 使用，不需要服务器。

## 先看结论

- 程序代码保存在你从 GitHub 下载或克隆的项目文件夹里。
- 浏览器画像数据不保存在项目文件夹里，而是保存在系统用户目录。
- macOS 电脑只显示 macOS 画像；Windows 电脑只显示 Windows 画像，不跨系统混用。
- 默认卸载只删除运行环境，不删除画像、Cookie 和登录状态。
- 彻底删除数据前，请先备份整个 `CloakBrowser Manager` 文件夹。
- 这是本地 Windows / macOS 使用教程，不是服务器部署教程。

## 安装前必须准备什么

请先安装这些依赖，顺序不要乱：

1. **Google Chrome**
   - 下载地址：`https://www.google.com/chrome/`
   - Windows / macOS 的稳定原生模式会调用本机 Chrome。

2. **Python 3.10 或更高版本**
   - 下载地址：`https://www.python.org/downloads/`
   - Windows 安装时必须勾选 `Add Python to PATH`。

3. **Node.js 18 或更高版本**
   - 下载地址：`https://nodejs.org/`
   - 安装 LTS 版本即可。

4. **Git，可选**
   - 下载地址：`https://git-scm.com/downloads`
   - 不会 Git 的用户可以直接在 GitHub 点击 `Code` → `Download ZIP`。

检查依赖是否安装成功：

macOS：

```bash
python3 --version
node --version
npm --version
git --version
```

Windows：

```text
py -3 --version
node --version
npm --version
git --version
```

如果某个命令提示找不到，就先把对应软件装好，再继续下一步。

## 下载项目

会用 Git 的用户：

```bash
git clone https://github.com/NorwayXZ/CloakBrowser-Manager.git
cd CloakBrowser-Manager
```

不会 Git 的用户：

1. 打开 GitHub 项目页面。
2. 点击绿色 `Code`。
3. 点击 `Download ZIP`。
4. 解压 ZIP。
5. 进入解压后的项目文件夹。

## 一键安装

macOS：

```bash
chmod +x install-macos.sh run-macos.sh uninstall-macos.sh bin/cloak
./install-macos.sh
```

Windows：

```text
双击 install-windows.bat
```

如果 macOS 提示“没有权限运行”，在项目文件夹打开终端执行：

```bash
chmod +x install-macos.sh run-macos.sh uninstall-macos.sh bin/cloak
./install-macos.sh
```

安装脚本会自动：

1. 创建 Python 虚拟环境
2. 安装后端依赖
3. 安装前端依赖
4. 构建界面
5. 启动 Manager
6. 打开 `http://127.0.0.1:8080`

首次安装需要下载依赖，时间和网络速度有关。以后再次双击 `run-macos.sh`、`run-windows.bat` 即可启动，不会重复安装未变化的依赖。

## 日常启动和关闭

macOS 启动：

```bash
./run-macos.sh
```

Windows 启动：

```text
双击 run-windows.bat
```

打开地址：

```text
http://127.0.0.1:8080
```

关闭方式：

- macOS：在运行 Manager 的终端按 `Control + C`
- Windows：在运行 Manager 的窗口按 `Ctrl + C`，或关闭命令窗口

如果提示 8080 被占用，先打开 `http://127.0.0.1:8080` 看看是不是已经在运行。

### 日常模式、调试模式和指纹自检

- `伪装画像（CloakBrowser）` 的日常启动会直接运行 CloakBrowser 二进制，不开放外部 CDP 调试端口。代理识别出的语言和时区会通过浏览器底层参数应用到主页面、iframe 和 Worker。
- `稳定原生（系统 Chrome）` 的日常启动同样不开放外部 CDP，但系统 Chrome 没有完整的指纹参数接口。Manager 会传入语言和进程时区，实际是否完整生效以启动自检结果为准。
- `调试` 按钮只用于排查问题，会开启本机回环地址上的 CDP。日常使用不需要点它。
- 默认起始页会自动采集主页面、iframe、Worker 的语言和时区，并把结果保存为本次运行的指纹自检报告。面板显示“外部 CDP：未开启”才代表本次是日常无外部 CDP 启动。

新建浏览器默认使用 `伪装画像（CloakBrowser）`。如果目标是让语言、时区随代理变化并保持多层一致，请保留这个模式；系统 Chrome 更适合完全使用本机真实环境、不要求修改时区的场景。

## 一键卸载

macOS：

```bash
./uninstall-macos.sh
```

Windows：

```text
双击 uninstall-windows.bat
```

默认卸载只会清理程序运行环境，不会删除你的画像数据。

它会清理项目里的 `.venv`、`frontend/node_modules`、`frontend/dist` 等运行文件；不会删除下面介绍的画像目录。

## 如果要彻底删除数据

运行：

```bash
python3 run.py --uninstall --purge-data
```

Windows 可以在项目文件夹终端里执行：

```text
py -3 run.py --uninstall --purge-data
```

也可以在命令提示符或 PowerShell 中执行：

```text
uninstall-windows.bat --purge-data
```

## 画像数据保存在哪里

Manager 的数据目录如下：

- macOS: `~/Library/Application Support/CloakBrowser Manager`
- Windows: `%LOCALAPPDATA%\CloakBrowser Manager`

目录里最重要的东西有：

- `profiles.db`：配置数据库
- `profiles/<profile-id>/`：每个浏览器画像自己的 Chromium 用户数据目录
- `proxy-tests/`：代理测试产生的临时目录，可以删除

每个 `profiles/<profile-id>/` 里面通常包含：

- `Default/`：Cookie、网站登录状态、书签、扩展和偏好设置
- `Local State`：浏览器级别设置
- 缓存、GPU 缓存和其他 Chromium 状态文件

不要只备份截图或界面里的画像名称。要完整迁移画像，建议关闭所有浏览器窗口后备份整个：

```text
macOS:  ~/Library/Application Support/CloakBrowser Manager
Windows: %LOCALAPPDATA%\CloakBrowser Manager
```

你如果想手动备份，直接把整个 `CloakBrowser Manager` 文件夹复制走就行。

## CloakBrowser 二进制保存在哪里

这和画像数据是两个不同位置。CloakBrowser Python 包第一次启动时会把浏览器二进制缓存到：

- macOS: `~/.cloakbrowser`
- Windows: `%USERPROFILE%\.cloakbrowser`

如果你选择“稳定原生”模式，实际打开的是本机安装的 Google Chrome，Chrome 程序本体由系统安装位置管理；画像仍然使用 Manager 的 `profiles/<profile-id>/` 目录。

## 接回 CloakBrowser 继续使用

可以继续使用画像数据，但要区分两种情况：

1. **继续用本项目的 Manager**

   保留 `profiles.db` 和 `profiles/`，重新安装依赖后，Manager 会继续显示原来的画像名称和设置。

2. **改用独立的 CloakBrowser 程序**

   在 CloakBrowser 的启动选项中，把对应画像目录设置为 `user-data-dir`，例如：

   ```text
   macOS:
   ~/Library/Application Support/CloakBrowser Manager/profiles/<profile-id>

   Windows:
   %LOCALAPPDATA%\CloakBrowser Manager\profiles\<profile-id>
   ```

   独立 CloakBrowser 可以读取这个 Chromium 用户数据目录，但不会读取 Manager 的 `profiles.db`，所以画像名称、代理、时区等 Manager 配置不会自动出现在独立程序里。需要在独立程序中重新填写，或继续通过 Manager 启动。

   两个程序不能同时打开同一个 `<profile-id>`。切换前先完全关闭浏览器，否则可能出现锁文件、数据损坏或登录状态异常。

   推荐使用相同或接近的 Chromium/CloakBrowser 主版本，并在切换前复制一份备份。不同电脑之间迁移时，Cookie、已保存密码等系统加密数据可能无法直接解密；同一台电脑、同一系统用户下兼容性最好。

## 如果你找不到文件夹

macOS 可以在 Finder 里按 `Shift + Command + G`，输入：

```text
~/Library/Application Support/CloakBrowser Manager
```

Windows 可以直接在资源管理器地址栏输入：

```text
%LOCALAPPDATA%\CloakBrowser Manager
```

如果你要找 CloakBrowser 二进制缓存：

- macOS：Finder 按 `Shift + Command + G`，输入 `~/.cloakbrowser`
- Windows：资源管理器输入 `%USERPROFILE%\.cloakbrowser`

## 补充

如果你手动改过 `CLOAKBROWSER_MANAGER_DATA_DIR`，那实际存储位置会优先使用你自己设置的路径。
