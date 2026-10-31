"""End-to-end smoke test of the redesigned panel against a real Manager.

Starts its own Manager on a free port with a throwaway data directory (same
isolation as capture_baseline_ui.py), drives the panel with Playwright's Chromium,
and checks each result through the API. It never launches a browser profile:
that needs the real kernel and a license seat, and stays a manual check.

    python scripts/smoke_next_ui.py
"""

from __future__ import annotations

import secrets
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_baseline_ui import ROOT, call, free_port, seed, start_server  # noqa: E402


def profiles_by_name(base: str) -> dict[str, dict]:
    return {p["name"]: p for p in call(base, "GET", "/api/profiles")}


def step(name: str):
    print(f"· {name}", flush=True)


def run(page: Page, base: str) -> None:
    page.goto(base + "/profiles")
    expect(page.get_by_role("row", name="Amazon Seller #1")).to_be_visible()

    step("search narrows the list and can be cleared")
    page.get_by_role("textbox", name="搜索环境").fill("主店铺")
    expect(page.get_by_role("row", name="Etsy UK")).to_have_count(0)
    page.get_by_role("textbox", name="搜索环境").fill("")

    step("create a group from the rail")
    page.get_by_role("button", name="新建分组").click()
    page.get_by_role("textbox", name="新分组名称").fill("冒烟测试组")
    page.get_by_role("button", name="添加").click()
    expect(page.get_by_role("navigation", name="分组").get_by_role("button", name="冒烟测试组")).to_be_visible()
    assert any(g["name"] == "冒烟测试组" for g in call(base, "GET", "/api/groups"))

    step("save a note from the details panel")
    page.get_by_role("row", name="Etsy UK").locator("td").nth(2).click()
    panel = page.get_by_role("complementary", name="Etsy UK")
    note = panel.get_by_role("textbox", name="「Etsy UK」的备注")
    note.fill("冒烟测试备注")
    note.press("Enter")
    expect(panel.get_by_label("正在保存备注")).to_have_count(0)
    page.wait_for_timeout(500)
    assert profiles_by_name(base)["Etsy UK"]["notes"] == "冒烟测试备注"
    page.keyboard.press("Escape")

    step("copy an environment")
    page.get_by_role("button", name="「Etsy UK」的更多操作").click()
    page.get_by_role("menuitem", name="复制").click()
    expect(page.get_by_role("row", name="Etsy UK 副本")).to_be_visible()
    copy = profiles_by_name(base)["Etsy UK 副本"]
    original = profiles_by_name(base)["Etsy UK"]
    assert copy["proxy"] == original["proxy"] and copy["fingerprint_seed"] != original["fingerprint_seed"]

    step("move to the trash, then undo")
    page.get_by_role("button", name="「Etsy UK 副本」的更多操作").click()
    page.get_by_role("menuitem", name="移到回收站").click()
    expect(page.get_by_role("row", name="Etsy UK 副本")).to_have_count(0)
    assert "Etsy UK 副本" not in profiles_by_name(base)
    page.get_by_role("button", name="撤销").click()
    expect(page.get_by_role("row", name="Etsy UK 副本")).to_be_visible()

    step("one-sentence profile with the keyword parser (no AI configured)")
    page.get_by_role("button", name="新建", exact=True).click()
    page.get_by_role("menuitem", name="一句话建号").click()
    page.get_by_role("textbox", name="一句话描述").fill("建个日本号，东京，喜欢动漫")
    page.get_by_role("button", name="解析").click()
    preview = page.get_by_role("dialog", name="一句话建号预览")
    expect(preview.get_by_text("关键词解析", exact=True)).to_be_visible()
    preview.get_by_label("名称", exact=False).first.fill("冒烟测试东京号")
    preview.get_by_role("button", name="确认创建").click()
    expect(page.get_by_role("complementary", name="冒烟测试东京号")).to_be_visible()
    made = profiles_by_name(base)["冒烟测试东京号"]
    assert made["timezone"] == "Asia/Tokyo", made["timezone"]

    step("disposable identity, then burn it")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="新建", exact=True).click()
    page.get_by_role("menuitem", name="一次性身份").click()
    dialog = page.get_by_role("dialog", name="新建一次性身份")
    dialog.get_by_label("地区").select_option("GB")
    dialog.get_by_role("button", name="创建").click()
    panel = page.locator("aside[aria-labelledby=profile-drawer-title]")
    expect(panel.get_by_text("一次性", exact=True)).to_be_visible()
    name = panel.locator("#profile-drawer-title").inner_text()
    assert profiles_by_name(base)[name]["timezone"] == "Europe/London"
    panel.get_by_role("button", name="永久删除").click()
    page.get_by_role("dialog", name=f"永久删除「{name}」？").get_by_role("button", name="永久删除").click()
    expect(page.get_by_role("row", name=name)).to_have_count(0)
    assert name not in profiles_by_name(base)
    assert name not in {p["name"] for p in call(base, "GET", "/api/profiles/trash")}

    step("create with the editor: custom SOCKS5 proxy, group, notes")
    page.goto(base + "/profiles/new")
    page.get_by_role("textbox", name="名称").fill("编辑器创建的环境")
    page.get_by_label("分组").select_option("冒烟测试组")
    page.get_by_label("备注").fill("由新编辑页创建")
    page.get_by_role("radiogroup", name="代理方式").get_by_role("radio", name="自定义代理").click()
    page.get_by_label("代理类型").select_option("socks5")
    page.get_by_placeholder("192.168.100.1").fill("203.0.113.77")
    page.get_by_placeholder("1090").fill("1080")
    page.get_by_label("代理账号").fill("smoke")
    page.get_by_label("代理密码").fill("p@ss word")
    page.get_by_role("button", name="创建").click()
    expect(page.get_by_role("complementary", name="编辑器创建的环境")).to_be_visible()
    made = profiles_by_name(base)["编辑器创建的环境"]
    assert made["proxy"] == "socks5://smoke:p%40ss%20word@203.0.113.77:1080", made["proxy"]
    assert made["group_name"] == "冒烟测试组" and made["notes"] == "由新编辑页创建"
    assert made["fingerprint_options"].get("storage_quota_mb") == 50000

    step("edit: leaving with changes asks first; Ctrl/Cmd+S saves")
    page.goto(base + f"/profiles/{made['id']}/edit")
    page.get_by_label("备注").fill("改过的备注")
    page.get_by_role("button", name="取消").click()
    page.get_by_role("dialog", name="放弃没保存的修改？").get_by_role("button", name="继续编辑").click()
    page.keyboard.press("ControlOrMeta+s")
    expect(page.get_by_role("complementary", name="编辑器创建的环境")).to_be_visible()
    assert profiles_by_name(base)["编辑器创建的环境"]["notes"] == "改过的备注"

    step("typing stays responsive with a large cookie field")
    big = "[" + ",".join(f'{{"name":"c{i}","value":"{"x" * 40}","domain":".example.com","path":"/"}}' for i in range(400)) + "]"
    page.goto(base + f"/profiles/{made['id']}/edit")
    page.get_by_placeholder("支持 JSON、Netscape", exact=False).fill(big)
    name = page.get_by_role("textbox", name="名称")
    name.click()
    name.press("End")
    per_key = page.evaluate("""async () => {
      const input = document.activeElement;
      const samples = [];
      for (let i = 0; i < 30; i += 1) {
        const start = performance.now();
        input.dispatchEvent(new KeyboardEvent("keydown", { key: "a", bubbles: true }));
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
        setter.call(input, input.value + "a");
        input.dispatchEvent(new Event("input", { bubbles: true }));
        await new Promise((resolve) => requestAnimationFrame(() => resolve()));
        samples.push(performance.now() - start);
      }
      samples.sort((a, b) => a - b);
      return { median: samples[15], worst: samples[29] };
    }""")
    print(f"    keystroke to next frame: median {per_key['median']:.1f} ms, worst {per_key['worst']:.1f} ms")
    assert per_key["median"] < 50, per_key
    page.get_by_role("button", name="取消").click()
    page.get_by_role("dialog", name="放弃没保存的修改？").get_by_role("button", name="放弃修改").click()

    step("proxies: add one, add a batch, delete one")
    page.goto(base + "/proxies")
    page.get_by_label("代理名称").fill("冒烟 SOCKS5")
    page.get_by_placeholder("192.168.100.1 或 proxy.example.com").fill("203.0.113.88")
    page.get_by_placeholder("1090").fill("1080")
    page.get_by_role("button", name="保存代理").click()
    expect(page.get_by_role("row", name="冒烟 SOCKS5")).to_be_visible()
    page.get_by_role("tab", name="批量导入").click()
    page.get_by_label("批量代理").fill("198.51.100.20:8000\nsocks5://u:p@198.51.100.21:1080\n乱写的一行")
    expect(page.get_by_text("1 行无法识别，会跳过")).to_be_visible()
    page.get_by_role("button", name="保存 2 个代理").click()
    expect(page.get_by_role("row", name="SOCKS5 198.51.100.21:1080")).to_be_visible()
    names = {p["name"] for p in call(base, "GET", "/api/proxy-presets")}
    assert {"冒烟 SOCKS5", "SOCKS5 198.51.100.20:8000", "SOCKS5 198.51.100.21:1080"} <= names, names
    page.get_by_role("button", name="删除「冒烟 SOCKS5」").click()
    page.get_by_role("dialog").get_by_role("button", name="删除").click()
    expect(page.get_by_role("row", name="冒烟 SOCKS5")).to_have_count(0)

    step("data: full backup is created and downloaded")
    page.goto(base + "/data")
    with page.expect_download(timeout=120_000) as download:
        page.get_by_role("button", name="立即完整备份").click()
    assert download.value.suggested_filename.endswith(".zip"), download.value.suggested_filename
    expect(page.get_by_text("完整备份已生成", exact=False).first).to_be_visible()
    full = [b for b in call(base, "GET", "/api/backups")["backups"] if b["kind"] == "full"]
    assert full, "no full backup listed"

    step("data: delete a profile after the backup, then restore the backup brings it back")
    victim = profiles_by_name(base)["Google Ads 测试"]
    call(base, "DELETE", f"/api/profiles/{victim['id']}")
    call(base, "DELETE", f"/api/profiles/{victim['id']}/purge")
    assert "Google Ads 测试" not in profiles_by_name(base)
    page.reload()
    page.get_by_role("button", name=f"恢复到 {full[0]['name']}").click()
    page.get_by_role("dialog", name="恢复这个完整备份？").get_by_role("button", name="恢复").click()
    expect(page.get_by_text("原来的数据保存在", exact=False).first).to_be_visible(timeout=120_000)
    assert "Google Ads 测试" in profiles_by_name(base)

    step("data: automatic backup settings and a run now")
    page.get_by_label("备份频率").select_option("3")
    page.get_by_role("button", name="保存设置").click()
    expect(page.get_by_text("自动备份设置已保存。")).to_be_visible()
    assert call(base, "GET", "/api/backups/auto")["interval_days"] == 3
    page.get_by_role("button", name="立即备份一次").click()
    expect(page.get_by_text("已备份：", exact=False).first).to_be_visible(timeout=120_000)

    step("data: configuration export, then import adds the profiles again")
    with page.expect_download() as download:
        page.get_by_role("button", name="下载配置备份").click()
    exported = download.value.path()
    before = len(call(base, "GET", "/api/profiles"))
    page.locator('input[type="file"][accept*="json"]').set_input_files(exported)
    expect(page.get_by_text("配置已导入").first).to_be_visible()
    assert len(call(base, "GET", "/api/profiles")) > before

    step("trash: restore one, delete one for good")
    first, second = list(profiles_by_name(base).values())[:2]
    call(base, "DELETE", f"/api/profiles/{first['id']}")
    call(base, "DELETE", f"/api/profiles/{second['id']}")
    page.goto(base + "/data/trash")
    page.get_by_role("button", name=f"恢复「{first['name']}」").click()
    expect(page.get_by_text(f"已恢复「{first['name']}」")).to_be_visible()
    page.get_by_role("button", name=f"彻底删除「{second['name']}」").click()
    page.get_by_role("dialog").get_by_role("button", name="彻底删除").click()
    expect(page.get_by_role("button", name=f"彻底删除「{second['name']}」")).to_have_count(0)
    assert first["id"] in {p["id"] for p in call(base, "GET", "/api/profiles")}
    assert second["id"] not in {p["id"] for p in call(base, "GET", "/api/profiles/trash")}

    step("checks: reports start empty; evolution switch saves; linkability analyses saved profiles")
    page.goto(base + "/checks")
    expect(page.get_by_text("还没有检测报告")).to_be_visible()
    expect(page.get_by_role("button", name="开始检测")).to_be_enabled()
    page.goto(base + "/checks/evolution")
    expect(page.get_by_label("进化的环境")).not_to_have_value("")
    target = page.get_by_label("进化的环境").input_value()
    page.get_by_role("switch", name="自动进化").click()
    expect(page.get_by_role("switch", name="自动进化")).to_be_checked()
    page.wait_for_timeout(500)
    assert {p["id"]: p for p in call(base, "GET", "/api/profiles")}[target]["evolution_enabled"] is True
    page.goto(base + "/checks/links")
    expect(page.get_by_text("个环境", exact=False).first).to_be_visible()
    analysis = call(base, "GET", "/api/linkability")
    assert analysis["profile_count"] == len(call(base, "GET", "/api/profiles")), analysis["profile_count"]

    step("settings: automation hours, AI endpoint (key write-only), kernel update policy")
    page.goto(base + "/settings/automation")
    page.get_by_label("允许的时段").fill("09-18")
    page.get_by_role("button", name="保存", exact=True).click()
    expect(page.get_by_text("自动化时段已设为 09-18")).to_be_visible()
    assert call(base, "GET", "/api/automation/hours")["hours"] == "09-18"
    page.get_by_label("允许的时段").fill("bad")
    page.get_by_role("button", name="保存", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="HH")).to_be_visible()
    assert call(base, "GET", "/api/automation/hours")["hours"] == "09-18"
    page.get_by_label("允许的时段").fill("")
    page.get_by_role("button", name="保存", exact=True).click()
    expect(page.get_by_text("已取消自动化时段限制")).to_be_visible()
    assert call(base, "GET", "/api/automation/hours")["hours"] is None

    page.goto(base + "/settings/ai")
    page.get_by_label("接口地址").fill("http://127.0.0.1:9/v1")
    page.get_by_label("模型", exact=True).fill("smoke-model")
    page.get_by_label("API 密钥").fill("sk-smoke-test-value")
    page.get_by_role("button", name="保存设置").click()
    expect(page.get_by_text("已配置，AI 功能可用。")).to_be_visible()
    expect(page.get_by_label("API 密钥")).to_have_value("")
    llm = call(base, "GET", "/api/settings/llm")
    assert llm["configured"] and llm["has_api_key"] and llm["model"] == "smoke-model", llm
    assert "sk-smoke-test-value" not in str(llm)

    page.goto(base + "/settings/kernel")
    page.get_by_role("switch", name="启动浏览器时自动下载新内核").click()
    page.get_by_role("button", name="保存设置").click()
    expect(page.get_by_text("内核设置已保存")).to_be_visible()
    assert call(base, "GET", "/api/kernel")["settings"]["auto_update"] is False

    page.goto(base + "/settings/about")
    expect(page.get_by_text("源码版（Git 安装）")).to_be_visible()
    # 拉取更新 would run git pull in this checkout, so it is not clicked here.
    expect(page.get_by_role("button", name="拉取更新")).to_be_enabled()

    step("cutover: old /next/ links redirect; the old panel is one click away and one click back")
    page.goto(base + "/next/settings/about?x=1")
    expect(page.get_by_role("heading", name="界面版本")).to_be_visible()
    assert page.url == base + "/settings/about?x=1", page.url
    page.get_by_role("button", name="切换回旧版界面").click()
    page.get_by_role("dialog").get_by_role("button", name="切换").click()
    expect(page.get_by_role("button", name="试用新界面")).to_be_visible()
    assert page.url == base + "/legacy/", page.url
    assert call(base, "GET", "/api/settings/ui")["interface"] == "legacy"
    # "/" now opens the old panel too, which is what the app window loads on the next start.
    page.goto(base + "/")
    expect(page.get_by_role("button", name="试用新界面")).to_be_visible()
    page.get_by_role("button", name="试用新界面").click()
    expect(page.get_by_role("navigation", name="页面")).to_be_visible()
    assert call(base, "GET", "/api/settings/ui")["interface"] == "new"
    page.goto(base + "/")
    expect(page.get_by_role("navigation", name="页面")).to_be_visible()

    step("preflight opens and cancels without launching")
    page.goto(base + "/profiles")
    page.get_by_role("button", name="打开「Etsy UK」").first.click()
    page.get_by_role("dialog", name="打开前检查").get_by_role("button", name="取消").click()
    assert profiles_by_name(base)["Etsy UK"]["status"] != "running"


