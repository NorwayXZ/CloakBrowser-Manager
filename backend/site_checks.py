"""Run a profile through public fingerprint-detection sites and keep a report.

The bar for "done" is what independent detectors say, not our own probe. The
check opens each site in the profile (debug launch, so the Manager can drive
it), waits until the site shows its verdict, saves a screenshot and judges
the verdict with the rules below. Pages only collect text and a few element
counts; every decision is made in Python so it can be tested.

Sites change their wording; when a verdict cannot be read the check reports
"unknown" with a screenshot instead of guessing.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

REPORTS_DIRNAME = "check-reports"
REPORT_FILE = "report.json"
POLL_SECONDS = 2.0

TEXT_JS = "document.body ? document.body.innerText.slice(0, 40000) : ''"
SANNYSOFT_JS = """({
  text: document.body ? document.body.innerText.slice(0, 40000) : '',
  passed: document.querySelectorAll('td.passed').length,
  failed: document.querySelectorAll('td.failed').length,
  warn: document.querySelectorAll('td.warn').length,
})"""
IPHEY_JS = """({
  text: document.body ? document.body.innerText.slice(0, 40000) : '',
  flagged: [...document.querySelectorAll('.code-block--error h4')].map(e => e.innerText.trim()),
  signals: (document.getElementById('signals') || {}).innerText || '',
  diag: (() => {
    const h = [...document.querySelectorAll('h1')].find(e => e.innerText.includes('Digital Identity'));
    return h ? (h.parentElement || h).outerHTML.slice(0, 1500) : 'no heading found';
  })(),
})"""
CREEPJS_JS = """({
  text: document.body ? document.body.innerText.slice(0, 40000) : '',
  lies: document.querySelectorAll('.lies').length,
  lieTexts: [...document.querySelectorAll('.lies')].slice(0, 12).map(el => {
    const box = el.closest('div') || el;
    return (box.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 160);
  }),
})"""


@dataclass(frozen=True)
class SiteCheck:
    id: str
    name: str
    url: str
    criteria: str
    collect_js: str = TEXT_JS
    timeout: float = 60.0
    # Scores settle a few seconds after the first verdict appears.
    min_wait: float = 8.0


SITES: tuple[SiteCheck, ...] = (
    SiteCheck("creepjs", "CreepJS", "https://abrahamjuliot.github.io/creepjs/",
              "没有 lies，headless 0%，stealth 0%", CREEPJS_JS, 75.0, min_wait=10.0),
    SiteCheck("pixelscan", "Pixelscan", "https://pixelscan.net/fingerprint-check",
              "指纹一致、未检测到伪装、未检测到自动化"),
    SiteCheck("browserscan", "BrowserScan", "https://www.browserscan.net/",
              "真实度 100%（90–99% 记为警告），未检测到机器人"),
    SiteCheck("sannysoft", "Sannysoft", "https://bot.sannysoft.com/",
              "没有任何失败项", SANNYSOFT_JS, 45.0),
    SiteCheck("iphey", "IPHey", "https://iphey.com/",
              "结论为 Trustworthy（可信）", IPHEY_JS, timeout=150.0),
    SiteCheck("browserleaks_webrtc", "BrowserLeaks WebRTC", "https://browserleaks.com/webrtc",
              "WebRTC 没有泄漏 IP", timeout=45.0),
    SiteCheck("fingerprint", "Fingerprint.com", "https://demo.fingerprint.com/playground",
              "不是机器人、未篡改、不是反检测浏览器、不是虚拟机；IP 没被认出是代理/VPN", timeout=75.0),
)
SITES_BY_ID = {site.id: site for site in SITES}


@dataclass
class CheckResult:
    site: str
    name: str
    url: str
    criteria: str
    status: str  # pass | warn | fail | unknown | error
    summary: str
    details: list[str] = field(default_factory=list)
    screenshot: str | None = None
    seconds: float = 0.0
    # "site" for the public detection sites, "local" for the Manager's own
    # probe items folded into the same report.
    source: str = "site"
    # Set on items whose verdict depends on the egress IP's reputation.
    ip_note: str | None = None


# Verdicts that say as much about the egress IP as about the browser: a
# datacenter or proxy-pool address gets flagged even when every browser
# signal is clean (the scorecard practice is to annotate, not to hide).
IP_RESULT_NOTE = (
    "这一项的结论受出口 IP 信誉影响：机房或代理池 IP 常被标记，"
    "与浏览器指纹本身无关；换住宅 IP 后结果可能不同。"
)
IP_DEPENDENT_SITES = frozenset({"fingerprint", "iphey", "pixelscan"})


def status_counts(results: list[Any]) -> dict[str, int]:
    """pass/warn/fail/unknown/error tallies over CheckResults or dicts."""
    counts = {"pass": 0, "warn": 0, "fail": 0, "unknown": 0, "error": 0}
    for result in results:
        status = result.get("status") if isinstance(result, dict) else getattr(result, "status", None)
        if status in counts:
            counts[status] += 1
    counts["total"] = len(results)
    return counts


def egress_note(environment: dict[str, Any] | None) -> str:
    """The report-level egress caveat, mirroring the scorecard's annotation."""
    env = environment or {}
    ip = env.get("exit_ip")
    proxy_type = env.get("proxy_type") or "direct"
    if ip:
        where = f"{proxy_type} 出口 {ip}"
        country = env.get("exit_country")
        if country:
            where += f"（{country}）"
    else:
        where = "未取到出口 IP"
    return (
        f"本次{where}。标注「IP 信誉」的条目结论受出口 IP 影响："
        "机房或代理池 IP 常被检测站标记，与浏览器指纹本身无关，换住宅 IP 后结果可能不同。"
    )


