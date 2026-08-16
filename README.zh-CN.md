# CloakBrowser Manager 本地版

这是基于 CloakBrowser-Manager 的本地桌面版配置管理器，重点面向 Windows 和 macOS。

## 现在保留什么

- 中文界面
- 代理增强：HTTP / HTTPS / SOCKS5，分开填写主机、端口、账号、密码
- 代理测试：可查看出口 IP、国家、时区、语言建议
- Apple Silicon 画像：内置多组 M1 / M2 / M3 / M4 / M5 系列 macOS 设备画像
- 稳定原生模式：macOS 本机可用系统 Google Chrome
- 伪装画像模式：可继续调 GPU、CPU、UA、分辨率等参数
- 指纹自检：启动后生成本地报告，提示明显不一致的地方
- 账号密码登录：可选，本地也能启用

## 本地使用

```bash
Windows: run-windows.bat
macOS:   ./run-macos.sh
```

首次启动会创建本地 Python 环境，安装依赖，构建前端，然后打开：

```text
http://127.0.0.1:8080
```

Windows 配置会保存在：

```text
%LOCALAPPDATA%\CloakBrowser Manager
```

macOS 配置会保存在：

```text
~/Library/Application Support/CloakBrowser Manager
```

## 使用建议

macOS 本机的“稳定原生”模式适合直接用真实 Chrome。伪装画像模式更适合继续调试指纹一致性、代理和语言时区。

不要把“随机改参数”当成好画像。更稳的做法是选一套互相匹配的设备画像，再让语言、时区、代理 IP 尽量一致。

## 开发

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8080
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## API

每个正在运行的配置都提供 CDP 接口，可以给 Playwright / Puppeteer 连接。

## 许可证

- 本应用 GUI 源码：MIT，见 [LICENSE](LICENSE)
- CloakBrowser 二进制：免费使用，不能重新分发，见 [BINARY-LICENSE.md](BINARY-LICENSE.md)
