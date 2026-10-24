"""Screenshot every screen of the panel at several window widths.

Used as the visual reference for the panel redesign (docs/redesign/). It
starts its own Manager on a free port with a throwaway data directory, fills
it with example data (documentation IP ranges, no real accounts), and drives
the panel with Playwright's bundled Chromium. Nothing here touches the
user's real data directory, and no browser profile is ever launched: the
preflight dialog is opened and cancelled.

Run from the repository root after `npm run build` in frontend/:

    python scripts/capture_baseline_ui.py [output_dir]

Writes <output_dir>/<width>/<screen>.jpg and <output_dir>/manifest.json
(per screen: whether the page scrolls horizontally).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "redesign" / "baseline" / "screenshots"
SIZES = [(1024, 680), (1280, 800), (1600, 1000)]
JPEG_QUALITY = 72


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def call(base: str, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def start_server(port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env["CLOAKBROWSER_MANAGER_DATA_DIR"] = tempfile.mkdtemp(prefix="cbm-baseline-data-")
    env["CLOAKBROWSER_MANAGER_BACKUP_COPY_DIR"] = tempfile.mkdtemp(prefix="cbm-baseline-backup-")
    env["CLOAKBROWSER_MANAGER_PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            call(base, "GET", "/api/status")
            return proc
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("Manager exited during startup")
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("Manager did not answer within 60 s")


def seed(base: str) -> None:
    call(base, "POST", "/api/groups", {"name": "美国账号", "color": "#2f5bff"})
    call(base, "POST", "/api/groups", {"name": "日本账号", "color": "#e11d48"})
    call(base, "POST", "/api/proxy-presets/bulk", {"items": [
        {"name": "美国 SOCKS5 #1", "proxy": "socks5://demo:demo@203.0.113.24:1080", "mode": "socks5"},
        {"name": "日本 HTTP", "proxy": "http://198.51.100.7:8080", "mode": "http"},
        {"name": "英国 HTTPS", "proxy": "https://user:pass@192.0.2.55:443", "mode": "https"},
    ]})
    examples = [
        ("Amazon Seller #1", "美国账号", "Amazon", "socks5://demo:demo@203.0.113.24:1080", "主店铺，只在白天登录"),
        ("TikTok JP 02", "日本账号", "TikTok", "http://198.51.100.7:8080", None),
        ("Etsy UK", "未分组", "Etsy", "https://user:pass@192.0.2.55:443", "备用号"),
        ("Google Ads 测试", "美国账号", "Google", None, None),
        ("一个名字特别长的环境用来检查列表里的截断和换行表现", "未分组", None, None, "这是一段比较长的备注，用来观察备注列在窄窗口下会不会把表格撑宽或者把按钮挤出可视区域"),
    ]
    for name, group, platform, proxy, notes in examples:
        call(base, "POST", "/api/profiles", {
            "name": name, "group_name": group, "account_platform": platform,
            "proxy": proxy, "notes": notes, "platform": "macos" if sys.platform == "darwin" else "windows",
        })
    call(base, "POST", "/api/profiles/disposable", {"region": "US"})
    trashed = call(base, "POST", "/api/profiles", {"name": "已删除的旧环境", "platform": "macos" if sys.platform == "darwin" else "windows"})
    call(base, "DELETE", f"/api/profiles/{trashed['id']}")


def settle(page: Page, ms: int = 900) -> None:
    page.wait_for_timeout(ms)


def nav(page: Page, label: str) -> None:
    page.get_by_role("button", name=label, exact=True).first.click()
    settle(page, 1300)


def screens(page: Page, base: str):
    """Yield (name, setup) pairs; each setup starts from a fresh list view."""

    def home():
        page.goto(base + "/")
        page.wait_for_selector("text=Amazon Seller #1")
        settle(page)

    def list_view():
        home()

    def list_selected():
        home()
        boxes = page.locator("tbody input[type=checkbox]")
        boxes.nth(0).check()
        boxes.nth(1).check()
        page.get_by_title("更多批量操作").click()
        settle(page, 400)

    def row_menu():
        home()
        page.locator("tbody").get_by_title("更多", exact=True).first.click()
        settle(page, 400)

    def preflight():
        home()
        page.locator("tbody").get_by_role("button", name="打开", exact=True).first.click()
        page.wait_for_selector("text=启动前检查")
        settle(page, 600)

    def sentence():
        home()
        page.get_by_label("一句话建号").fill("建个美国号，西雅图，喜欢露营摄影")
        page.get_by_title("用一句话解析出完整画像：先预览、可修改，确认后才创建").click()
        page.wait_for_selector("text=一句话建号预览")
        settle(page, 600)

    def form_section(section: str | None, edit: bool = False):
        def run():
            home()
            if edit:
                page.get_by_title("编辑").first.click()
            else:
                page.get_by_role("button", name="新建浏览器").click()
            page.wait_for_selector("nav[aria-label='表单分区']")
            settle(page, 700)
            if section:
                page.locator("nav[aria-label='表单分区']").get_by_role("button", name=section, exact=True).click()
                settle(page, 900)
        return run

    def section_page(label: str, extra=None):
        def run():
            home()
            nav(page, label)
            if extra:
                extra()
        return run

    def proxies_batch():
        page.get_by_role("button", name="批量导入").click()
        settle(page, 400)

    yield "01-environments", list_view
    yield "02-environments-batch-menu", list_selected
    yield "03-environments-row-menu", row_menu
    yield "04-preflight-dialog", preflight
    yield "05-sentence-preview", sentence
    yield "06-new-basic", form_section(None)
    yield "07-new-proxy", form_section("代理信息")
    yield "08-new-fingerprint", form_section("指纹配置")
    yield "09-new-more-fingerprint", form_section("更多指纹")
    yield "10-new-advanced", form_section("高级设置")
    yield "11-edit-basic", form_section(None, edit=True)
    yield "12-groups", section_page("分组管理")
    yield "13-proxies-single", section_page("代理管理")
    yield "14-proxies-batch", section_page("代理管理", proxies_batch)
    yield "15-kernel", section_page("浏览器内核")
    yield "16-ai-settings", section_page("AI 设置")
    yield "17-fingerprint-checks", section_page("指纹检测")
    yield "18-linkability", section_page("关联分析")
    yield "19-backup", section_page("数据备份")
    yield "20-trash", section_page("回收站")


def main() -> int:
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        print("frontend/dist is missing: run `npm run build` in frontend/ first", file=sys.stderr)
        return 1
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = start_server(port)
    manifest: dict[str, dict] = {}
    failures: list[str] = []
    try:
        seed(base)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width, height in SIZES:
                context = browser.new_context(viewport={"width": width, "height": height},
                                              device_scale_factor=1, locale="zh-CN")
                page = context.new_page()
                out_dir = OUT / str(width)
                out_dir.mkdir(parents=True, exist_ok=True)
                for name, setup in screens(page, base):
                    try:
                        setup()
                        page.screenshot(path=str(out_dir / f"{name}.jpg"), type="jpeg", quality=JPEG_QUALITY)
                        overflow = page.evaluate(
                            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth")
                        manifest.setdefault(name, {})[str(width)] = {"horizontal_overflow": overflow}
                    except Exception as exc:  # keep going: one broken screen should not hide the rest
                        failures.append(f"{width}/{name}: {exc}")
                context.close()
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "manifest.json").write_text(
        json.dumps({"sizes": [f"{w}x{h}" for w, h in SIZES], "screens": manifest, "failures": failures},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for line in failures:
        print("FAILED", line, file=sys.stderr)
    print(f"{sum(len(v) for v in manifest.values())} screenshots in {OUT}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