Verdict = tuple[str, str, list[str]]


def _text(raw: Any) -> str:
    return str(raw.get("text", "") if isinstance(raw, dict) else raw or "")


def _percent(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, re.I)
    return int(match.group(1)) if match else None


# ── Verdict rules: None means "not shown yet, keep waiting" ─────────────────


def judge_creepjs(raw: Any) -> Verdict | None:
    text = _text(raw)
    like = _percent(r"(\d+)%\s*like headless", text)
    headless = _percent(r"(\d+)%\s*headless(?!\w)", re.sub(r"\d+%\s*like headless", "", text, flags=re.I))
    stealth = _percent(r"(\d+)%\s*stealth", text)
    if headless is None or stealth is None:
        return None
    lies = int(raw.get("lies", 0)) if isinstance(raw, dict) else 0
    details = [f"lies：{lies} 处", f"headless：{headless}%", f"stealth：{stealth}%", f"像 headless：{like}%"]
    if isinstance(raw, dict):
        for item in raw.get("lieTexts") or []:
            item = str(item).strip()
            if item:
                details.append(f"lie 明细：{item}")
    problems = []
    if lies:
        problems.append(f"{lies} 处 lies")
    if headless:
        problems.append(f"headless {headless}%")
    if stealth:
        problems.append(f"stealth {stealth}%")
    if problems:
        return "fail", "检测到：" + "、".join(problems), details
    return "pass", "没有 lies，headless 0%，stealth 0%", details


def judge_pixelscan(raw: Any) -> Verdict | None:
    text = _text(raw)
    match = re.search(r"Fingerprint is (inconsistent|consistent)", text, re.I)
    if not match:
        return None
    consistent = match.group(1).lower() == "consistent"
    masking = bool(re.search(r"(?<!No )Masking detected", text))
    automated = bool(re.search(r"(?<!No )automated behavior detected", text, re.I))
    proxy = "Proxy detected" in text and "No proxy detected" not in text
    details = [
        f"指纹：{'一致' if consistent else '不一致'}",
        f"伪装：{'检测到' if masking else '未检测到'}",
        f"自动化：{'检测到' if automated else '未检测到'}",
        f"代理：{'检测到' if proxy else '未检测到'}（不计入结论）",
    ]
    problems = [p for p, bad in (("指纹不一致", not consistent), ("检测到伪装", masking), ("检测到自动化", automated)) if bad]
    if problems:
        return "fail", "、".join(problems), details
    return "pass", "指纹一致，未检测到伪装和自动化", details


