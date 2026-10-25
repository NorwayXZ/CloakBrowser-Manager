"""Does driving a profile as an AI agent leave traces a page can see?

Regression check for the agent tools. It serves a small local probe page,
opens a profile with ``open_browser``, sends it to that page with
``browser_navigate`` (the same path an agent uses) and prints what the page
itself could observe: ``navigator.webdriver``, automation globals and headless
markers.

It also runs the old ``console.debug(error)`` stack-getter trick for "a
DevTools client has Runtime enabled". That trick is inert on current Chrome: a
positive control (explicit ``Runtime.enable`` on Chrome 155) still reports
false, so a false there proves nothing. It stays in the output for older
Chrome builds only.

With ``--external-cdp`` it then attaches a second client the way a Playwright
based agent would and probes again, so you can see what that adds.

The script reports; it does not judge. Compare the output with
``get_fingerprint_report`` / ``run_site_check`` for the same profile and keep
it for before/after comparisons when you change the agent layer. Needs a
running Manager in ``mcp.mode=automation``. Example:

    .venv/bin/python scripts/agent_cdp_check.py --profile "my profile"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.cli import Cli  # noqa: E402

PROBE_PAGE = """<!doctype html><meta charset="utf-8"><title>probe</title><body>probe running</body>
<script>
function collect() {
  const r = {};
  r.webdriver = navigator.webdriver;
  r.hasChromeObject = !!window.chrome;
  r.pluginCount = navigator.plugins.length;
  r.languages = Array.from(navigator.languages || []);
  r.userAgent = navigator.userAgent;
  r.headlessUserAgent = /HeadlessChrome/.test(navigator.userAgent);
  r.automationGlobals = Object.getOwnPropertyNames(window).filter(
    (k) => /^(cdc_|\\$cdc_|__playwright|__pw_|__nightmare|_phantom|callPhantom|__selenium|__webdriver|domAutomation)/.test(k));
  let leaked = false;
  const err = new Error('probe');
  Object.defineProperty(err, 'stack', { get() { leaked = true; return 'probe'; } });
  console.debug(err);
  r.runtimeEnableStackTrick = leaked;
  return r;
}
setTimeout(() => {
  fetch('/report?tag=' + encodeURIComponent(location.hash.slice(1)), {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(collect()),
  });
}, 600);
</script>"""


class _Handler(BaseHTTPRequestHandler):
    reports: dict[str, dict] = {}

    def log_message(self, *args) -> None:  # quiet
        pass

    def do_GET(self) -> None:
        body = PROBE_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        data = json.loads(self.rfile.read(length) or b"{}")
        tag = self.path.split("tag=", 1)[-1] or "default"
        _Handler.reports[tag] = data
        self.send_response(204)
        self.end_headers()


async def wait_for_report(tag: str, timeout: float = 15.0) -> dict | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if tag in _Handler.reports:
            return _Handler.reports[tag]
        await asyncio.sleep(0.2)
    return None


async def probe_via_tools(cli: Cli, profile: str, base: str, tag: str) -> dict | None:
    nav = await cli.tool("browser_navigate", {"profile": profile, "url": f"{base}/#{tag}"})
    if not nav.get("ok"):
        raise SystemExit(f"browser_navigate 失败：{nav.get('reason')} — {nav.get('detail')}")
    return await wait_for_report(tag)


async def probe_with_external_client(endpoint: str, base: str, tag: str) -> dict | None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(endpoint)
        try:
            context = browser.contexts[0]
            page = await context.new_page()
            await page.goto(f"{base}/#{tag}")
            report = await wait_for_report(tag)
            await page.close()
            return report
        finally:
            await browser.close()


SIGNALS = ("webdriver", "automationGlobals", "headlessUserAgent", "runtimeEnableStackTrick")


def summarize(report: dict | None) -> dict:
    if report is None:
        return {"error": "页面没有回报（被拦截或加载失败）"}
    return {key: report.get(key) for key in (*SIGNALS, "hasChromeObject", "pluginCount", "languages")}


async def main_async(args: argparse.Namespace) -> int:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    cli = Cli()
    opened = await cli.tool("open_browser", {"profile": args.profile})
    if not opened.get("ok"):
        print(f"open_browser 失败：{opened.get('reason')} — {opened.get('detail')}", file=sys.stderr)
        if opened.get("next_step"):
            print(f"下一步：{opened['next_step']}", file=sys.stderr)
        return 1
    result: dict = {"profile": args.profile, "probe_page": base}
    try:
        result["via_agent_tools"] = summarize(await probe_via_tools(cli, args.profile, base, "tools"))
        if args.external_cdp:
            result["via_external_cdp_client"] = summarize(
                await probe_with_external_client(opened["cdp_http_endpoint"], base, "external")
            )
    finally:
        if not args.keep:
            await cli.tool("stop_profile", {"profile_id": opened["profile_id"]})
        server.shutdown()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    flagged = [
        f"{name}.{key}"
        for name in ("via_agent_tools", "via_external_cdp_client")
        for key in ("webdriver", "headlessUserAgent")
        if result.get(name, {}).get(key) is True
    ] + [
        f"{name}.automationGlobals"
        for name in ("via_agent_tools", "via_external_cdp_client")
        if result.get(name, {}).get("automationGlobals")
    ]
    if flagged:
        print(f"\n页面能直接看到的自动化痕迹：{', '.join(flagged)}", file=sys.stderr)
        return 1
    print(
        "\n没有发现 webdriver / 自动化全局变量 / HeadlessChrome。"
        "注意：runtimeEnableStackTrick 在当前 Chrome 上不会触发（加了显式 Runtime.enable 的对照实验也是 false），"
        "它为 false 不代表页面看不到 DevTools 客户端。",
        file=sys.stderr,
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--profile", required=True, help="画像 id 或名称")
    parser.add_argument("--external-cdp", action="store_true", help="再用一个外部 Playwright 客户端探测一遍")
    parser.add_argument("--keep", action="store_true", help="测完不关闭画像")
    raise SystemExit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
