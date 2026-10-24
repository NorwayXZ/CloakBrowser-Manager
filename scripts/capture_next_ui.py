"""Screenshot the redesigned panel (/next/) and check its layout.

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
from capture_baseline_ui import ROOT, free_port, seed, start_server  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "next-screenshots"
SIZES = [(900, 640), (1024, 680), (1280, 800), (1600, 1000)]
THEMES = ["light", "dark"]

LAYOUT_CHECK = """
() => {
  const faults = [];
  const vw = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > vw + 1) faults.push(`page scrolls sideways (${document.documentElement.scrollWidth} > ${vw})`);
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


def screens(page: Page, base: str):
    def go(path: str, ready: str):
        def run():
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

    yield "01-profiles-placeholder", go("/next/profiles", "text=这一页正在重做"), False
    yield "02-settings-appearance", go("/next/settings", "text=主题"), False
    yield "03-settings-placeholder", go("/next/settings/kernel", "text=正在重做"), False
    yield "04-running-popover", with_action("/next/settings", "text=主题",
                                            lambda: page.get_by_role("button", name="未运行").click()), False
    yield "05-theme-menu", with_action("/next/settings", "text=主题",
                                       lambda: page.get_by_role("button", name="外观：跟随系统").click()), False
    yield "06-shortcuts", with_action("/next/settings", "text=主题", lambda: page.keyboard.press("Shift+Slash")), False
    yield "07-gallery", go("/next/__ui", "text=组件展示"), True
    yield "08-confirm-dialog", with_action("/next/__ui", "text=组件展示",
                                           lambda: page.get_by_role("button", name="确认对话框").click()), False
    yield "09-not-found", go("/next/whatever", "text=没有这个页面"), False


def main() -> int:
    if not (ROOT / "frontend" / "dist" / "next" / "index.html").exists():
        print("frontend/dist/next is missing: run `npm run build` in frontend/ first", file=sys.stderr)
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