def judge_browserscan(raw: Any) -> Verdict | None:
    text = _text(raw)
    score = _percent(r"authenticity:\s*(\d+)%", text)
    if score is None:
        return None
    bot = re.search(r"Bot Detection:\s*(Yes|No)", text, re.I)
    deductions = [f"{m.group(1).strip()} {m.group(2)}" for m in re.finditer(r"\n([^\n%]{3,60})\n\s*(-\d+%)", text)]
    details = [f"真实度：{score}%", f"机器人检测：{bot.group(1) if bot else '未显示'}", *[f"扣分：{d}" for d in deductions]]
    if bot and bot.group(1).lower() == "yes":
        return "fail", f"检测到机器人，真实度 {score}%", details
    if score >= 100:
        return "pass", "真实度 100%", details
    if score >= 90:
        return "warn", f"真实度 {score}%", details
    return "fail", f"真实度只有 {score}%", details


def judge_sannysoft(raw: Any) -> Verdict | None:
    if not isinstance(raw, dict):
        return None
    passed, failed, warn = int(raw.get("passed", 0)), int(raw.get("failed", 0)), int(raw.get("warn", 0))
    if passed + failed + warn < 10:
        return None
    details = [f"通过 {passed} 项", f"失败 {failed} 项", f"警告 {warn} 项"]
    if failed:
        return "fail", f"{failed} 项失败", details
    if warn:
        return "warn", f"{warn} 项警告", details
    return "pass", f"{passed} 项全部通过", details


def judge_iphey(raw: Any) -> Verdict | None:
    text = _text(raw)
    match = re.search(r"Looks\s*\n?\s*(Trustworthy|Unreliable|Suspicious)", text, re.I)
    if not match:
        return None
    verdict = match.group(1).capitalize()
    score = re.search(r"\n(\d{1,3})\s*\n\s*MX SCORE", text)
    sections: dict[str, str] = {}
    for m in re.finditer(r"\n(BROWSER|LOCATION|IP ADDRESS|HARDWARE|SOFTWARE)\s*\n+\s*([^\n]+)", text):
        sections.setdefault(m.group(1).title(), m.group(2).strip())  # the summary card comes first
    details = [f"结论：{verdict}", *([f"MX 分数：{score.group(1)}"] if score else []),
               *(f"{label}：{value}" for label, value in sections.items())]
    if isinstance(raw, dict):
        flagged = [str(t) for t in raw.get("flagged") or []]
        if flagged:
            details.append("标红的项目：" + "、".join(flagged))
        signals = [line.strip() for line in str(raw.get("signals") or "").splitlines()
                   if line.strip() and line.strip().upper() != "SIGNALS"]
        # The section alternates "Browser" / "Detected …" lines.
        details.extend(f"原因：{line}" for line in signals if line.lower().startswith(("detected", "your", "we ")))
    if verdict == "Trustworthy":
        return "pass", "Trustworthy（可信）", details
    return "fail", f"{verdict}（{'不可靠' if verdict == 'Unreliable' else '可疑'}）", details


def judge_browserleaks_webrtc(raw: Any) -> Verdict | None:
    text = _text(raw)
    match = re.search(r"WebRTC Leak Test\s*\n?\s*[✔✘✖!?]?\s*\n?\s*(No Leak|Leak[^\n]*)", text)
    if not match:
        return None
    public = re.search(r"Public IP Address\s*\n?\s*([^\n]+)", text)
    local = re.search(r"Local IP Address\s*\n?\s*([^\n]+)", text)
    details = [f"结果：{match.group(1).strip()}",
               f"WebRTC 公网 IP：{public.group(1).strip() if public else '-'}",
               f"WebRTC 内网 IP：{local.group(1).strip() if local else '-'}"]
    if match.group(1).strip() == "No Leak":
        return "pass", "WebRTC 没有泄漏", details
    return "fail", f"WebRTC 泄漏：{match.group(1).strip()}", details


