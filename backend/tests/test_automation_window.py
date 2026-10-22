"""Automation hours window: parsing, open/closed logic, settings API,
scheduler deferral, and the live automation-status endpoint."""

from __future__ import annotations

from datetime import datetime

import pytest
from starlette.testclient import TestClient

from backend import automation_window as aw
from backend import database as db


# ── Parsing ──────────────────────────────────────────────────────────────


def test_parse_window_variants():
    assert aw.parse_window("09-18") == (9, 18)
    assert aw.parse_window("23-07") == (23, 7)
    assert aw.parse_window(" 9 - 18 ") == (9, 18)
    assert aw.parse_window("") is None
    assert aw.parse_window(None) is None
    assert aw.parse_window("09-09") is None  # empty range = no restriction
    assert aw.parse_window("25-26") is None
    assert aw.parse_window("banana") is None
    assert aw.parse_window("9") is None


def test_format_and_describe_round_trip():
    assert aw.format_window((9, 18)) == "09-18"
    assert aw.format_window((23, 7)) == "23-07"
    assert "09:00" in aw.describe_window((9, 18))


# ── Open/closed ──────────────────────────────────────────────────────────


def _at(hour: int) -> datetime:
    return datetime(2026, 10, 22, hour, 30)


def test_is_open_daytime_range():
    window = (9, 18)
    assert aw.is_open(_at(9), window) and aw.is_open(_at(17), window)
    assert not aw.is_open(_at(8), window) and not aw.is_open(_at(18), window)


def test_is_open_overnight_range():
    window = (23, 7)
    assert aw.is_open(_at(23), window) and aw.is_open(_at(0), window)
    assert aw.is_open(_at(6), window)
    assert not aw.is_open(_at(7), window) and not aw.is_open(_at(12), window)


def test_is_open_without_window_is_always_open():
    assert aw.is_open(_at(3), None)


# ── Settings API ─────────────────────────────────────────────────────────


def test_hours_settings_round_trip(app_client: TestClient):
    assert app_client.get("/api/automation/hours").json() == {
        "hours": None, "open_now": True,
    }
    resp = app_client.put("/api/automation/hours", json={"hours": "23-07"})
    assert resp.status_code == 200 and resp.json()["hours"] == "23-07"
    assert app_client.get("/api/automation/hours").json()["hours"] == "23-07"

    resp = app_client.put("/api/automation/hours", json={"hours": ""})
    assert resp.status_code == 200 and resp.json()["hours"] is None
    assert app_client.get("/api/automation/hours").json()["hours"] is None


def test_hours_settings_reject_garbage(app_client: TestClient):
    for bad in ("banana", "25-26", "9", "09:00-18:00"):
        resp = app_client.put("/api/automation/hours", json={"hours": bad})
        assert resp.status_code == 422, bad
    # Rejections never clobber the stored value.
    assert app_client.get("/api/automation/hours").json()["hours"] is None


# ── Live automation status ───────────────────────────────────────────────


def test_status_idle_by_default(app_client: TestClient):
    body = app_client.get("/api/automation/status").json()
    assert body["active"] is False and body["kind"] is None


def test_status_reports_running_warmup(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from backend import main

    monkeypatch.setattr(main, "_warmup_busy", lambda: True)
    monkeypatch.setitem(main._warmup_current, "profile_id", "p-9")
    monkeypatch.setitem(main._warmup_current, "profile_name", "养号画像")

    body = app_client.get("/api/automation/status").json()
    assert body == {
        "active": True, "kind": "warmup", "label": "养号",
        "profile_id": "p-9", "profile_name": "养号画像",
    }


def test_status_prefers_evolution_over_its_own_site_check(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from backend import main

    monkeypatch.setattr(main, "_evolution_busy", lambda: True)
    monkeypatch.setitem(main._evolution_current, "profile_id", "p-1")
    monkeypatch.setitem(main._evolution_current, "profile_name", "进化画像")
    # Even with a warm-up also claiming to run, the evolution cycle (which
    # drives its own checks internally) is the unit worth displaying.
    monkeypatch.setattr(main, "_warmup_busy", lambda: True)

    body = app_client.get("/api/automation/status").json()
    assert body["kind"] == "evolution" and body["profile_name"] == "进化画像"


# ── Warm-up scheduler deferral ───────────────────────────────────────────


def _closed_window_text(now: datetime) -> str:
    """An HH-HH window that does not contain the current hour."""
    start = (now.hour + 2) % 24
    end = (now.hour + 3) % 24
    return f"{start:02d}-{end:02d}"


@pytest.mark.asyncio
async def test_warmup_tick_defers_outside_window_without_advancing_cadence(
    tmp_db, monkeypatch: pytest.MonkeyPatch
):
    from backend import main

    profile = db.create_profile(name="养号", warmup_enabled=1, warmup_daily_max=1)
    now = datetime.now().astimezone()
    db.set_setting(aw.SETTING_KEY, _closed_window_text(now))
    assert not main._automation_window_open()

    started: list[str] = []
    monkeypatch.setattr(
        main, "_start_warmup_task",
        lambda prof, done: started.append(prof["id"]) or True,
    )

    await main._warmup_tick()
    assert started == []
    runs = db.list_warmup_runs(profile["id"], 5)
    assert len(runs) == 1
    assert runs[0]["status"] == "skipped"
    assert runs[0]["detail"]["deferred"] == "automation_hours"
    assert "时段" in runs[0]["reason"]

    # A second tick inside the same closed stretch leaves no duplicate.
    await main._warmup_tick()
    assert len(db.list_warmup_runs(profile["id"], 5)) == 1

    # Once the window opens, the profile is due immediately: the deferred
    # marker did not push the cadence clock forward.
    db.set_setting(aw.SETTING_KEY, "")
    await main._warmup_tick()
    assert started == [profile["id"]]
