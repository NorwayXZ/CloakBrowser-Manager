"""Warm-up （养号）: catalog, plan builder, due logic, runner, persistence."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import pytest

from backend import database as db
from backend import warmup as wu


def _profile(**overrides):
    base = {
        "id": "prof-warm",
        "name": "Warm",
        "locale": "en-US",
        "timezone": "America/New_York",
        "warmup_enabled": 1,
        "warmup_daily_max": 1,
        "warmup_targets": [],
        "created_at": "2026-10-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# ── Catalog integrity ───────────────────────────────────────────────────────


def test_catalog_is_well_formed():
    for platform_id, entry in wu.TARGET_CATALOG.items():
        assert "*" in entry["domains"], platform_id
        for domain in entry["domains"].values():
            assert "." in domain and " " not in domain
        profile = _profile()
        home = wu.target_home_url(platform_id, profile)
        parsed = urlparse(home)
        assert parsed.scheme == "https" and parsed.hostname in entry["domains"].values()
        if entry.get("search"):
            url = wu.target_search_url(platform_id, profile, "test query")
            assert url is not None and urlparse(url).hostname == parsed.hostname
            assert "test+query" in url
        else:
            assert wu.target_search_url(platform_id, profile, "x") is None


def test_catalog_regional_domains_follow_locale():
    de = _profile(locale="de-DE")
    assert urlparse(wu.target_home_url("amazon", de)).hostname == "www.amazon.de"
    jp = _profile(locale="ja-JP")
    assert urlparse(wu.target_home_url("google", jp)).hostname == "www.google.co.jp"
    assert urlparse(wu.target_home_url("amazon", _profile(locale="fr-FR"))).hostname == "www.amazon.fr"


# ── URL safety policy ───────────────────────────────────────────────────────


def test_follow_url_policy():
    home = "https://www.amazon.com/"
    assert wu.is_safe_follow_url("https://www.amazon.com/dp/B0EXAMPLE", home)
    assert wu.is_safe_follow_url("https://smile.amazon.com/gp/product/x", home)
    assert not wu.is_safe_follow_url("https://www.amazon.com/gp/cart/view.html", home)
    assert not wu.is_safe_follow_url("https://www.amazon.com/ap/signin", home)
    assert not wu.is_safe_follow_url("https://www.amazon.com/checkout", home)
    assert not wu.is_safe_follow_url("https://evil.example.com/dp/x", home)
    assert not wu.is_safe_follow_url("javascript:void(0)", home)


# ── Session plan ────────────────────────────────────────────────────────────


def test_plan_prioritizes_targets_and_stays_in_catalog():
    profile = _profile(warmup_targets=["amazon", "google"])
    plan = wu.build_session_plan(profile, random.Random(7))
    assert plan[0]["kind"] == "target"
    platforms = [s["platform"] for s in plan if s["kind"] == "target"]
    assert set(platforms) == {"amazon", "google"}
    assert 4 <= len(plan) <= 7
    allowed_hosts = set()
    for entry in wu.TARGET_CATALOG.values():
        allowed_hosts.update(entry["domains"].values())
    allowed_hosts.update(urlparse(u).hostname for u in wu.GENERIC_SITES["en"])
    for step in plan:
        assert urlparse(step["url"]).hostname in allowed_hosts
        path = urlparse(step["url"]).path.lower()
        assert not any(seg in path for seg in ("login", "checkout", "cart", "signin"))
        if step.get("search_url"):
            assert urlparse(step["search_url"]).hostname in allowed_hosts


def test_plan_respects_daily_cap_and_unknown_platforms():
    profile = _profile(warmup_targets=["amazon", "not-a-platform", "ebay"])
    plan = wu.build_session_plan(profile, random.Random(3), targets_done_today={"amazon"})
    platforms = [s.get("platform") for s in plan if s["kind"] == "target"]
    assert "amazon" not in platforms and "ebay" in platforms
    assert all(s["kind"] in ("target", "generic") for s in plan)


def test_plan_without_targets_is_generic_only():
    plan = wu.build_session_plan(_profile(), random.Random(1))
    assert plan and all(s["kind"] == "generic" for s in plan)


# ── Due logic / identity age ────────────────────────────────────────────────

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)


def test_is_due():
    profile = _profile()
    assert wu.is_due(profile, runs_today=0, last_run_at=None, now=NOW)
    assert not wu.is_due(profile, runs_today=1, last_run_at=None, now=NOW)
    assert not wu.is_due(_profile(warmup_enabled=0), runs_today=0, last_run_at=None, now=NOW)
    assert not wu.is_due(_profile(deleted_at="2026-10-20"), runs_today=0, last_run_at=None, now=NOW)
    twice = _profile(warmup_daily_max=2)
    assert not wu.is_due(twice, runs_today=1, last_run_at=NOW - timedelta(hours=1), now=NOW)
    assert wu.is_due(twice, runs_today=1, last_run_at=NOW - timedelta(hours=4), now=NOW)


def test_identity_age():
    age = wu.identity_age(_profile(), {"ok_runs": 5, "total_runs": 6, "last_run_at": "2026-10-21T09:00:00+00:00"}, now=NOW)
    assert age["age_days"] == 21 and age["warmup_sessions"] == 5 and age["warmup_runs_total"] == 6
    assert age["last_warmup_at"].startswith("2026-10-21")


def test_targets_done_today_reads_run_details():
    runs = [
        {"status": "ok", "detail": {"targets": ["amazon"]}},
        {"status": "skipped", "detail": {"targets": ["google"]}},
        {"status": "ok", "detail": None},
    ]
    assert wu.targets_done_today(runs) == {"amazon"}


# ── Runner with a faked BrowserManager ──────────────────────────────────────


class _Page:
    def __init__(self, links):
        self.visited: list[str] = []
        self._links = links
        self.mouse = SimpleNamespace(
            move=AsyncMock(), down=AsyncMock(), up=AsyncMock(), wheel=AsyncMock()
        )
        self.keyboard = SimpleNamespace(type=AsyncMock(), press=AsyncMock())

    async def goto(self, url, **_kw):
        self.visited.append(url)

    async def evaluate(self, js):
        if "querySelectorAll" in js:
            return list(self._links)
        return 0

    async def close(self):
        pass


class _Mgr:
    def __init__(self, page=None, launch_error=None, context_none=False):
        self.running: dict = {}
        self._launching: set = set()
        self.page = page
        self.launch_error = launch_error
        self.context_none = context_none
        self.launch_calls = 0
        self.launch_kwargs: list[dict] = []
        self.stop_calls: list[str] = []

    async def launch(self, profile, launch_mode="debug", **kwargs):
        self.launch_calls += 1
        self.launch_kwargs.append({"launch_mode": launch_mode, **kwargs})
        if self.launch_error:
            raise self.launch_error
        context = None if self.context_none else SimpleNamespace(new_page=AsyncMock(return_value=self.page))
        return SimpleNamespace(context=context)

    async def stop(self, profile_id, reason=None):
        self.stop_calls.append(profile_id)


async def _run(profile, mgr, **kw):
    records: list[dict] = []
    result = await wu.run_warmup(
        profile, browser_mgr=mgr, record_run=records.append, time_scale=0, **kw
    )
    return result, records


async def test_runner_browses_plan_and_closes():
    home = "https://www.amazon.com/"
    page = _Page(links=[
        "https://www.amazon.com/dp/B0EXAMPLE",      # safe product page
        "https://www.amazon.com/ap/signin",          # blocked
        "https://evil.example.com/",                 # off-site
    ])
    mgr = _Mgr(page=page)
    profile = _profile(warmup_targets=["amazon"])
    result, records = await _run(profile, mgr)
    assert result["status"] == "ok" and records and records[0]["status"] == "ok"
    # Warm-up is automation: it must always launch headless so no window
    # ever appears on the user's desktop.
    assert mgr.launch_kwargs == [{"launch_mode": "debug", "headless": True}]
    assert mgr.stop_calls == [profile["id"]]
    assert page.visited[0] == home
    assert all(
        urlparse(u).hostname.endswith("amazon.com") or u in wu.GENERIC_SITES["en"]
        for u in page.visited
    )
    assert not any("signin" in u or "evil" in u for u in page.visited)
    assert result["pages_visited"] == len(page.visited) >= 4
    assert result["detail"]["targets"] == ["amazon"]


async def test_runner_skips_when_seat_busy():
    mgr = _Mgr(launch_error=RuntimeError("license session limit reached"))
    result, records = await _run(_profile(), mgr)
    assert result["status"] == "skipped" and "并发" in result["reason"]
    assert mgr.stop_calls == [] and records[0]["status"] == "skipped"


async def test_runner_skips_when_profile_already_running():
    mgr = _Mgr(page=_Page(links=[]))
    profile = _profile()
    mgr.running[profile["id"]] = object()
    result, _records = await _run(profile, mgr)
    assert result["status"] == "skipped" and mgr.launch_calls == 0


async def test_runner_records_generic_launch_failure():
    mgr = _Mgr(launch_error=RuntimeError("binary missing"))
    result, _records = await _run(_profile(), mgr)
    assert result["status"] == "failed" and "binary missing" in result["reason"]


async def test_runner_closes_browser_when_context_missing():
    mgr = _Mgr(context_none=True)
    result, _records = await _run(_profile(), mgr)
    assert result["status"] == "failed"
    assert mgr.stop_calls == [_profile()["id"]]


# ── Persistence + API ───────────────────────────────────────────────────────


def test_warmup_fields_and_run_history_round_trip(tmp_db):
    profile = db.create_profile(name="Aged", warmup_enabled=True, warmup_daily_max=2,
                                warmup_targets=["amazon", "facebook"])
    assert profile["warmup_enabled"] == 1 and profile["warmup_daily_max"] == 2
    assert profile["warmup_targets"] == ["amazon", "facebook"]

    updated = db.update_profile(profile["id"], warmup_targets=["google"], warmup_daily_max=3)
    assert updated["warmup_targets"] == ["google"] and updated["warmup_daily_max"] == 3

    run = db.record_warmup_run(
        profile["id"], started_at="2026-10-22T08:00:00+00:00",
        finished_at="2026-10-22T08:05:00+00:00", duration_s=300.0,
        pages_visited=6, status="ok", detail={"targets": ["google"], "urls": []},
    )
    assert run["detail"]["targets"] == ["google"]
    db.record_warmup_run(
        profile["id"], started_at="2026-10-22T09:00:00+00:00",
        finished_at=None, duration_s=None, pages_visited=0,
        status="skipped", reason="授权并发已满",
    )
    runs = db.list_warmup_runs(profile["id"])
    assert [r["status"] for r in runs] == ["skipped", "ok"]  # newest first
    stats = db.warmup_stats(profile["id"])
    assert stats == {"total_runs": 2, "ok_runs": 1, "last_run_at": "2026-10-22T08:00:00+00:00"}
    assert db.count_warmup_runs_since(profile["id"], "2026-10-22T00:00:00+00:00", status="ok") == 1
    assert db.count_warmup_runs_since(profile["id"], "2026-10-23T00:00:00+00:00") == 0


def test_warmup_api_surface(app_client):
    pid = app_client.post("/api/profiles", json={"name": "Warm API"}).json()["id"]
    targets = app_client.get("/api/warmup/targets").json()
    assert {t["id"] for t in targets} >= {"amazon", "facebook", "google", "x", "ebay", "youtube"}
    info = app_client.get(f"/api/profiles/{pid}/warmup").json()
    assert info["enabled"] is False and info["daily_max"] == 1 and info["targets"] == []
    assert info["age"]["warmup_sessions"] == 0 and info["runs"] == []
    assert app_client.get("/api/profiles/nope/warmup").status_code == 404

    updated = app_client.put(
        f"/api/profiles/{pid}",
        json={"warmup_enabled": True, "warmup_daily_max": 2, "warmup_targets": ["amazon"]},
    )
    assert updated.status_code == 200
    info = app_client.get(f"/api/profiles/{pid}/warmup").json()
    assert info["enabled"] is True and info["daily_max"] == 2 and info["targets"] == ["amazon"]