def _fp_value(text: str, key: str) -> str | None:
    match = re.search(rf"\b{key}:\s*\"?([\w.]+)\"?", text)
    return match.group(1) if match else None


def judge_fingerprint(raw: Any) -> Verdict | None:
    text = _text(raw)
    if "suspect_score:" not in text:
        return None
    bot = _fp_value(text, "bot")
    tampering = _fp_value(text, "tampering")
    anti_detect = _fp_value(text, "anti_detect_browser")
    vm = _fp_value(text, "virtual_machine")
    devtools = _fp_value(text, "developer_tools")
    suspect = _fp_value(text, "suspect_score")
    vpn = re.search(r"\nVPN\s*\n+\s*([^\n]+)", text)
    proxy_line = re.search(r"\nProxy Detection\s*\n+\s*([^\n]+)", text)
    details = [
        f"机器人：{bot}", f"篡改：{tampering}", f"反检测浏览器：{anti_detect or 'false'}",
        f"虚拟机：{vm or '未显示'}", f"开发者工具：{devtools}", f"可疑分数：{suspect}",
        f"VPN：{vpn.group(1).strip() if vpn else '未显示'}",
        f"代理检测：{proxy_line.group(1).strip() if proxy_line else '未显示'}",
    ]
    # The IP's reputation, separate from the browser: a known proxy or VPN
    # address tells a site a proxy is in use even when the browser passes.
    ip_flags = []
    if _fp_value(text, "proxy") == "true":
        kind = _fp_value(text, "proxy_type") or "未知类型"
        provider = _fp_value(text, "provider")
        confidence = _fp_value(text, "proxy_confidence") or "未知"
        ip_flags.append(f"代理 IP（{kind}{'，' + provider if provider else ''}，置信度 {confidence}）")
    if _fp_value(text, "vpn") == "true":
        methods = [
            name for name in ("public_vpn", "relay", "auxiliary_mobile", "timezone_mismatch", "os_mismatch")
            if _fp_value(text, name) == "true"
        ]
        ip_flags.append(f"VPN（{'、'.join(methods) or _fp_value(text, 'vpn_confidence') or '原因未显示'}）")
    problems = []
    if bot and bot != "not_detected":
        problems.append(f"机器人（{bot}）")
    if tampering == "true":
        problems.append("浏览器篡改")
    if anti_detect == "true":
        problems.append("识别为反检测浏览器")
    if vm == "true":
        problems.append("虚拟机")
    if problems:
        return "fail", "检测到：" + "、".join(problems), details
    if ip_flags:
        return "warn", "浏览器没被认出，但 IP 被认出：" + "、".join(ip_flags), details
    return "pass", "不是机器人，未检测到篡改", details


JUDGES: dict[str, Callable[[Any], Verdict | None]] = {
    "creepjs": judge_creepjs,
    "pixelscan": judge_pixelscan,
    "browserscan": judge_browserscan,
    "sannysoft": judge_sannysoft,
    "iphey": judge_iphey,
    "browserleaks_webrtc": judge_browserleaks_webrtc,
    "fingerprint": judge_fingerprint,
}


def overall_status(results: list[CheckResult]) -> str:
    statuses = {r.status for r in results}
    if statuses & {"fail", "error", "unknown"}:
        return "fail"
    return "warn" if "warn" in statuses else "pass"


# ── The Manager's own probe, as report items ────────────────────────────────
#
# The one-click report combines the public sites with the local consistency
# probe (fingerprint_report.analyze_fingerprint): each probe signal becomes
# one report item, so the report shows UA/platform/GPU/timezone/... rows
# next to the site verdicts. An item's status is the worst severity the
# analysis recorded for its signals; issues it does not recognise land in
# the cross-scope consistency item.

