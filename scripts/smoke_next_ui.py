"""End-to-end smoke test of the redesigned panel against a real Manager.

Starts its own Manager on a free port with a throwaway data directory (same
isolation as capture_baseline_ui.py), drives /next/ with Playwright's Chromium,
and checks each result through the API. It never launches a browser profile:
that needs the real kernel and a license seat, and stays a manual check.

    python scripts/smoke_next_ui.py
"""

from __future__ import annotations

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
    page.goto(base + "/next/profiles")
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
    panel.get_by_role("button", name="焚毁").click()
    page.get_by_role("dialog", name=f"焚毁「{name}」？").get_by_role("button", name="焚毁").click()
    expect(page.get_by_role("row", name=name)).to_have_count(0)
    assert name not in profiles_by_name(base)
    assert name not in {p["name"] for p in call(base, "GET", "/api/profiles/trash")}

    step("create with the editor: custom SOCKS5 proxy, group, notes")
    page.goto(base + "/next/profiles/new")
    page.get_by_role("textbox", name="名称").fill("编辑器创建的环境")
    page.get_by_label("分组").select_option("冒烟测试组")
    page.get_by_role("radiogroup", name="代理方式").get_by_role("radio", name="自定义代理").click()
    page.get_by_label("代理类型").select_option("socks5")
    page.get_by_placeholder("192.168.100.1").fill("203.0.113.77")
    page.get_by_placeholder("1090").fill("1080")
    page.get_by_label("代理账号").fill("smoke")
    page.get_by_label("代理密码").fill("p@ss word")
    page.get_by_label("备注").fill("由新编辑页创建")
    page.get_by_role("button", name="创建").click()
    expect(page.get_by_role("complementary", name="编辑器创建的环境")).to_be_visible()
    made = profiles_by_name(base)["编辑器创建的环境"]
    assert made["proxy"] == "socks5://smoke:p%40ss%20word@203.0.113.77:1080", made["proxy"]
    assert made["group_name"] == "冒烟测试组" and made["notes"] == "由新编辑页创建"
    assert made["fingerprint_options"].get("storage_quota_mb") == 50000

    step("edit: leaving with changes asks first; Ctrl/Cmd+S saves")
    page.goto(base + f"/next/profiles/{made['id']}/edit")
    page.get_by_label("备注").fill("改过的备注")
    page.get_by_role("button", name="取消").click()
    page.get_by_role("dialog", name="放弃没保存的修改？").get_by_role("button", name="继续编辑").click()
    page.keyboard.press("ControlOrMeta+s")
    expect(page.get_by_role("complementary", name="编辑器创建的环境")).to_be_visible()
    assert profiles_by_name(base)["编辑器创建的环境"]["notes"] == "改过的备注"

    step("typing stays responsive with a large cookie field")
    big = "[" + ",".join(f'{{"name":"c{i}","value":"{"x" * 40}","domain":".example.com","path":"/"}}' for i in range(400)) + "]"
    page.goto(base + f"/next/profiles/{made['id']}/edit")
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

    step("preflight opens and cancels without launching")
    page.goto(base + "/next/profiles")
    page.get_by_role("button", name="打开「Etsy UK」").click()
    page.get_by_role("dialog", name="启动前检查").get_by_role("button", name="取消").click()
    assert profiles_by_name(base)["Etsy UK"]["status"] != "running"


def main() -> int:
    if not (ROOT / "frontend" / "dist" / "next" / "index.html").exists():
        print("frontend/dist/next is missing: run `npm run build` in frontend/ first", file=sys.stderr)
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
