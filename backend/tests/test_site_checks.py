"""Fingerprint check against public detection sites: verdict rules, run, reports."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from backend import site_checks as sc
from backend.site_check_job import SiteCheckJob, describe_environment

# ── Verdict rules ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("raw", "status"), [
    ({"text": "Headless\n12% like headless: aa\n0% headless: bb\n0% stealth: cc", "lies": 0}, "pass"),
    ({"text": "31% like headless: aa\n0% headless: bb\n0% stealth: cc", "lies": 2}, "fail"),
    ({"text": "10% like headless: aa\n33% headless: bb\n0% stealth: cc", "lies": 0}, "fail"),
    ({"text": "still loading", "lies": 0}, None),
])
def test_creepjs(raw, status):
    verdict = sc.judge_creepjs(raw)
    assert (verdict[0] if verdict else None) == status


def test_creepjs_does_not_mistake_like_headless_for_headless():
    verdict = sc.judge_creepjs({"text": "45% like headless: a\n0% headless: b\n0% stealth: c", "lies": 0})
    assert verdict[0] == "pass"
    assert "headless：0%" in verdict[2]


@pytest.mark.parametrize(("text", "status", "summary"), [
    ("Your Browser Fingerprint is consistent\nNo masking detected\nNo automated behavior detected", "pass", "指纹一致"),
    ("Your Browser Fingerprint is inconsistent\nMasking detected\nNo automated behavior detected", "fail", "指纹不一致、检测到伪装"),
    ("Your Browser Fingerprint is consistent\nNo masking detected\nAutomated behavior detected", "fail", "检测到自动化"),
])
def test_pixelscan(text, status, summary):
    verdict = sc.judge_pixelscan(text)
    assert verdict[0] == status and summary in verdict[1]


def test_pixelscan_waits_for_its_verdict():
    assert sc.judge_pixelscan("Scanning...") is None


@pytest.mark.parametrize(("text", "status"), [
    ("Bot Detection:\nNo\nBrowser fingerprint authenticity: 100%", "pass"),
    ("Bot Detection:\nNo\nBrowser fingerprint authenticity: 95%\nAd\nWebGL exception\n-5%\n", "warn"),
    ("Bot Detection:\nNo\nBrowser fingerprint authenticity: 85%\nAd\nDifferent time zones\n-10%\n", "fail"),
    ("Bot Detection:\nYes\nBrowser fingerprint authenticity: 100%", "fail"),
])
def test_browserscan(text, status):
    verdict = sc.judge_browserscan(text.replace("Bot Detection:\n", "Bot Detection: "))
    assert verdict[0] == status


def test_browserscan_lists_deductions():
    verdict = sc.judge_browserscan("Browser fingerprint authenticity: 85%\nAd\nDifferent time zones\n-10%\n")
    assert "扣分：Different time zones -10%" in verdict[2]


@pytest.mark.parametrize(("raw", "status"), [
    ({"passed": 31, "failed": 0, "warn": 0}, "pass"),
    ({"passed": 29, "failed": 2, "warn": 0}, "fail"),
    ({"passed": 30, "failed": 0, "warn": 1}, "warn"),
    ({"passed": 3, "failed": 0, "warn": 0}, None),
])
def test_sannysoft(raw, status):
    verdict = sc.judge_sannysoft(raw)
    assert (verdict[0] if verdict else None) == status


@pytest.mark.parametrize(("text", "status"), [
    ("Your Digital Identity Looks \nTrustworthy\n\nHARDWARE\n\nEverything is fine\n95\nMX SCORE", "pass"),
    ("Your Digital Identity Looks \nUnreliable\n\nHARDWARE\n\nEverything is fine\n60\nMX SCORE", "fail"),
    ("Your Digital Identity Looks \nSuspicious\n", "fail"),
])
def test_iphey(text, status):
    verdict = sc.judge_iphey(text)
    assert verdict[0] == status


def test_iphey_names_the_flagged_card_and_its_reasons():
    raw = {
        "text": "Looks \nUnreliable\n\nHARDWARE\n\nEverything is fine\n70\nMX SCORE",
        "flagged": ["Browser"],
        "signals": "SIGNALS\nBrowser\nDetected an inconsistent browser fingerprint (pineapple)\nBrowser\nDetected an inconsistent browser fingerprint (roadmap)",
    }
    verdict = sc.judge_iphey(raw)
    assert "标红的项目：Browser" in verdict[2]
    assert "原因：Detected an inconsistent browser fingerprint (roadmap)" in verdict[2]


def test_iphey_keeps_the_summary_card_values():
    text = "Looks \nUnreliable\n\nHARDWARE\n\nEverything is fine\n60\nMX SCORE\n...\nHARDWARE\nAudio\n"
    verdict = sc.judge_iphey(text)
    assert "Hardware：Everything is fine" in verdict[2]
    assert "MX 分数：60" in verdict[2]
    assert not any("Audio" in d for d in verdict[2])


@pytest.mark.parametrize(("text", "status"), [
    ("Your WebRTC IP\nWebRTC Leak Test\t\n✔\nNo Leak\nLocal IP Address\t-\nPublic IP Address\t-", "pass"),
    ("WebRTC Leak Test\t\n✘\nLeak\nPublic IP Address\t203.0.113.7", "fail"),
])
def test_browserleaks_webrtc(text, status):
    assert sc.judge_browserleaks_webrtc(text)[0] == status


FP_OK = 'bot: "not_detected"\ndeveloper_tools: false\nsuspect_score: 2\ntampering: false\nvirtual_machine: false\n'


@pytest.mark.parametrize(("text", "status", "problem"), [
    (FP_OK, "pass", None),
    (FP_OK.replace("tampering: false", 'tampering: true\ntampering_details: {\nanti_detect_browser: true\n}'),
     "fail", "识别为反检测浏览器"),
    (FP_OK.replace('"not_detected"', '"bad"'), "fail", "机器人"),
    (FP_OK.replace("virtual_machine: false", "virtual_machine: true"), "fail", "虚拟机"),
])
def test_fingerprint(text, status, problem):
    verdict = sc.judge_fingerprint(text)
    assert verdict[0] == status
    if problem:
        assert problem in verdict[1]


def test_fingerprint_ignores_vpn_in_the_verdict():
    verdict = sc.judge_fingerprint("SMART SIGNALS\nVPN\t\nYou are using a VPN\n" + FP_OK)
    assert verdict[0] == "pass"
    assert any("VPN：You are using a VPN" in d for d in verdict[2])


def test_every_site_has_a_rule():
    assert set(sc.JUDGES) == {site.id for site in sc.SITES}
    assert len(sc.SITES) == 7


def test_overall_needs_every_site_to_pass():
    def r(status):
        return sc.CheckResult("x", "X", "u", "c", status, "")
    assert sc.overall_status([r("pass"), r("pass")]) == "pass"
    assert sc.overall_status([r("pass"), r("warn")]) == "warn"
    assert sc.overall_status([r("pass"), r("unknown")]) == "fail"
    assert sc.overall_status([r("error"), r("pass")]) == "fail"


# ── Running against a fake browser ───────────────────────────────────────────


class FakePage:
    def __init__(self, readings, fail=False):
        self.readings = list(readings)
        self.fail = fail
        self.closed = False

    async def goto(self, url, **_kw):
        if self.fail:
            raise TimeoutError("net::ERR_TIMED_OUT")

    async def evaluate(self, _js):
        return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]

    async def screenshot(self, path, full_page=False):
        Path(path).write_bytes(b"\x89PNG")

    async def close(self):
        self.closed = True


def _context(pages):
    queue = list(pages)
    return SimpleNamespace(new_page=AsyncMock(side_effect=lambda: queue.pop(0)))


SANNY = sc.SiteCheck("sannysoft", "Sannysoft", "u", "c", sc.SANNYSOFT_JS, timeout=5, min_wait=0)


@pytest.mark.asyncio
async def test_run_site_waits_for_the_verdict_and_screenshots(tmp_path: Path):
    page = FakePage([{"passed": 0, "failed": 0, "warn": 0}, {"passed": 31, "failed": 0, "warn": 0}])
    site = sc.SiteCheck("sannysoft", "Sannysoft", "u", "c", sc.SANNYSOFT_JS, min_wait=0)
    result = await sc.run_site(_context([page]), site, tmp_path, poll=0)

    assert result.status == "pass" and result.screenshot == "sannysoft.png"
    assert (tmp_path / "sannysoft.png").exists() and page.closed


@pytest.mark.asyncio
async def test_run_site_reports_unknown_when_no_verdict_appears(tmp_path: Path):
    site = sc.SiteCheck("sannysoft", "Sannysoft", "u", "c", sc.SANNYSOFT_JS, timeout=0.05)
    result = await sc.run_site(_context([FakePage([{"passed": 0, "failed": 0, "warn": 0}])]), site, tmp_path, poll=0.01)
    assert result.status == "unknown" and result.screenshot == "sannysoft.png"


@pytest.mark.asyncio
async def test_run_site_reports_network_errors(tmp_path: Path):
    result = await sc.run_site(_context([FakePage([{}], fail=True)]), SANNY, tmp_path, poll=0)
    assert result.status == "error" and "ERR_TIMED_OUT" in result.summary


@pytest.mark.asyncio
async def test_run_checks_writes_the_report_and_lists_it(tmp_path: Path):
    report_dir = sc.new_report_dir(tmp_path, "awsdee@eeaa.xyz")
    seen = []
    report = await sc.run_checks(
        _context([FakePage([{"passed": 31, "failed": 0, "warn": 0}])]), report_dir,
        environment={"profile_name": "awsdee@eeaa.xyz", "host_os": "windows"},
        progress=lambda site, i, total, result: seen.append((site, i, result is not None)),
        sites=(SANNY,),
    )

    assert report["overall"] == "pass"
    assert seen == [("sannysoft", 0, False), ("sannysoft", 1, True)]
    listed = sc.list_reports(tmp_path)
    assert listed[0]["id"] == report_dir.name and listed[0]["passed"] == 1 and listed[0]["host_os"] == "windows"
    assert sc.load_report(tmp_path, report_dir.name)["results"][0]["status"] == "pass"

    archive = sc.zip_report(tmp_path, report_dir.name, tmp_path / "out.zip")
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == [f"{report_dir.name}/report.json", f"{report_dir.name}/sannysoft.png"]


@pytest.mark.asyncio
async def test_run_site_waits_until_two_reads_agree(tmp_path: Path):
    reads = [{"passed": 30, "failed": 1, "warn": 0}, {"passed": 31, "failed": 0, "warn": 0},
             {"passed": 31, "failed": 0, "warn": 0}]
    result = await sc.run_site(_context([FakePage(reads)]), SANNY, tmp_path, poll=0)
    assert result.status == "pass"


def test_report_paths_cannot_escape(tmp_path: Path):
    for bad in ("../x", "a/b", ""):
        with pytest.raises(FileNotFoundError):
            sc.load_report(tmp_path, bad)
    report_dir = sc.new_report_dir(tmp_path, "p")
    (report_dir / sc.REPORT_FILE).write_text("{}")
    with pytest.raises(FileNotFoundError):
        sc.report_file(tmp_path, report_dir.name, "../report.json")


# ── Job and API ──────────────────────────────────────────────────────────────


def test_environment_never_contains_proxy_credentials_or_cookies():
    profile = {"name": "p", "proxy": "socks5://user:secret@1.2.3.4:1080", "cookies_json": "[...]",
               "platform": "windows", "gpu_renderer": "ANGLE (NVIDIA)", "fingerprint_options": {"brand": "Edge"}}
    running = SimpleNamespace(proxy_geo={"ip": "1.2.3.4", "country_code": "JP"}, effective_timezone="Asia/Tokyo", effective_locale="ja-JP")

    env = describe_environment(profile, running, app_version="0.5.3", kernel_version="154", host_os="windows")

    dumped = json.dumps(env)
    assert "secret" not in dumped and "user:" not in dumped and "cookies" not in dumped
    assert env["proxy_type"] == "socks5" and env["exit_country"] == "JP"
    assert env["fingerprint"]["fingerprint_options"] == {"brand": "Edge"}


@pytest.mark.asyncio
async def test_job_launches_in_debug_checks_and_closes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    running = SimpleNamespace(context=_context([FakePage([{"passed": 31, "failed": 0, "warn": 0}])]))
    mgr = SimpleNamespace(launch=AsyncMock(return_value=running), stop=AsyncMock())
    job = SiteCheckJob()

    assert job.start({"id": "p1", "name": "P"}, browser_mgr=mgr, data_dir=tmp_path,
                     environment=lambda p, r: {"profile_name": "P"}, sites=(SANNY,))
    assert job.busy
    await job._task

    mgr.launch.assert_awaited_once_with({"id": "p1", "name": "P"}, launch_mode="debug")
    mgr.stop.assert_awaited_once_with("p1", reason="指纹检测完成")
    state = job.snapshot()
    assert state["phase"] == "done" and state["overall"] == "pass" and len(state["results"]) == 1


@pytest.mark.asyncio
async def test_job_reports_a_failed_launch(tmp_path: Path):
    mgr = SimpleNamespace(launch=AsyncMock(side_effect=RuntimeError("授权并发已满")), stop=AsyncMock())
    job = SiteCheckJob()
    job.start({"id": "p1", "name": "P"}, browser_mgr=mgr, data_dir=tmp_path, environment=lambda p, r: {})
    await job._task

    assert job.snapshot()["phase"] == "failed" and "授权并发已满" in job.snapshot()["error"]
    mgr.stop.assert_not_awaited()


def test_api_refuses_a_running_profile(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from backend import main

    pid = app_client.post("/api/profiles", json={"name": "Check me"}).json()["id"]
    monkeypatch.setitem(main.browser_mgr.running, pid, MagicMock())
    resp = app_client.post(f"/api/profiles/{pid}/site-check")
    assert resp.status_code == 409 and "关闭" in resp.json()["detail"]


def test_api_starts_a_check(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from backend import main

    pid = app_client.post("/api/profiles", json={"name": "Check me"}).json()["id"]
    started = []
    monkeypatch.setattr(main.site_check_job, "start", lambda profile, **kw: started.append(profile["id"]) or True)

    assert app_client.post(f"/api/profiles/{pid}/site-check").status_code == 200
    assert started == [pid]
    assert [s["id"] for s in app_client.get("/api/site-checks/sites").json()][:2] == ["creepjs", "pixelscan"]


def test_api_reports_round_trip(app_client: TestClient):
    from backend import database as db

    report_dir = sc.new_report_dir(db.DATA_DIR, "p")
    (report_dir / "creepjs.png").write_bytes(b"\x89PNG")
    (report_dir / sc.REPORT_FILE).write_text(json.dumps({"id": report_dir.name, "overall": "fail", "results": [], "environment": {}}))

    assert app_client.get("/api/site-checks").json()[0]["id"] == report_dir.name
    assert app_client.get(f"/api/site-checks/{report_dir.name}").json()["overall"] == "fail"
    assert app_client.get(f"/api/site-checks/{report_dir.name}/files/creepjs.png").status_code == 200
    download = app_client.get(f"/api/site-checks/{report_dir.name}/download")
    assert download.status_code == 200 and download.headers["content-type"] == "application/zip"
    assert app_client.delete(f"/api/site-checks/{report_dir.name}").status_code == 200
    assert app_client.get(f"/api/site-checks/{report_dir.name}").status_code == 404