_LOCAL_ITEM_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("local_user_agent", "UA（User-Agent）", ("userAgent", "ua_ua_ch_version", "navigator.userAgentData", "network.user_agent_header")),
    ("local_platform", "平台", ("platform", "navigator.userAgentData.platform", "scope_consistency.userAgentData.platform")),
    ("local_language", "语言", ("navigator.language", "navigator.languages", "Intl.", "network.accept_language", "scope_consistency.navigator.language", "scope_consistency.navigator.languages")),
    ("local_timezone", "时区", ("timezone", "scope_consistency.timezone")),
    ("local_screen", "屏幕", ("screen.", "window.outer")),
    ("local_cpu", "CPU 核数", ("hardwareConcurrency",)),
    ("local_memory", "内存", ("deviceMemory",)),
    ("local_gpu", "GPU / WebGL", ("webgl.",)),
    ("local_canvas", "Canvas 稳定性", ("canvas_stability",)),
    ("local_audio", "Audio 稳定性", ("audio_stability",)),
    ("local_fonts", "字体", ("fonts.",)),
    ("local_webrtc", "WebRTC 本地候选", ("webrtc.",)),
    ("local_egress_ip", "出口 IP", ("network.egress_ip", "network.external_probe")),
    ("local_webdriver", "webdriver 标记", ("navigator.webdriver",)),
    ("local_storage", "存储", ("storage.", "cookies")),
    ("local_native", "原生函数完整性", ("native_string.",)),
    ("local_scope", "跨作用域一致性", ("scope_consistency.", "scope_error", "probe_url")),
)
_LOCAL_FALLBACK_ITEM = "local_scope"
_LOCAL_ALWAYS_SHOWN = frozenset({
    "local_user_agent", "local_platform", "local_language", "local_timezone",
    "local_screen", "local_cpu", "local_memory", "local_gpu", "local_canvas",
    "local_audio", "local_fonts", "local_webrtc", "local_egress_ip", "local_webdriver",
})


def _local_item_for_signal(signal: str) -> str:
    """The report item a probe signal belongs to (longest prefix wins)."""
    best_item, best_length = _LOCAL_FALLBACK_ITEM, -1
    for item_id, _name, prefixes in _LOCAL_ITEM_SPECS:
        for prefix in prefixes:
            if (signal == prefix or signal.startswith(prefix)) and len(prefix) > best_length:
                best_item, best_length = item_id, len(prefix)
    return best_item


def _local_item_value(item_id: str, main: dict[str, Any], exit_ip: str | None) -> str | None:
    nav = main.get("navigator") if isinstance(main.get("navigator"), dict) else {}
    graphics = main.get("graphics") if isinstance(main.get("graphics"), dict) else {}
    if item_id == "local_user_agent":
        return str(nav["userAgent"]) if nav.get("userAgent") else None
    if item_id == "local_platform":
        return str(nav["platform"]) if nav.get("platform") else None
    if item_id == "local_language":
        languages = nav.get("languages")
        if nav.get("language"):
            suffix = f"（共 {len(languages)} 种）" if isinstance(languages, list) and len(languages) > 1 else ""
            return f"{nav['language']}{suffix}"
        return None
    if item_id == "local_timezone":
        date = main.get("date") if isinstance(main.get("date"), dict) else {}
        return str(date["timezone"]) if date.get("timezone") else None
    if item_id == "local_screen":
        screen = main.get("screen") if isinstance(main.get("screen"), dict) else {}
        if screen.get("width") and screen.get("height"):
            return f"{screen['width']}×{screen['height']}"
        return None
    if item_id == "local_cpu":
        return str(nav["hardwareConcurrency"]) if nav.get("hardwareConcurrency") else None
    if item_id == "local_memory":
        return f"{nav['deviceMemory']} GB" if nav.get("deviceMemory") else None
    if item_id == "local_gpu":
        webgl = graphics.get("webgl") if isinstance(graphics.get("webgl"), dict) else {}
        if webgl.get("renderer"):
            return f"{webgl.get('vendor') or ''} / {webgl['renderer']}".strip(" /")
        return None
    if item_id == "local_canvas":
        return f"哈希 {graphics['canvasHashA']}" if graphics.get("canvasHashA") else None
    if item_id == "local_audio":
        return f"哈希 {graphics['audioHashA']}" if graphics.get("audioHashA") else None
    if item_id == "local_fonts":
        fonts = main.get("fonts") if isinstance(main.get("fonts"), dict) else {}
        available = fonts.get("available")
        if isinstance(available, list):
            return f"可测字体：{'、'.join(map(str, available))}" if available else "候选字体均不可测"
        return None
    if item_id == "local_webrtc":
        network = main.get("network") if isinstance(main.get("network"), dict) else {}
        candidates = network.get("webrtcCandidates")
        if isinstance(candidates, list):
            return f"{len(candidates)} 个候选地址"
        return None
    if item_id == "local_egress_ip":
        return str(exit_ip) if exit_ip else None
    if item_id == "local_webdriver":
        return f"webdriver = {nav['webdriver']}" if "webdriver" in nav else None
    return None