def run_login(browser) -> None:
    """Sign-in, password change and sign-out against a second Manager that has a password."""
    step("login: wrong password refused, right one signs in; change password; sign out; sign in with the new one")
    first, second = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = start_server(port, {"ADMIN_USERNAME": "smoke", "ADMIN_PASSWORD": first})
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 800}, locale="zh-CN")
        page.goto(base + "/profiles")
        expect(page.get_by_label("用户名")).to_have_value("smoke")
        page.get_by_label("密码").fill("not-the-password")
        page.get_by_role("button", name="登录").click()
        expect(page.get_by_text("用户名或密码错误")).to_be_visible()
        page.get_by_label("密码").fill(first)
        page.get_by_role("button", name="登录").click()
        expect(page.get_by_role("navigation", name="页面")).to_be_visible()

        page.goto(base + "/settings/account")
        page.get_by_label("当前密码").fill(first)
        page.get_by_label("新密码", exact=True).fill(second)
        page.get_by_label("确认新密码").fill(second)
        page.get_by_role("button", name="保存", exact=True).click()
        expect(page.get_by_text("用户名和密码已保存")).to_be_visible()

        page.get_by_role("button", name="退出登录").click()
        expect(page.get_by_text("输入管理员账号和密码")).to_be_visible()
        page.reload()
        expect(page.get_by_text("输入管理员账号和密码")).to_be_visible()
        page.get_by_label("密码").fill(first)
        page.get_by_role("button", name="登录").click()
        expect(page.get_by_text("用户名或密码错误")).to_be_visible()
        page.get_by_label("密码").fill(second)
        page.get_by_role("button", name="登录").click()
        expect(page.get_by_role("navigation", name="页面")).to_be_visible()
        page.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        print("frontend/dist is missing: run `npm run build` in frontend/ first", file=sys.stderr)
        return 1
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = start_server(port)
    errors: list[str] = []
    try:
        seed(base)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            expect.set_options(timeout=10_000)
            run(page, base)
            run_login(browser)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    if errors:
        print("page errors:", errors, file=sys.stderr)
        return 1
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
