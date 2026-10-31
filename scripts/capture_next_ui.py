"""Screenshot the redesigned panel (the root page) and check its layout.

Same isolation as capture_baseline_ui.py (own Manager, throwaway data
directory, example data, no browser profile launched). Every screen is taken
at four widths in light and dark, and a script in the page reports layout
faults: horizontal page scroll, elements pushed past the right edge, and text
cut off without an ellipsis. Any fault makes the script exit 1.

    python scripts/capture_next_ui.py [output_dir]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_baseline_ui import ROOT, call, free_port, seed, start_server  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "next-screenshots"
SIZES = [(900, 640), (1024, 680), (1280, 800), (1600, 1000)]
THEMES = ["light", "dark"]

LAYOUT_CHECK = """
() => {
  const faults = [];
  const vw = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > vw + 1) faults.push(`page scrolls sideways (${document.documentElement.scrollWidth} > ${vw})`);
  // The shell never scrolls as a whole; only its panes do. A scrolled page means
  // something (e.g. scrollIntoView) pushed the toolbar out of the window.
  if (window.scrollY > 0 || document.querySelector("#root")?.parentElement?.scrollTop) faults.push(`the page itself is scrolled by ${window.scrollY}px`);
  const describe = (el) => {
    const id = el.id ? `#${el.id}` : "";
    const text = (el.textContent || "").trim().slice(0, 40);
    return `${el.tagName.toLowerCase()}${id} "${text}"`;
  };
  const scrollsX = (el) => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if (o === "auto" || o === "scroll") return true;
    }
    return false;
  };
  for (const el of document.querySelectorAll("body *")) {
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || el.closest(".sr-only")) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    if (rect.right > vw + 1 && !scrollsX(el)) faults.push(`past right edge by ${Math.round(rect.right - vw)}px: ${describe(el)}`);
    const clips = style.overflowX === "hidden" || style.overflowX === "clip";
    const hasOwnText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (clips && hasOwnText && el.scrollWidth > el.clientWidth + 1 && style.textOverflow !== "ellipsis") {
      faults.push(`text cut off: ${describe(el)}`);
    }
    // A box that hides vertical overflow while its content is taller: content squeezed away.
    const clipsY = style.overflowY === "hidden" || style.overflowY === "clip";
    if (clipsY && el.textContent.trim() && el.scrollHeight > el.clientHeight + 2 && !style.webkitLineClamp?.match(/^\d/)) {
      faults.push(`content cut off at the bottom: ${describe(el)}`);
    }
  }
  return [...new Set(faults)].slice(0, 20);
}
"""


def seed_reports(data_dir: Path, base: str, browser) -> None:
    """Two example detection reports for one profile (older and newer), so the
    report screens show real content. Example data, written straight into the
    throwaway data directory; no browser profile is launched."""
    profile = next(p for p in call(base, "GET", "/api/profiles") if p["name"] == "Etsy UK")
    page = browser.new_page(viewport={"width": 640, "height": 400})

    def shot(title: str, verdict: str) -> bytes:
        page.set_content(f"<body style='margin:0;font:28px sans-serif;background:#eef1f7;display:flex;align-items:center;justify-content:center;height:100vh'>"
                         f"<div><b>{title}</b><br><span style='color:#666'>{verdict}（示例截图）</span></div></body>")
        return page.screenshot()

    def result(site, name, status, summary, details=(), local=False, ip_note=None):
        return {"site": site, "name": name, "url": "", "criteria": "示例标准", "status": status, "summary": summary,
                "details": list(details), "screenshot": None if local else f"{site}.png", "seconds": 20,
                "source": "local" if local else "site", "ip_note": ip_note}

    for stamp, pixelscan in (("20261023-100000", "pass"), ("20261024-100000", "fail")):
        folder = data_dir / "check-reports" / f"{stamp}-Etsy_UK"
        folder.mkdir(parents=True, exist_ok=True)
        results = [
            result("local_gpu", "GPU / WebGL", "pass", "ANGLE (Apple, ANGLE Metal Renderer: Apple M2)", local=True),
            result("creepjs", "CreepJS", "pass", "没有 lies，headless 0%，stealth 0%", ["lies：0 处"]),
            result("pixelscan", "Pixelscan", pixelscan, "指纹一致" if pixelscan == "pass" else "指纹不一致、检测到伪装", ["指纹：" + ("一致" if pixelscan == "pass" else "不一致")]),
            result("fingerprint", "Fingerprint.com", "warn", "浏览器没被认出，但 IP 被认出", ip_note="这一项的结论受出口 IP 信誉影响"),
        ]
        for item in results:
            if item["screenshot"]:
                (folder / item["screenshot"]).write_bytes(shot(item["name"], item["summary"]))
        report = {
            "id": folder.name, "created_at": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T10:00:00+08:00",
            "overall": "fail" if pixelscan == "fail" else "warn",
            "environment": {"profile_id": profile["id"], "profile_name": profile["name"], "host_os": "macos", "kernel_version": "145.0.7632.159.1", "exit_ip": "192.0.2.55", "exit_country": "GB"},
            "results": results,
            "egress_note": "示例报告：出口 192.0.2.55（GB）。标注“IP 信誉”的条目结论受出口 IP 影响。",
        }
        (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    page.close()


KERNEL_FIXTURE = {
    "wrapper_version": "0.6.2", "platform": "darwin-arm64", "cache_dir": "/Users/example/.cloakbrowser",
    "license": {"tier": "free", "plan": "free", "expires": None, "can_pin": False, "key_stored": True},
    "settings": {"auto_update": True, "release_channel": "stable", "pinned_version": None},
    "version": "154.0.8037.57.1", "installed": True, "pinned": False, "bundled_version": "146.0.7680.177.5",
    "installed_kernels": [
        {"name": "chromium-154.0.8037.57.1-pro", "version": "154.0.8037.57.1", "pro": True, "size_bytes": 408 << 20, "in_use": True},
        {"name": "chromium-145.0.7632.109.2", "version": "145.0.7632.109.2", "pro": False, "size_bytes": 367 << 20, "in_use": False},
    ],
    "running_count": 0,
}
UPDATE_FIXTURE = {"phase": "downloading", "label": "正在下载新版本", "target": "0.8.0", "done": 42, "total": 100,
                  "supported": True, "current_version": "0.7.2", "last_result": None}
SIGNED_OUT_FIXTURE = {"auth_required": True, "authenticated": False, "username": "admin"}


def screens(page: Page, base: str):
    faked: list[str] = []

    def fake(answers: dict[str, dict]):
        """Answer these API paths with example JSON until the next screen starts."""
        def install():
            for path, body in answers.items():
                pattern = f"**{path}"
                payload = json.dumps(body, ensure_ascii=False)

                def answer(route, _request=None, payload=payload):
                    route.fulfill(status=200, content_type="application/json", body=payload)

                page.route(pattern, answer)
                faked.append(pattern)
        return install

    def go(path: str, ready: str, before=None):
        def run():
            while faked:
                page.unroute(faked.pop())
            if before:
                before()
            page.goto(base + path)
            page.wait_for_selector(ready)
            page.wait_for_timeout(700)
        return run

    def with_action(path: str, ready: str, action):
        def run():
            go(path, ready)()
            action()
            page.wait_for_timeout(500)
        return run

    first_row = lambda: page.locator("[data-row]").first
    yield "01-profiles", go("/profiles", "[data-row]"), False
    yield "01b-profiles-drawer", with_action("/profiles", "[data-row]",
                                             lambda: first_row().locator("div.truncate").first.click()), False
    yield "01c-profiles-batch", with_action("/profiles", "[data-row]", lambda: (
        page.get_by_role("checkbox", name="全选当前列表").click())), False
    yield "01d-profiles-row-menu", with_action("/profiles", "[data-row]",
                                               lambda: page.get_by_role("button", name="的更多操作").first.click()), False
    yield "01e-preflight", with_action("/profiles", "[data-row]", lambda: (
        page.locator("[data-row]", has_text="Etsy UK").get_by_role("button", name="打开「Etsy UK」").click(),
        page.wait_for_selector("text=打开前检查"))), False
    yield "01f-sentence", go("/profiles?create=sentence", "text=一句话描述"), False
    yield "01f2-sentence-preview", with_action("/profiles?create=sentence", "text=一句话描述", lambda: (
        page.get_by_role("textbox", name="一句话描述").fill("建个美国号，西雅图，喜欢露营摄影"),
        page.get_by_role("button", name="解析").click(),
        page.wait_for_selector("text=一句话建号预览"))), False
    yield "01g-disposable", go("/profiles?create=disposable", "text=新建一次性身份"), False
    yield "01h-no-match", go("/profiles?q=zzzz", "text=没有匹配的环境"), False
    def edit_first():
        page.goto(base + "/profiles")
        page.wait_for_selector("[data-row]")
        page.get_by_role("button", name="「Amazon Seller #1」的更多操作").click()
        page.get_by_role("menuitem", name="编辑").click()
        page.wait_for_selector("#form-basic")
        page.wait_for_timeout(700)

    def section(name: str):
        def run():
            edit_first()
            page.get_by_role("navigation", name="表单分区").get_by_role("button", name=name).click()
            page.wait_for_timeout(900)
        return run

    yield "02a-editor-new", go("/profiles/new", "#form-basic"), False
    yield "02b-editor-edit", edit_first, False
    yield "02c-editor-proxy", section("代理信息"), False
    yield "02d-editor-fingerprint", section("指纹配置"), False
    yield "02e-editor-more", section("更多指纹"), False
    yield "02f-editor-advanced", with_action("/profiles/new", "#form-basic", lambda: (
        page.get_by_role("textbox", name="名称").fill("向导示例"),
        page.get_by_role("list", name="创建步骤").get_by_role("button", name="更多").click(),
        page.get_by_role("checkbox", name="养号（定时自动浏览养护）").click(),
        page.wait_for_timeout(600))), False
    yield "02h-wizard-network", with_action("/profiles/new", "#form-basic", lambda: (
        page.get_by_role("textbox", name="名称").fill("向导示例"),
        page.get_by_role("button", name="下一步").click(),
        page.wait_for_selector("text=这个环境怎么上网？"),
        page.wait_for_timeout(500))), False
    yield "02i-wizard-device", with_action("/profiles/new", "#form-basic", lambda: (
        page.get_by_role("textbox", name="名称").fill("向导示例"),
        page.get_by_role("list", name="创建步骤").get_by_role("button", name="设备").click(),
        page.wait_for_selector("text=它是一台什么设备？"),
        page.wait_for_timeout(500))), False
    yield "02g-editor-leave", with_action("/profiles/new", "#form-basic", lambda: (
        page.get_by_role("textbox", name="名称").fill("没保存的环境"),
        page.get_by_role("button", name="取消").click(),
        page.wait_for_selector("text=放弃没保存的修改？"))), False
    yield "03a-proxies", go("/proxies", "text=美国 SOCKS5"), False
    yield "03b-proxies-batch", with_action("/proxies", "text=美国 SOCKS5", lambda: (
        page.get_by_role("tab", name="批量导入").click(),
        page.get_by_label("批量代理").fill("192.168.0.1:8000\nsocks5://user:pass@10.0.0.1:1080\nvless://uuid@edge.example.com:443?security=tls#东京\n写错的一行"))), False
    yield "04a-data", go("/data", "text=备份记录"), True
    yield "04b-data-restore-confirm", with_action("/data", "text=备份记录", lambda: (
        page.get_by_role("button", name="恢复到", exact=False).first.click(),
        page.wait_for_selector("role=dialog"))), False
    yield "04c-trash", go("/data/trash", "text=已删除的旧环境"), False
    yield "05a-checks", go("/checks", "text=检测哪些网站"), False
    yield "05b-checks-report", go("/checks?report=20261024-100000-Etsy_UK", "text=和上次不同"), True
    yield "05c-checks-evolution", go("/checks/evolution", "text=进化时间线"), False
    yield "05d-checks-links", go("/checks/links", "text=关联分析"), False
    yield "02-settings-appearance", go("/settings", "text=主题"), False
    yield "06a-settings-kernel", go("/settings/kernel", "text=已下载的内核", fake({"/api/kernel": KERNEL_FIXTURE})), True
    yield "06b-settings-ai", go("/settings/ai", "text=执行强度"), False
    yield "06c-settings-automation", go("/settings/automation", "text=允许的时段"), False
    yield "06d-settings-account", go("/settings/account", "text=没有开启登录保护"), False
    yield "06e-settings-about", go("/settings/about", "text=还没有检查过"), False
    yield "06f-settings-updating", go("/settings/about", "text=正在下载新版本", fake({"/api/app/update": UPDATE_FIXTURE})), False
    yield "06g-login", go("/profiles", "text=输入管理员账号和密码", fake({"/api/auth/status": SIGNED_OUT_FIXTURE})), False
    yield "04-running-popover", with_action("/settings", "text=主题",
                                            lambda: page.get_by_role("button", name="未运行").click()), False
    yield "05-theme-menu", with_action("/settings", "text=主题",
                                       lambda: page.get_by_role("button", name="外观：跟随系统").click()), False
    yield "06-shortcuts", with_action("/settings", "text=主题", lambda: page.keyboard.press("Shift+Slash")), False
    yield "07-gallery", go("/__ui", "text=组件展示"), True
    yield "08-confirm-dialog", with_action("/__ui", "text=组件展示",
                                           lambda: page.get_by_role("button", name="确认对话框").click()), False
    yield "09-not-found", go("/whatever", "text=没有这个页面"), False


def main() -> int:
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        print("frontend/dist is missing: run `npm run build` in frontend/ first", file=sys.stderr)
        return 1
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = start_server(port)
    report: dict[str, dict] = {}
    failures: list[str] = []
    try:
        seed(base)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            seed_reports(proc.data_dir, base, browser)
            for theme in THEMES:
                for width, height in SIZES:
                    context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme,
                                                  device_scale_factor=1, locale="zh-CN")
                    page = context.new_page()
                    errors: list[str] = []
                    page.on("pageerror", lambda exc: errors.append(str(exc)))
                    out_dir = OUT / theme / str(width)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    for name, setup, full_page in screens(page, base):
                        key = f"{theme}/{width}/{name}"
                        try:
                            setup()
                            if full_page:
                                # The page itself never scrolls (main does), so grow the window to the content.
                                tall = page.evaluate("() => document.querySelector('main').scrollHeight + 52")
                                page.set_viewport_size({"width": width, "height": max(height, tall)})
                            page.screenshot(path=str(out_dir / f"{name}.png"))
                            faults = page.evaluate(LAYOUT_CHECK)
                            if full_page:
                                page.set_viewport_size({"width": width, "height": height})
                            report[key] = {"faults": faults}
                            if faults:
                                failures.append(f"{key}: " + "; ".join(faults))
                        except Exception as exc:
                            failures.append(f"{key}: {exc}")
                    if errors:
                        failures.append(f"{theme}/{width}: page errors: {errors[:3]}")
                    context.close()
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "layout-report.json").write_text(json.dumps({"screens": report, "failures": failures}, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
    for line in failures:
        print("FAULT", line, file=sys.stderr)
    print(f"{len(report)} screens checked, {len(failures)} with faults; output in {OUT}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