def local_probe_results(
    analysis: dict[str, Any] | None,
    raw: dict[str, Any] | None,
    *,
    exit_ip: str | None = None,
) -> list[CheckResult]:
    """``analyze_fingerprint`` output (plus the raw probe values) as items."""
    analysis = analysis or {}
    raw = raw or {}
    main = raw.get("main") if isinstance(raw.get("main"), dict) else {}
    issues_by_item: dict[str, list[dict[str, Any]]] = {}
    for issue in analysis.get("issues") or []:
        if isinstance(issue, dict):
            issues_by_item.setdefault(_local_item_for_signal(str(issue.get("signal") or "")), []).append(issue)

    results: list[CheckResult] = []
    for item_id, name, _prefixes in _LOCAL_ITEM_SPECS:
        issues = issues_by_item.get(item_id, [])
        value = _local_item_value(item_id, main, exit_ip)
        if item_id not in _LOCAL_ALWAYS_SHOWN and not issues:
            continue
        if value is None and not issues:
            continue
        severities = {str(issue.get("severity")) for issue in issues}
        status = "fail" if "error" in severities else "warn" if "warning" in severities else "pass"
        details = []
        for issue in issues:
            scope = str(issue.get("scope") or "main")
            message = str(issue.get("message") or issue.get("signal") or "")
            details.append(message if scope == "main" else f"[{scope}] {message}")
        if issues:
            first = details[0]
            summary = first if len(details) == 1 else f"{first}（共 {len(details)} 个问题）"
        else:
            summary = value or "未检出问题"
            if item_id == "local_gpu":
                webgl = (main.get("graphics") or {}).get("webgl") or {}
                if isinstance(webgl, dict) and webgl.get("version"):
                    details.append(f"WebGL 版本：{webgl['version']}")
        results.append(CheckResult(
            site=item_id,
            name=name,
            url="",
            criteria="与画像配置一致" if item_id != "local_egress_ip" else "与画像代理出口一致",
            status=status,
            summary=summary,
            details=details,
            source="local",
            ip_note=IP_RESULT_NOTE if item_id == "local_egress_ip" else None,
        ))
    return results


# ── Running ─────────────────────────────────────────────────────────────────


Progress = Callable[[str, int, int, CheckResult | None], Awaitable[None] | None]


