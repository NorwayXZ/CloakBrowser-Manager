<p align="center">
<img src="https://i.imgur.com/cqkp6fG.png" width="500" alt="CloakBrowser">
</p>

<h3 align="center">Browser Profile Manager for CloakBrowser</h3>

<p align="center">
Create and launch isolated browser profiles on your local Windows or macOS computer.
</p>

<p align="center">
<a href="https://github.com/CloakHQ/CloakBrowser"><img src="https://img.shields.io/github/stars/cloakhq/cloakbrowser?label=CloakBrowser" alt="Stars"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
</p>

---

> 中文说明见 [README.zh-CN.md](README.zh-CN.md).
> This fork focuses on local desktop use on Windows/macOS, with Chinese UI polish, proxy testing, Apple Silicon presets, optional login, and fingerprint reports.

<p align="center">
<img src="https://i.imgur.com/twdX81Q.png" width="800" alt="CloakBrowser Manager — Browser View">
<br>
<img src="https://i.imgur.com/XFYn1qY.png" width="800" alt="CloakBrowser Manager — Profile Settings">
</p>

Each profile is an isolated CloakBrowser instance with its own fingerprint, proxy, cookies, and session data. Profiles persist across restarts. Windows and macOS launch browsers directly in native desktop windows.

### Quick Start

Clone the repository, then start the platform launcher:

```text
Install: install-windows.bat / ./install-macos.sh
Windows: run-windows.bat
macOS:   ./run-macos.sh
Uninstall: uninstall-windows.bat / ./uninstall-macos.sh
```

The first run creates a local Python environment, installs dependencies, builds the React UI, starts Manager on `127.0.0.1:8080`, and opens it in your default browser. Profiles are stored in `%LOCALAPPDATA%\CloakBrowser Manager` on Windows and `~/Library/Application Support/CloakBrowser Manager` on macOS.

One-click install/uninstall wrappers and full data-location notes are in [docs/local-install-uninstall.zh-CN.md](docs/local-install-uninstall.zh-CN.md).

Open [http://127.0.0.1:8080](http://127.0.0.1:8080), create a profile, and click Launch.

> **Early alpha** - this project is under active development. Expect bugs. If you find one, please [open an issue](https://github.com/CloakHQ/CloakBrowser-Manager/issues).

## Features

- Profile management
- Per-profile settings for fingerprint seed, proxy, timezone, locale, user agent, screen size, and platform
- One-click launch/stop
- Session persistence
- Platform-native browsing on Windows/macOS
- Proxy testing
- Apple Silicon profile presets
- Fingerprint report
- Playwright/Puppeteer API via CDP
- Optional authentication for local use
- Powered by CloakBrowser

## Stack

- Backend: FastAPI (Python)
- Frontend: React + Tailwind CSS
- Browser viewer: native desktop windows
- Database: SQLite
- Browser engine: [CloakBrowser](https://github.com/CloakHQ/CloakBrowser)

## Development

### Native backend

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8080
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Requirements

- Windows or macOS native: Python 3.10+, Node.js 18+
- macOS stable native mode also expects Google Chrome
- About 2 GB disk space
- About 512 MB RAM per running profile

## Automation API

Every running profile exposes a CDP (Chrome DevTools Protocol) endpoint.

```python
from playwright.async_api import async_playwright

async with async_playwright() as pw:
    browser = await pw.chromium.connect_over_cdp(
        "http://localhost:8080/api/profiles/<profile-id>/cdp"
    )
    page = browser.contexts[0].pages[0]
    await page.goto("https://example.com")
```

## Authentication

Local builds can optionally enable login with `ADMIN_USERNAME` and `ADMIN_PASSWORD`. The account can later be changed from the web UI.

## License

- This application (GUI source code) - MIT. See [LICENSE](LICENSE).
- CloakBrowser binary (compiled Chromium) - free to use, no redistribution. See [BINARY-LICENSE.md](BINARY-LICENSE.md).

## Links

- **CloakBrowser** - [github.com/CloakHQ/CloakBrowser](https://github.com/CloakHQ/CloakBrowser)
- **Website** - [cloakbrowser.dev](https://cloakbrowser.dev)
- **Bug reports** - [GitHub Issues](https://github.com/CloakHQ/CloakBrowser-Manager/issues)
- **Contact** - cloakhq@pm.me
