# CloakBrowser Manager 本地版

这是给普通用户看的中文安装说明。项目只面向本地 Windows / macOS 使用，不需要服务器。

完整教程已经放在 GitHub 首页：[README.md](README.md)

如果你是第一次安装，按这个顺序来：

1. 安装 Google Chrome
2. 安装 Python 3.10+
3. 安装 Node.js 18+
4. 下载本项目
5. 运行安装脚本
6. 打开 `http://127.0.0.1:8080`

macOS：

```bash
cd CloakBrowser-Manager
chmod +x install-macos.sh run-macos.sh uninstall-macos.sh bin/cloak
./install-macos.sh
```

Windows：

```text
双击 install-windows.bat
```

以后启动：

```text
macOS:   ./run-macos.sh
Windows: 双击 run-windows.bat
```

也可以直接下载安装包版（macOS DMG / Windows 安装程序），双击就能用，不用再开终端：
[Releases 页面](https://github.com/NorwayXZ/CloakBrowser-Manager/releases/latest)。详见 [README.md](README.md) 里的「可选：安装包版，双击就能用」。

浏览器内核怎么更新：

- 面板左侧「浏览器内核」页显示当前用的 CloakBrowser 内核版本和授权类型，可以「检查更新」「立即更新」、切换稳定版/预览版、删除旧版本释放空间。
- 默认启动浏览器时自动下载新内核；付费授权还可以锁定到某个旧版本。
- 只有「伪装画像」引擎用这个内核；「稳定原生」用电脑上的 Google Chrome，跟着 Chrome 自己更新。
- Manager 本身（面板和安装包）的更新是另一回事，在菜单「检查更新」里下载新安装包。

数据目录：

```text
macOS:   ~/Library/Application Support/CloakBrowser Manager
Windows: %LOCALAPPDATA%\CloakBrowser Manager
```

更详细的安装、卸载、备份、迁移说明见：

- [README.md](README.md)
- [docs/local-install-uninstall.zh-CN.md](docs/local-install-uninstall.zh-CN.md)