async def run_site(context: Any, site: SiteCheck, report_dir: Path, *, poll: float = POLL_SECONDS, human_factory: Any = None) -> CheckResult:
    started = time.monotonic()
    result = CheckResult(site.id, site.name, site.url, site.criteria, "unknown", "页面没有显示结论")
    page = None
    try:
        page = await context.new_page()
        await page.goto(site.url, timeout=int(site.timeout * 1000), wait_until="domcontentloaded")
        if human_factory is not None:
            # A few seconds of human presence (drift, a glance down the
            # page) so the check session does not look like an instant-load
            # robot. Hard-capped: behavior can never hang a check.
            try:
                human = human_factory(page)
                await asyncio.wait_for(human.settle(3.0), timeout=8)
            except Exception:
                pass
        verdict = None
        loaded = time.monotonic()
        previous = None
        last_raw: Any = None
        while time.monotonic() - started < site.timeout:
            last_raw = await page.evaluate(site.collect_js)
            current = JUDGES[site.id](last_raw)
            settled = time.monotonic() - loaded >= site.min_wait
            # Take a verdict once the page had time to finish scoring and two
            # reads in a row agree; otherwise keep the latest one seen.
            if current is not None:
                verdict = current
                if settled and previous is not None and previous[0] == current[0]:
                    break
            previous = current
            await asyncio.sleep(poll)
        if verdict is not None:
            result.status, result.summary, result.details = verdict
        elif isinstance(last_raw, dict) and last_raw.get("diag"):
            # No verdict before the timeout: keep the collector's diagnostic
            # snapshot so an "unknown" result explains what the page showed.
            result.details = [f"诊断：{str(last_raw['diag'])[:1500]}"]
        screenshot = report_dir / f"{site.id}.png"
        try:
            await page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass
        await page.screenshot(path=str(screenshot), full_page=site.id == "sannysoft")
        result.screenshot = screenshot.name
    except Exception as exc:  # network, site down, browser closed
        result.status = "error"
        result.summary = f"没能完成：{type(exc).__name__}: {str(exc)[:160]}"
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
    result.seconds = round(time.monotonic() - started, 1)
    return result


def reports_dir(data_dir: Path) -> Path:
    return data_dir / REPORTS_DIRNAME


def new_report_dir(data_dir: Path, profile_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^\w.@-]+", "_", profile_name or "profile")[:40]
    path = reports_dir(data_dir) / f"{stamp}-{safe}"
    path.mkdir(parents=True, exist_ok=False)
    return path


async def run_checks(
    context: Any,
    report_dir: Path,
    *,
    environment: dict[str, Any],
    progress: Progress | None = None,
    sites: tuple[SiteCheck, ...] = SITES,
    extra_results: list[CheckResult] | None = None,
    human_factory: Any = None,
) -> dict[str, Any]:
    """Visit every site in turn and write report.json; returns the report.

    ``extra_results`` (the local probe items) are folded in ahead of the
    site verdicts so one stored report carries the whole battery.
    """
    results: list[CheckResult] = list(extra_results or [])
    for index, site in enumerate(sites):
        if progress:
            maybe = progress(site.id, index, len(sites), None)
            if asyncio.iscoroutine(maybe):
                await maybe
        result = await run_site(context, site, report_dir, human_factory=human_factory)
        results.append(result)
        if progress:
            maybe = progress(site.id, index + 1, len(sites), result)
            if asyncio.iscoroutine(maybe):
                await maybe
    for result in results:
        if result.site in IP_DEPENDENT_SITES and result.ip_note is None:
            result.ip_note = IP_RESULT_NOTE
    report = {
        "id": report_dir.name,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "overall": overall_status(results),
        "summary": status_counts(results),
        "egress_note": egress_note(environment),
        "environment": environment,
        "results": [asdict(r) for r in results],
    }
    (report_dir / REPORT_FILE).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


# ── Stored reports ──────────────────────────────────────────────────────────


def _report_path(data_dir: Path, report_id: str) -> Path:
    if not re.fullmatch(r"[\w.@-]+", report_id or ""):
        raise FileNotFoundError(report_id)
    path = reports_dir(data_dir) / report_id
    if not (path / REPORT_FILE).is_file():
        raise FileNotFoundError(report_id)
    return path


