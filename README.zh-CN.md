# CloakBrowser Manager 改造版

这是基于 CloakBrowser-Manager 的自托管浏览器配置管理器。它适合用来创建、保存、启动多个隔离浏览器配置，并通过网页登录管理。

## 这套方案做了什么

- 中文界面：创建配置、启动、代理、语言、时区、画像等主要操作已改成中文。
- 代理增强：支持 HTTP / HTTPS / SOCKS5，按协议、主机、端口、账号、密码分开填写，并可测试代理出口 IP、国家、时区。
- IP 跟随：代理测试后可把时区、语言建议写入配置，减少 IP、语言、时区不一致。
- Apple Silicon 画像：内置多组 M1 / M2 / M3 / M4 / M5 系列 macOS 设备画像。
- 稳定原生模式：macOS 本机默认可用系统 Google Chrome，尽量保持真实 Chrome 行为。
- 伪装画像模式：需要 CloakBrowser/Chromium 二进制时，可选择画像并填充 GPU、CPU、UA、分辨率等参数。
- 指纹自检：浏览器启动后可生成本地自检报告，提示配置里明显不一致的地方。
- 账号密码登录：服务器部署时有管理员账号，登录后可在右上角钥匙按钮修改用户名和密码。
- 一键服务器安装：提供 `install.sh`，自动安装 Docker、启动服务，并用 Caddy 做 HTTPS 反代。

## 重要边界

macOS 本机的“系统 Chrome 原生模式”只适合本地电脑，因为它依赖你机器上真正安装的 Google Chrome。

Linux 服务器部署使用 Docker + CloakBrowser/Chromium + VNC。它能远程管理和运行浏览器，但不是 Apple Silicon 原生 Chrome。画像可以帮助配置保持一致，但不能保证绕过所有网站检测。

不要把“随机改参数”当成好画像。更稳的做法是选择一套合理、互相匹配的设备画像，再让语言、时区、代理 IP 尽量一致。

## 一键安装到服务器

服务器要求：

- Ubuntu / Debian / CentOS / Rocky / AlmaLinux 等常见 Linux
- root 权限
- 域名 A 记录已经指向服务器 IP
- 服务器安全组放行 80 和 443

一键安装：

```bash
curl -fsSL https://raw.githubusercontent.com/NorwayXZ/CloakBrowser-Manager/main/install.sh -o install.sh
chmod +x install.sh
sudo ./install.sh --domain cloak.example.com
```

指定初始账号密码：

```bash
sudo ./install.sh \
  --domain cloak.example.com \
  --username admin \
  --password 'your-strong-password'
```

安装完成后打开：

```text
https://cloak.example.com
```

第一次启动会构建 Docker 镜像，可能需要几分钟。

## 后台修改登录账号

登录后点击右上角钥匙图标：

- 修改用户名
- 修改密码

修改密码后，旧登录会话会自动失效。服务器上的配置文件在：

```text
/opt/cloakbrowser-manager/.env
```

## 常用维护命令

进入安装目录：

```bash
cd /opt/cloakbrowser-manager
```

查看运行状态：

```bash
docker compose -f docker-compose.prod.yml ps
```

查看日志：

```bash
docker compose -f docker-compose.prod.yml logs -f --tail=100
```

更新：

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

重启：

```bash
docker compose -f docker-compose.prod.yml restart
```

停止：

```bash
docker compose -f docker-compose.prod.yml down
```

## 本地 macOS 使用

```bash
cd CloakBrowser-Manager
./run-macos.sh
```

打开：

```text
http://127.0.0.1:8080
```

本地 macOS 更适合使用“稳定原生”模式，也就是系统 Google Chrome。服务器部署更适合长期在线、统一管理和远程访问。
