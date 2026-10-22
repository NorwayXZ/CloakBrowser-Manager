"""Behavior humanization engine: planners, session driver, trace recorder."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend import behavior as bh
from backend import behavior_traces as bt


def _apply_plan(plan) -> str:
    """Replay a typing plan into a text buffer (typo-correction invariant)."""
    buffer: list[str] = []
    for event in plan:
        if event["kind"] == "char":
            buffer.append(event["value"])
        elif event["value"] == "Backspace":
            if buffer:
                buffer.pop()
    return "".join(buffer)


def _typo_count(plan) -> int:
    return sum(1 for e in plan if e["kind"] == "key" and e["value"] == "Backspace")


# ── Personality / presets ───────────────────────────────────────────────────


def test_personality_is_deterministic_per_seed():
    a = bh.personality_for("profile-1", "natural")
    b = bh.personality_for("profile-1", "natural")
    c = bh.personality_for("profile-2", "natural")
    assert a == b and a != c


def test_preset_scaling_removes_imperfections_when_off():
    off = bh.personality_for("p", "off")
    subtle = bh.personality_for("p", "subtle")
    natural = bh.personality_for("p", "natural")
    assert off.jitter_px == 0 and off.typo_rate == 0 and off.overshoot_chance == 0
    assert 0 < subtle.jitter_px < natural.jitter_px
    assert subtle.typo_rate < natural.typo_rate
    # Identity ranges (speed, rhythm) do not depend on the preset.
    assert off.mouse_speed == natural.mouse_speed


def test_easing_is_monotonic():
    samples = [bh._ease(i / 20) for i in range(21)]
    assert samples == sorted(samples) and samples[0] == 0 and samples[-1] == 1


def test_bias_personality_uses_trace_medians_clamped():
    base = bh.personality_for("p", "natural")
    biased = bh.bias_personality(base, {"median_key_interval_s": 0.21, "median_move_speed_px_s": 900.0})
    assert biased.key_interval == pytest.approx(0.21)
    assert biased.mouse_speed == pytest.approx(900.0)
    wild = bh.bias_personality(base, {"median_key_interval_s": 99.0})
    assert wild.key_interval <= 0.4
    assert bh.bias_personality(base, None) == base
    assert bh.bias_personality(base, {}) == base


# ── Mouse path planning ─────────────────────────────────────────────────────


def test_mouse_path_lands_on_target_and_takes_steps():
    personality = bh.personality_for("p", "natural")
    rng = bh._rng_for("case-1")
    path = bh.plan_mouse_path(rng, (0.0, 0.0), (300.0, 120.0), personality)
    assert path[-1][0] == 300.0 and path[-1][1] == 120.0
    assert 4 <= len(path) <= 121
    assert all(delay >= 0 for *_xy, delay in path)
    assert sum(delay for *_xy, delay in path) > 0.05


def test_mouse_path_is_curved_not_straight():
    personality = bh.personality_for("p", "natural")
    rng = bh._rng_for("curve")
    path = bh.plan_mouse_path(rng, (0.0, 0.0), (800.0, 0.0), personality)
    # Some intermediate point must bow off the straight line.
    assert max(abs(y) for _x, y, _d in path[:-1]) > 2.0


def test_mouse_path_short_move_is_single_step():
    personality = bh.personality_for("p", "natural")
    path = bh.plan_mouse_path(bh._rng_for("s"), (10.0, 10.0), (11.0, 10.5), personality)
    assert path == [(11.0, 10.5, 0.03)]


def test_mouse_path_deterministic():
    personality = bh.personality_for("p", "natural")
    a = bh.plan_mouse_path(bh._rng_for("d"), (0, 0), (500, 300), personality)
    b = bh.plan_mouse_path(bh._rng_for("d"), (0, 0), (500, 300), personality)
    assert a == b


# ── Typing planning ─────────────────────────────────────────────────────────


def test_typing_plan_replays_to_exact_text():
    personality = bh.personality_for("p", "natural")
    text = "The quick brown fox jumps over the lazy dog 1234567890 times and again"
    for trial in range(6):
        plan = bh.plan_typing(bh._rng_for(f"t{trial}"), text, personality)
        assert _apply_plan(plan) == text


def test_typing_plan_sensitive_mode_has_no_typos():
    personality = bh.personality_for("p", "natural")
    text = "correct horse battery staple"
    plan = bh.plan_typing(bh._rng_for("pw"), text, personality, sensitive=True)
    assert _typo_count(plan) == 0
    assert [e["value"] for e in plan] == list(text)


def test_typing_typos_are_bounded():
    personality = bh.personality_for("p", "natural")
    text = "a" * 400
    plan = bh.plan_typing(bh._rng_for("bounded"), text, personality)
    # Rate is ≤2.8%/char and typos are spaced ≥5 chars apart.
    assert _typo_count(plan) <= math.ceil(len(text) * personality.typo_rate) + 8


def test_typing_has_word_pauses_and_positive_delays():
    personality = bh.personality_for("p", "natural")
    plan = bh.plan_typing(bh._rng_for("wp"), "hello world this is typing", personality)
    assert all(e["delay"] >= 0.015 for e in plan)
    assert max(e["delay"] for e in plan) > 0.2  # a word pause or typo recovery


# ── Scroll planning ─────────────────────────────────────────────────────────


def test_scroll_plan_sums_to_distance_and_decelerates():
    personality = bh.personality_for("p", "natural")
    plan = bh.plan_scroll(bh._rng_for("sc"), 2000, personality)
    assert sum(delta for delta, _d in plan) == 2000
    assert len(plan) >= 3
    assert all(d >= 0 for _delta, d in plan)
    magnitudes = [abs(delta) for delta, _d in plan]
    assert magnitudes[-1] <= max(magnitudes)


def test_scroll_plan_handles_zero_and_negative():
    personality = bh.personality_for("p", "natural")
    assert bh.plan_scroll(bh._rng_for("z"), 0, personality) == []
    plan = bh.plan_scroll(bh._rng_for("n"), -900, personality)
    assert sum(delta for delta, _d in plan) == -900


# ── HumanSession against a fake page ────────────────────────────────────────


class _FakeMouse:
    def __init__(self, log):
        self.log = log

    async def move(self, x, y):
        self.log.append(("move", round(float(x), 1), round(float(y), 1)))

    async def down(self, button="left"):
        self.log.append(("down", button))

    async def up(self, button="left"):
        self.log.append(("up", button))

    async def wheel(self, dx, dy):
        self.log.append(("wheel", dx, dy))


class _FakeKeyboard:
    def __init__(self, log):
        self.log = log
        self.buffer: list[str] = []

    async def type(self, text):
        self.log.append(("type", text))
        self.buffer.extend(text)

    async def press(self, key):
        self.log.append(("press", key))
        if key == "Backspace" and self.buffer:
            self.buffer.pop()


class _FakePage:
    def __init__(self):
        self.log: list = []
        self.mouse = _FakeMouse(self.log)
        self.keyboard = _FakeKeyboard(self.log)
        self.scroll_y = 0.0

    async def evaluate(self, _js):
        return self.scroll_y


def _session(page, seed="sess", strength="natural"):
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    return bh.HumanSession(page, seed=seed, strength=strength, sleep=fake_sleep), sleeps


async def test_session_click_moves_then_presses():
    page = _FakePage()
    session, _sleeps = _session(page)
    await session.click((400.0, 200.0))
    kinds = [entry[0] for entry in page.log]
    assert kinds[0] == "move" and kinds[-2:] == ["down", "up"]
    moves = [e for e in page.log if e[0] == "move"]
    assert moves[-1][1] == 400.0 and moves[-1][2] == 200.0


async def test_session_click_locator_uses_bounding_box():
    page = _FakePage()
    session, _ = _session(page)
    locator = SimpleNamespace(
        bounding_box=AsyncMock(return_value={"x": 100.0, "y": 50.0, "width": 80.0, "height": 30.0})
    )
    await session.click(locator)
    moves = [e for e in page.log if e[0] == "move"]
    x, y = moves[-1][1], moves[-1][2]
    assert 100.0 < x < 180.0 and 50.0 < y < 80.0


async def test_session_type_produces_exact_text():
    page = _FakePage()
    session, sleeps = _session(page)
    text = "hello human world, this is a longer sentence to type out"
    await session.type_text(text)
    assert "".join(page.keyboard.buffer) == text
    assert sleeps and all(d >= 0 for d in sleeps)


async def test_session_type_sensitive_has_no_corrections():
    page = _FakePage()
    session, _ = _session(page)
    await session.type_text("s3cret password phrase", sensitive=True)
    assert "".join(page.keyboard.buffer) == "s3cret password phrase"
    assert not any(e[0] == "press" for e in page.log)


async def test_session_scroll_reaches_total_and_dwell_drifts():
    page = _FakePage()
    session, _ = _session(page)
    await session.scroll(1500)
    wheeled = sum(e[2] for e in page.log if e[0] == "wheel")
    assert wheeled == 1500
    page.log.clear()
    await session.dwell(2.0)
    assert page.log  # drift moves or micro-scrolls happened


# ── Trace recorder ──────────────────────────────────────────────────────────


def test_recorder_script_captures_timings_only():
    script = bt.RECORDER_SCRIPT
    assert "__cbmBehaviorRecord" in script
    # No key identity, no field values, no text content may be forwarded.
    assert "e.key" not in script and ".value" not in script and "textContent" not in script
    assert '"key"' in script or "'key'" in script or '{type: "key"' in script


def test_trace_stats_extracts_medians():
    events = (
        [{"type": "key", "t": t} for t in (0, 120, 260, 390)]
        + [{"type": "down", "t": 500}, {"type": "up", "t": 580}]
        + [{"type": "move", "t": 0, "x": 0, "y": 0}, {"type": "move", "t": 100, "x": 30, "y": 40}]
    )
    stats = bt.extract_stats(events)
    assert stats["event_count"] == len(events)
    assert stats["median_key_interval_s"] == pytest.approx(0.13)
    assert stats["median_press_ms"] == 80
    assert stats["median_move_speed_px_s"] == pytest.approx(500.0)


def test_trace_storage_round_trip(tmp_path: Path):
    events = [{"type": "key", "t": 0}, {"type": "key", "t": 150}, {"type": "key", "t": 300}]
    meta = bt.save_trace(tmp_path, "prof-1", events, started_at=None)
    assert meta["event_count"] == 3 and meta["profile_id"] == "prof-1"
    listed = bt.list_traces(tmp_path, "prof-1")
    assert [t["id"] for t in listed] == [meta["id"]]
    loaded = bt.load_trace(tmp_path, "prof-1", meta["id"])
    assert loaded["events"] == events
    stats = bt.latest_trace_stats(tmp_path, "prof-1")
    assert stats is not None and stats["median_key_interval_s"] == pytest.approx(0.15)
    assert bt.list_traces(tmp_path, "missing") == []
    assert bt.latest_trace_stats(tmp_path, "missing") is None


async def test_recorder_collects_via_binding():
    captured = {}

    class _RecPage:
        async def expose_binding(self, name, fn):
            captured["name"] = name
            captured["fn"] = fn

        async def add_init_script(self, script):
            captured["script"] = script

        async def evaluate(self, script):
            captured["evaluated"] = script

    recorder = bt.BehaviorRecorder("prof-9")
    await recorder.start(_RecPage())
    assert captured["name"] == "__cbmBehaviorRecord"
    captured["fn"](None, '{"type": "key", "t": 42}')
    captured["fn"](None, '{"type": "move", "t": 50, "x": 3, "y": 4}')
    captured["fn"](None, "not json")
    events = recorder.stop()
    assert events == [{"type": "key", "t": 42}, {"type": "move", "t": 50, "x": 3, "y": 4}]
    # After stop, further events are ignored.
    captured["fn"](None, '{"type": "key", "t": 99}')
    assert len(recorder.events) == 2


# ── Trace endpoints ─────────────────────────────────────────────────────────


def test_trace_endpoints_need_a_running_debug_session(app_client, monkeypatch):
    from unittest.mock import AsyncMock as _AM

    from backend import main

    pid = app_client.post("/api/profiles", json={"name": "Trace me"}).json()["id"]
    assert app_client.post(f"/api/profiles/{pid}/behavior-traces/start").status_code == 409
    assert app_client.get("/api/profiles/nope/behavior-traces").status_code == 404

    page = SimpleNamespace(
        expose_binding=_AM(), add_init_script=_AM(), evaluate=_AM(return_value=None)
    )
    running = SimpleNamespace(context=SimpleNamespace(pages=[page], new_page=_AM()))
    monkeypatch.setitem(main.browser_mgr.running, pid, running)
    try:
        resp = app_client.post(f"/api/profiles/{pid}/behavior-traces/start")
        assert resp.status_code == 200 and resp.json()["recording"] is True
        assert app_client.post(f"/api/profiles/{pid}/behavior-traces/start").status_code == 409
        listing = app_client.get(f"/api/profiles/{pid}/behavior-traces").json()
        assert listing["recording"] is True and listing["traces"] == []
        stopped = app_client.post(f"/api/profiles/{pid}/behavior-traces/stop")
        assert stopped.status_code == 200 and stopped.json()["trace"]["profile_id"] == pid
        listing = app_client.get(f"/api/profiles/{pid}/behavior-traces").json()
        assert listing["recording"] is False and len(listing["traces"]) == 1
        assert app_client.post(f"/api/profiles/{pid}/behavior-traces/stop").status_code == 409
    finally:
        main._behavior_recorders.pop(pid, None)


# ── Site-check integration ──────────────────────────────────────────────────


async def test_run_site_uses_human_factory(tmp_path: Path):
    from backend import site_checks as sc

    class _CheckPage:
        def __init__(self):
            self.closed = False

        async def goto(self, url, **_kw):
            pass

        async def evaluate(self, js):
            if "scrollY" in js:
                return 0
            return {"passed": 31, "failed": 0, "warn": 0}

        async def screenshot(self, path, full_page=False):
            Path(path).write_bytes(b"\x89PNG")

        async def close(self):
            self.closed = True

    page = _CheckPage()
    context = SimpleNamespace(new_page=AsyncMock(return_value=page))
    site = sc.SiteCheck("sannysoft", "Sannysoft", "u", "c", sc.SANNYSOFT_JS, timeout=5, min_wait=0)

    settled: list[float] = []

    class _Human:
        async def settle(self, seconds):
            settled.append(seconds)

    result = await sc.run_site(context, site, tmp_path, poll=0, human_factory=lambda p: _Human())
    assert result.status == "pass"
    assert settled == [3.0]