def list_reports(data_dir: Path) -> list[dict[str, Any]]:
    root = reports_dir(data_dir)
    if not root.is_dir():
        return []
    reports = []
    for path in sorted(root.iterdir(), reverse=True):
        try:
            report = json.loads((path / REPORT_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        env = report.get("environment", {})
        results = report.get("results", [])
        reports.append({
            "id": report.get("id", path.name),
            "created_at": report.get("created_at"),
            "overall": report.get("overall"),
            "profile_id": env.get("profile_id"),
            "profile_name": env.get("profile_name"),
            "host_os": env.get("host_os"),
            "passed": sum(1 for r in results if r.get("status") == "pass"),
            "total": len(results),
            "counts": status_counts(results),
        })
    return reports


def load_report(data_dir: Path, report_id: str) -> dict[str, Any]:
    return json.loads((_report_path(data_dir, report_id) / REPORT_FILE).read_text(encoding="utf-8"))


# ── Comparing two reports of the same profile ───────────────────────────────


def _same_profile(a: dict[str, Any], b: dict[str, Any]) -> bool:
    env_a, env_b = a.get("environment") or {}, b.get("environment") or {}
    id_a, id_b = env_a.get("profile_id"), env_b.get("profile_id")
    if id_a and id_b:
        return id_a == id_b
    name_a, name_b = env_a.get("profile_name"), env_b.get("profile_name")
    return bool(name_a) and name_a == name_b


def previous_report(data_dir: Path, report: dict[str, Any]) -> dict[str, Any] | None:
    """The newest stored report for the same profile older than ``report``."""
    root = reports_dir(data_dir)
    if not root.is_dir():
        return None
    created = str(report.get("created_at") or "")
    candidates: list[dict[str, Any]] = []
    for path in root.iterdir():
        if path.name == report.get("id"):
            continue
        try:
            other = json.loads((path / REPORT_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not _same_profile(other, report):
            continue
        if str(other.get("created_at") or "") >= created:
            continue
        candidates.append(other)
    if not candidates:
        return None
    return max(candidates, key=lambda r: str(r.get("created_at") or ""))


def diff_reports(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Status changes between two reports of one profile, keyed by item id."""
    def by_site(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(r["site"]): r
            for r in report.get("results", [])
            if isinstance(r, dict) and r.get("site")
        }

    before, after = by_site(previous), by_site(current)
    changes: list[dict[str, Any]] = []
    for site_id, result in after.items():
        old = before.get(site_id)
        if old is None:
            changes.append({
                "site": site_id, "name": result.get("name"),
                "from": None, "to": result.get("status"), "summary": result.get("summary"),
            })
        elif old.get("status") != result.get("status"):
            changes.append({
                "site": site_id, "name": result.get("name"),
                "from": old.get("status"), "to": result.get("status"),
                "summary": result.get("summary"),
            })
    for site_id, result in before.items():
        if site_id not in after:
            changes.append({
                "site": site_id, "name": result.get("name"),
                "from": result.get("status"), "to": None, "summary": result.get("summary"),
            })
    return {
        "previous_id": previous.get("id"),
        "previous_created_at": previous.get("created_at"),
        "changes": changes,
    }


def report_file(data_dir: Path, report_id: str, name: str) -> Path:
    if not re.fullmatch(r"[\w-]+\.png", name or ""):
        raise FileNotFoundError(name)
    path = _report_path(data_dir, report_id) / name
    if not path.is_file():
        raise FileNotFoundError(name)
    return path


def zip_report(data_dir: Path, report_id: str, target: Path) -> Path:
    """report.json plus screenshots, ready to send for review."""
    source = _report_path(data_dir, report_id)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.iterdir()):
            if path.is_file() and (path.name == REPORT_FILE or path.suffix == ".png"):
                archive.write(path, f"{report_id}/{path.name}")
    return target


def delete_report(data_dir: Path, report_id: str) -> None:
    shutil.rmtree(_report_path(data_dir, report_id))
