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

数据目录：

```text
macOS:   ~/Library/Application Support/CloakBrowser Manager
Windows: %LOCALAPPDATA%\CloakBrowser Manager
```

更详细的安装、卸载、备份、迁移说明见：

- [README.md](README.md)
- [docs/local-install-uninstall.zh-CN.md](docs/local-install-uninstall.zh-CN.md)
