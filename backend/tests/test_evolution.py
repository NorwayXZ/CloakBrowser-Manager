"""Self-adversarial evolution: attribution, scoring, engine, API.

The engine is tested with injected fakes — no browser ever launches.
The guarantees under test: experiments only ever touch disposable
clones, clones are burned in every outcome, wins become proposals,
and the real profile changes only through proposal approval.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from starlette.testclient import TestClient

from backend import database as db
from backend import evolution
from backend.evolution import (
    AutomationLock,
    Candidate,
    CheckOutcome,
    EngineDeps,
    EvolutionEngine,
    attribute,
    is_due,
    score_experiment,
    update_kwargs,
)


def make_report(*items: tuple[str, str], report_id: str = "r1") -> dict:
    return {
        "id": report_id,
        "overall": "fail",
        "results": [
            {"site": site, "name": site, "status": status, "summary": f"{site} {status}", "details": []}
            for site, status in items
        ],
    }


def profile(**overrides) -> dict:
    base = {
        "id": "src-1",
        "name": "源画像",
        "platform": "windows",
        "device_profile": None,
        "gpu_renderer": "ANGLE (Intel)",
        "screen_width": 1920,
        "screen_height": 1080,
        "fingerprint_options": {},
    }
    base.update(overrides)
    return base


# ── Attribution ──────────────────────────────────────────────────────────────


def test_creepjs_lies_map_to_noise_candidate():
    found = attribute(profile(), make_report(("creepjs", "fail")))
    assert len(found["candidates"]) == 1
    candidate = found["candidates"][0]
    assert candidate.knob == evolution.KNOB_NOISE
    assert candidate.to_value is False
    assert candidate.targets == ["creepjs"]
    assert found["unfixable"] == []


def test_noise_candidate_merges_canvas_audio_and_creepjs():
    report = make_report(("creepjs", "fail"), ("local_canvas", "warn"), ("local_audio", "fail"))
    found = attribute(profile(), report)
    assert len(found["candidates"]) == 1
    assert set(found["candidates"][0].targets) == {"creepjs", "local_canvas", "local_audio"}


def test_noise_already_off_leaves_creepjs_unfixable():
    found = attribute(
        profile(fingerprint_options={"noise": False}),
        make_report(("creepjs", "fail")),
    )
    assert found["candidates"] == []
    assert len(found["unfixable"]) == 1
    assert "内核层" in found["unfixable"][0]["reason"]


def test_browserscan_maps_to_storage_and_noise():
    found = attribute(profile(), make_report(("browserscan", "fail")))
    knobs = {c.knob for c in found["candidates"]}
    assert knobs == {evolution.KNOB_STORAGE, evolution.KNOB_NOISE}
    storage = next(c for c in found["candidates"] if c.knob == evolution.KNOB_STORAGE)
    assert storage.to_value == 50000 and storage.from_value is None


def test_local_storage_maps_to_quota_only_when_not_already_set():
    found = attribute(
        profile(fingerprint_options={"storage_quota_mb": 50000}),
        make_report(("local_storage", "warn")),
    )
    assert all(c.knob != evolution.KNOB_STORAGE for c in found["candidates"])


def test_local_gpu_maps_to_a_different_device_template():
    found = attribute(profile(), make_report(("local_gpu", "fail")))
    assert len(found["candidates"]) == 1
    candidate = found["candidates"][0]
    assert candidate.knob == evolution.KNOB_TEMPLATE
    from backend import device_templates

    tpl = device_templates.get_template(candidate.to_value)
    assert tpl is not None and tpl["gpu_renderer"] != "ANGLE (Intel)"


def test_ip_reputation_items_are_labelled_unfixable():
    report = make_report(("pixelscan", "fail"), ("fingerprint", "fail"), ("iphey", "warn"))
    found = attribute(profile(), report)
    assert found["candidates"] == []
    reasons = {u["site"]: u["reason"] for u in found["unfixable"]}
    assert set(reasons) == {"pixelscan", "fingerprint", "iphey"}
    assert all("IP" in reason for reason in reasons.values())


def test_kernel_items_are_labelled_unfixable():
    found = attribute(profile(), make_report(("sannysoft", "fail"), ("local_webdriver", "fail")))
    assert found["candidates"] == []
    assert all("内核" in u["reason"] for u in found["unfixable"])


def test_pass_and_error_items_are_not_problems():
    report = make_report(("creepjs", "pass"), ("browserscan", "error"), ("pixelscan", "unknown"))
    found = attribute(profile(), report)
    assert found == {"candidates": [], "unfixable": []}


# ── Scoring ──────────────────────────────────────────────────────────────────


def _candidate(*targets: str) -> Candidate:
    return Candidate(knob=evolution.KNOB_NOISE, label="关闭指纹噪声",
                     from_value=None, to_value=False, targets=list(targets))


def test_score_improved_when_target_heals_and_nothing_regresses():
    before = make_report(("creepjs", "fail"), ("sannysoft", "pass"))
    after = make_report(("creepjs", "pass"), ("sannysoft", "pass"))
    scored = score_experiment(before, after, _candidate("creepjs"))
    assert scored["verdict"] == "improved"
    assert scored["targets"] == {"creepjs": {"from": "fail", "to": "pass"}}
    assert scored["regressions"] == []


def test_score_no_change_when_target_stays_warn():
    before = make_report(("browserscan", "warn"))
    after = make_report(("browserscan", "warn"))
    scored = score_experiment(before, after, _candidate("browserscan"))
    assert scored["verdict"] == "no_change"


def test_score_regressed_when_another_item_breaks():
    before = make_report(("creepjs", "fail"), ("sannysoft", "pass"))
    after = make_report(("creepjs", "pass"), ("sannysoft", "fail"))
    scored = score_experiment(before, after, _candidate("creepjs"))
    assert scored["verdict"] == "regressed"
    assert scored["regressions"][0]["site"] == "sannysoft"


def test_score_regressed_when_target_gets_worse():
    before = make_report(("creepjs", "warn"))
    after = make_report(("creepjs", "error"))
    scored = score_experiment(before, after, _candidate("creepjs"))
    assert scored["verdict"] == "regressed"


def test_score_local_item_disappearing_counts_as_healed():
    before = make_report(("local_canvas", "fail"))
    after = {"id": "r2", "results": []}
    scored = score_experiment(before, after, _candidate("local_canvas"))
    assert scored["verdict"] == "improved"


# ── Applying candidates ──────────────────────────────────────────────────────


def test_update_kwargs_merges_fingerprint_options():
    source = profile(fingerprint_options={"brand": "Edge", "noise": True})
    kwargs = update_kwargs(source, evolution.KNOB_NOISE, False)
    assert kwargs == {"fingerprint_options": {"brand": "Edge", "noise": False}}


def test_update_kwargs_for_template_swaps_device_fields():
    from backend import device_templates

    tpl = device_templates.list_templates()[0]
    kwargs = update_kwargs(profile(), evolution.KNOB_TEMPLATE, tpl["id"])
    assert kwargs["device_profile"] == tpl["id"]
    assert kwargs["gpu_renderer"] == tpl["gpu_renderer"]
    assert kwargs["platform"] == "windows"


def test_update_kwargs_rejects_unknown_template_and_knob():
    with pytest.raises(ValueError):
        update_kwargs(profile(), evolution.KNOB_TEMPLATE, "no-such-template")
    with pytest.raises(ValueError):
        update_kwargs(profile(), "fingerprint_seed", 42)


# ── Scheduling + lock ────────────────────────────────────────────────────────


def test_is_due():
    now = datetime.now().astimezone()
    enabled = {"evolution_enabled": 1, "evolution_interval_hours": 24}
    assert is_due(enabled, last_cycle_at=None, now=now)
    recent = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    assert not is_due(enabled, last_cycle_at=recent, now=now)
    old = (now - timedelta(hours=30)).isoformat(timespec="seconds")
    assert is_due(enabled, last_cycle_at=old, now=now)
    assert not is_due({"evolution_enabled": 0}, last_cycle_at=None, now=now)
    assert not is_due({**enabled, "deleted_at": "x"}, last_cycle_at=None, now=now)


def test_automation_lock_serializes_owners():
    lock = AutomationLock()
    assert lock.try_acquire("warmup")
    assert not lock.try_acquire("evolution")
    assert lock.try_acquire("warmup")  # same owner re-enters
    lock.release("evolution")  # not the owner: no-op
    assert lock.owner == "warmup"
    lock.release("warmup")
    assert lock.owner is None
    assert lock.try_acquire("evolution")


def test_automation_lock_truth_hook_heals_stale_owner():
    lock = AutomationLock()
    lock.try_acquire("site_check")
    lock.truth = lambda: None  # nothing is actually running
    assert lock.owner is None
    assert lock.try_acquire("evolution")


# ── Engine ───────────────────────────────────────────────────────────────────


class FakeWorld:
    """Injected engine dependencies; records every touch."""

    def __init__(self, outcomes: dict[str, CheckOutcome]):
        self.outcomes = outcomes  # profile id -> check outcome
        self.clones: list[dict] = []
        self.applied: list[tuple[str, str]] = []
        self.burned: list[str] = []
        self.proposals: list[dict] = []
        self.logs: dict[str, dict] = {}
        self.checked: list[str] = []

    def deps(self) -> EngineDeps:
        return EngineDeps(
            run_check=self.run_check,
            make_clone=self.make_clone,
            apply_change=self.apply_change,
            burn=self.burn,
            record_log=self.record_log,
            update_log=self.update_log,
            file_proposal=self.file_proposal,
        )

    async def run_check(self, prof: dict) -> CheckOutcome:
        self.checked.append(prof["id"])
        return self.outcomes[prof["id"]]

    def make_clone(self, source: dict) -> dict:
        clone = {**source, "id": f"clone-{len(self.clones) + 1}", "disposable": 1}
        self.clones.append(clone)
        return clone

    def apply_change(self, prof: dict, candidate: Candidate) -> dict:
        self.applied.append((prof["id"], candidate.knob))
        return prof

    async def burn(self, prof: dict) -> None:
        self.burned.append(prof["id"])

    def record_log(self, entry: dict) -> str:
        log_id = f"log-{len(self.logs) + 1}"
        self.logs[log_id] = dict(entry)
        return log_id

    def update_log(self, log_id: str, fields: dict) -> None:
        self.logs[log_id].update(fields)

    def file_proposal(self, payload: dict) -> str:
        self.proposals.append(payload)
        return f"prop-{len(self.proposals)}"


def engine_for(world: FakeWorld, lock: AutomationLock | None = None) -> EvolutionEngine:
    return EvolutionEngine(world.deps(), lock=lock or AutomationLock())


@pytest.mark.asyncio
async def test_cycle_clean_report_makes_no_clone():
    source = profile()
    world = FakeWorld({"src-1": CheckOutcome(make_report(("creepjs", "pass")))})
    entry = await engine_for(world).run_cycle(source, trigger="manual")
    assert entry["outcome"] == "clean"
    assert world.clones == [] and world.proposals == []


@pytest.mark.asyncio
async def test_scheduled_cycle_defers_when_window_gate_closes():
    source = profile()
    world = FakeWorld({"src-1": CheckOutcome(make_report(("creepjs", "pass")))})
    engine = EvolutionEngine(
        world.deps(), lock=AutomationLock(),
        scheduled_defer=lambda: "不在自动化允许时段内（09:00–18:00），本轮推迟",
    )
    entry = await engine.run_cycle(source, trigger="scheduled")
    assert entry["outcome"] == "deferred"
    assert "时段" in entry["summary"]
    assert world.checked == []  # no check (and no browser) ever ran


@pytest.mark.asyncio
async def test_manual_cycle_ignores_window_gate():
    source = profile()
    world = FakeWorld({"src-1": CheckOutcome(make_report(("creepjs", "pass")))})
    engine = EvolutionEngine(
        world.deps(), lock=AutomationLock(),
        scheduled_defer=lambda: "不在自动化允许时段内（09:00–18:00），本轮推迟",
    )
    entry = await engine.run_cycle(source, trigger="manual")
    assert entry["outcome"] == "clean"
    assert world.checked == ["src-1"]


@pytest.mark.asyncio
async def test_cycle_win_becomes_proposal_and_clone_is_burned():
    source = profile()
    world = FakeWorld({
        "src-1": CheckOutcome(make_report(("creepjs", "fail"))),
        "clone-1": CheckOutcome(make_report(("creepjs", "pass"), report_id="r2")),
    })
    entry = await engine_for(world).run_cycle(source, trigger="scheduled")

    assert entry["outcome"] == "experiments"
    # Only the clone was ever changed or burned; the source was only checked.
    assert world.applied == [("clone-1", evolution.KNOB_NOISE)]
    assert world.burned == ["clone-1"]
    assert world.checked == ["src-1", "clone-1"]
    assert len(world.proposals) == 1
    proposal = world.proposals[0]
    assert proposal["profile_id"] == "src-1" and proposal["knob"] == evolution.KNOB_NOISE
    assert proposal["evidence"]["targets"] == {"creepjs": {"from": "fail", "to": "pass"}}
    experiment = entry["detail"]["experiments"][0]
    assert experiment["verdict"] == "improved" and experiment["proposal_id"] == "prop-1"


@pytest.mark.asyncio
async def test_cycle_no_improvement_files_no_proposal_but_still_burns():
    source = profile()
    world = FakeWorld({
        "src-1": CheckOutcome(make_report(("creepjs", "fail"))),
        "clone-1": CheckOutcome(make_report(("creepjs", "fail"))),
    })
    entry = await engine_for(world).run_cycle(source, trigger="manual")
    assert entry["outcome"] == "experiments"
    assert world.proposals == []
    assert world.burned == ["clone-1"]
    assert entry["detail"]["experiments"][0]["verdict"] == "no_change"


@pytest.mark.asyncio
async def test_cycle_burns_clone_even_when_clone_check_errors():
    source = profile()
    world = FakeWorld({
        "src-1": CheckOutcome(make_report(("creepjs", "fail"))),
        "clone-1": CheckOutcome(None, "启动失败"),
    })
    entry = await engine_for(world).run_cycle(source, trigger="manual")
    assert world.burned == ["clone-1"]
    assert world.proposals == []
    assert entry["detail"]["experiments"][0]["verdict"] == "error"


@pytest.mark.asyncio
async def test_cycle_defers_when_seat_is_taken():
    source = profile()
    world = FakeWorld({"src-1": CheckOutcome(None, "session limit reached：授权并发已满")})
    entry = await engine_for(world).run_cycle(source, trigger="scheduled")
    assert entry["outcome"] == "deferred"
    assert world.clones == []


@pytest.mark.asyncio
async def test_cycle_defers_when_lock_is_held_by_another_automation():
    source = profile()
    world = FakeWorld({"src-1": CheckOutcome(make_report(("creepjs", "pass")))})
    lock = AutomationLock()
    assert lock.try_acquire("warmup")
    entry = await engine_for(world, lock).run_cycle(source, trigger="scheduled")
    assert entry["outcome"] == "deferred"
    assert world.checked == []  # the source was never even checked


@pytest.mark.asyncio
async def test_cycle_unfixable_only_problems_make_no_clone():
    source = profile()
    world = FakeWorld({"src-1": CheckOutcome(make_report(("pixelscan", "fail")))})
    entry = await engine_for(world).run_cycle(source, trigger="manual")
    assert entry["outcome"] == "unfixable_only"
    assert world.clones == []
    assert entry["detail"]["unfixable"][0]["site"] == "pixelscan"


# ── Persistence ──────────────────────────────────────────────────────────────


def test_proposals_and_logs_round_trip(tmp_db):
    proposal = db.create_evolution_proposal(
        "p1", profile_name="甲", knob=evolution.KNOB_NOISE, label="关闭指纹噪声",
        from_value=None, to_value=False, targets=["creepjs"],
        evidence={"verdict": "improved"},
    )
    assert proposal["status"] == "pending" and proposal["to_value"] is False
    assert db.list_evolution_proposals(status="pending")[0]["id"] == proposal["id"]
    assert db.list_evolution_proposals(status="applied") == []

    decided = db.decide_evolution_proposal(proposal["id"], "applied")
    assert decided["status"] == "applied" and decided["decided_at"]
    assert db.decide_evolution_proposal(proposal["id"], "dismissed") is None

    db.record_evolution_log(
        profile_id="p1", profile_name="甲", started_at="2026-10-22T01:00:00+08:00",
        finished_at="2026-10-22T01:10:00+08:00", trigger="scheduled",
        outcome="deferred", summary="推迟", detail={},
    )
    db.record_evolution_log(
        profile_id="p1", profile_name="甲", started_at="2026-10-22T02:00:00+08:00",
        finished_at="2026-10-22T02:10:00+08:00", trigger="scheduled",
        outcome="experiments", summary="完成", detail={"experiments": []},
    )
    logs = db.list_evolution_logs(profile_id="p1")
    assert [entry["outcome"] for entry in logs] == ["experiments", "deferred"]
    # Deferred cycles do not reset the cadence clock.
    assert db.last_evolution_cycle_at("p1") == "2026-10-22T02:00:00+08:00"


def test_profile_evolution_fields_round_trip(tmp_db):
    created = db.create_profile(name="Evo", evolution_enabled=True, evolution_interval_hours=48)
    assert created["evolution_enabled"] == 1 and created["evolution_interval_hours"] == 48
    updated = db.update_profile(created["id"], evolution_enabled=False)
    assert updated["evolution_enabled"] == 0 and updated["evolution_interval_hours"] == 48


# ── API ──────────────────────────────────────────────────────────────────────


def _seed_proposal(profile_id: str, **kwargs) -> dict:
    defaults = dict(
        profile_name="甲", knob=evolution.KNOB_NOISE, label="关闭指纹噪声",
        from_value=None, to_value=False, targets=["creepjs"],
        evidence={"verdict": "improved", "targets": {"creepjs": {"from": "fail", "to": "pass"}}},
    )
    defaults.update(kwargs)
    return db.create_evolution_proposal(profile_id, **defaults)


def test_api_proposal_approve_applies_through_update_path(app_client: TestClient):
    created = app_client.post(
        "/api/profiles",
        json={"name": "待进化", "fingerprint_options": {"noise": True}},
    ).json()
    pid = created["id"]
    assert created["fingerprint_options"]["noise"] is True
    proposal = _seed_proposal(pid, from_value=True)

    listed = app_client.get("/api/evolution/proposals", params={"status": "pending"}).json()
    assert [p["id"] for p in listed] == [proposal["id"]]

    resp = app_client.post(f"/api/evolution/proposals/{proposal['id']}/approve")
    assert resp.status_code == 200 and resp.json()["status"] == "applied"

    updated = app_client.get(f"/api/profiles/{pid}").json()
    assert updated["fingerprint_options"]["noise"] is False

    # A decided proposal cannot be decided again.
    assert app_client.post(f"/api/evolution/proposals/{proposal['id']}/approve").status_code == 409
    assert app_client.post(f"/api/evolution/proposals/{proposal['id']}/dismiss").status_code == 409


def test_api_proposal_dismiss_and_missing(app_client: TestClient):
    pid = app_client.post("/api/profiles", json={"name": "待进化"}).json()["id"]
    proposal = _seed_proposal(pid)
    resp = app_client.post(f"/api/evolution/proposals/{proposal['id']}/dismiss")
    assert resp.status_code == 200 and resp.json()["status"] == "dismissed"
    assert app_client.post("/api/evolution/proposals/nope/approve").status_code == 404
    assert app_client.post("/api/evolution/proposals/nope/dismiss").status_code == 404


def test_api_proposal_approve_template_knob(app_client: TestClient):
    pid = app_client.post("/api/profiles", json={"name": "待进化"}).json()["id"]
    from backend import device_templates

    tpl = device_templates.list_templates()[0]
    proposal = _seed_proposal(pid, knob=evolution.KNOB_TEMPLATE, to_value=tpl["id"], targets=["local_gpu"])
    resp = app_client.post(f"/api/evolution/proposals/{proposal['id']}/approve")
    assert resp.status_code == 200
    updated = app_client.get(f"/api/profiles/{pid}").json()
    assert updated["device_profile"] == tpl["id"]
    assert updated["gpu_renderer"] == tpl["gpu_renderer"]


def test_api_logs_status_and_profile_fields(app_client: TestClient):
    created = app_client.post(
        "/api/profiles",
        json={"name": "进化画像", "evolution_enabled": True, "evolution_interval_hours": 12},
    ).json()
    assert created["evolution_enabled"] is True and created["evolution_interval_hours"] == 12

    db.record_evolution_log(
        profile_id=created["id"], profile_name="进化画像",
        started_at="2026-10-22T02:00:00+08:00", finished_at="2026-10-22T02:10:00+08:00",
        trigger="manual", outcome="experiments", summary="完成", detail={"experiments": []},
    )
    logs = app_client.get("/api/evolution/logs", params={"profile_id": created["id"]}).json()
    assert len(logs) == 1 and logs[0]["outcome"] == "experiments"

    status = app_client.get("/api/evolution/status").json()
    assert status["busy"] is False and status["pending_proposals"] == 0


def test_api_manual_run_starts_a_cycle(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from backend import main

    pid = app_client.post("/api/profiles", json={"name": "手动进化"}).json()["id"]
    started: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main, "_start_evolution_task",
        lambda prof, trigger: started.append((prof["id"], trigger)) or True,
    )
    resp = app_client.post(f"/api/profiles/{pid}/evolution/run")
    assert resp.status_code == 200 and resp.json()["started"] is True
    assert started == [(pid, "manual")]

    monkeypatch.setattr(main, "_evolution_busy", lambda: True)
    assert app_client.post(f"/api/profiles/{pid}/evolution/run").status_code == 409
    assert app_client.post("/api/profiles/nope/evolution/run").status_code == 404


@pytest.mark.asyncio
async def test_scheduler_tick_starts_only_due_profiles(tmp_db, monkeypatch: pytest.MonkeyPatch):
    from backend import main

    due = db.create_profile(name="到期", evolution_enabled=1)
    db.create_profile(name="没开", evolution_enabled=0)
    started: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main, "_start_evolution_task",
        lambda prof, trigger: started.append((prof["id"], trigger)) or True,
    )
    await main._evolution_tick()
    assert started == [(due["id"], "scheduled")]

    # A just-finished cycle pushes the next one a full interval out.
    now = datetime.now().astimezone()
    db.record_evolution_log(
        profile_id=due["id"], profile_name="到期",
        started_at=now.isoformat(timespec="seconds"),
        finished_at=now.isoformat(timespec="seconds"),
        trigger="scheduled", outcome="experiments", summary="完成", detail={},
    )
    started.clear()
    await main._evolution_tick()
    assert started == []


def test_experiment_clone_never_carries_account_cookies(tmp_db):
    from backend import database as db
    from backend import main

    source = db.create_profile(
        name="Seller", fingerprint_seed=4242, platform="macos",
        cookies_json='[{"name":"session-id","value":"secret","domain":".amazon.com","path":"/"}]',
        account_platform="Amazon",
    )

    clone = main._evo_make_clone(db.get_profile(source["id"]))

    assert clone["fingerprint_seed"] == 4242
    assert not clone.get("cookies_json")
