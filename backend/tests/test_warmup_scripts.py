"""AI warm-up scripts (AI 养号编排）: compiler, LLM client, storage, runner
selection and API. The LLM is always mocked — no network, no real key."""

from __future__ import annotations

import json
import random
import time
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import httpx
import pytest

from backend import database as db
from backend import llm_client, main, warmup as wu, warmup_script as ws


def _profile(**overrides):
    base = {
        "id": "prof-script",
        "name": "Scripted",
        "locale": "en-US",
        "timezone": "America/New_York",
        "warmup_enabled": 1,
        "warmup_daily_max": 1,
        "warmup_targets": ["youtube", "google"],
        "warmup_persona": "32 岁，喜欢摄影和手冲咖啡",
        "created_at": "2026-10-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# ── Compiler ────────────────────────────────────────────────────────────────


def test_compile_target_intents_build_catalog_urls():
    steps = ws.compile_intents(_profile(), [
        {"type": "target", "platform": "youtube", "query": "lofi beats", "dwell": "long", "follow": True},
        {"type": "target", "platform": "google", "query": "weather tomorrow", "dwell": "short"},
    ])
    assert [s["platform"] for s in steps] == ["youtube", "google"]
    first = steps[0]
    assert first["url"] == "https://www.youtube.com/"
    assert first["search_query"] == "lofi beats"
    assert "search_query=lofi+beats" in first["search_url"]
    assert first["follow_link"] is True and first["dwell"] == "long"
    assert first["dwell_scale"] == ws.DWELL_SCALES["long"]
    assert steps[1]["follow_link"] is False


def test_compile_drops_unknown_and_unchosen_platforms():
    steps = ws.compile_intents(_profile(), [
        {"type": "target", "platform": "tiktok", "query": "x"},
        {"type": "target", "platform": "amazon", "query": "not chosen by profile"},
        {"type": "target", "platform": "google", "query": "kept"},
        {"type": "teleport", "platform": "google"},
        {"type": "target"},
        "not-a-dict",
    ])
    assert [s.get("platform") for s in steps] == ["google"]


def test_compile_query_is_sanitized():
    steps = ws.compile_intents(_profile(), [
        {"type": "target", "platform": "google", "query": "  a\x00b\t c   d  "},
    ])
    assert steps[0]["search_query"] == "a b c d"
    long_q = "word " * 40
    steps = ws.compile_intents(_profile(), [
        {"type": "target", "platform": "google", "query": long_q},
    ])
    assert len(steps[0]["search_query"]) <= ws.QUERY_MAX_LEN
    assert ws.sanitize_query("") is None and ws.sanitize_query(None) is None
    assert ws.sanitize_query(123) is None


def test_compile_no_search_platform_degrades_to_home_only():
    profile = _profile(warmup_targets=["facebook"])
    steps = ws.compile_intents(profile, [
        {"type": "target", "platform": "facebook", "query": "anything", "dwell": "medium"},
    ])
    assert len(steps) == 1
    assert steps[0]["url"] == "https://www.facebook.com/"
    assert "search_url" not in steps[0] and "search_query" not in steps[0]


def test_compile_generic_intents_cycle_locale_sites():
    steps = ws.compile_intents(_profile(), [{"type": "generic"}] * 3)
    sites = wu.GENERIC_SITES["en"]
    assert [s["url"] for s in steps] == sites[:3]
    assert all(s["kind"] == "generic" and s["dwell"] == "medium" for s in steps)


def test_compile_output_is_isomorphic_with_template_plan():
    profile = _profile()
    compiled = ws.compile_intents(profile, [
        {"type": "target", "platform": "youtube", "query": "jazz", "dwell": "long", "follow": True},
        {"type": "generic", "dwell": "short"},
    ])
    template = wu.build_session_plan(profile, random.Random(5))
    allowed_hosts = set()
    for entry in wu.TARGET_CATALOG.values():
        allowed_hosts.update(entry["domains"].values())
    for lang_sites in wu.GENERIC_SITES.values():
        allowed_hosts.update(urlparse(u).hostname for u in lang_sites)
    for steps in (compiled, template):
        for step in steps:
            assert step["kind"] in ("target", "generic")
            assert urlparse(step["url"]).hostname in allowed_hosts
            assert isinstance(step["follow_link"], bool)
            if step["kind"] == "target":
                assert step["platform"] in wu.TARGET_CATALOG
    assert len(compiled) == 2 and compiled[0]["dwell_scale"] > compiled[1]["dwell_scale"]


def test_compile_caps_steps_and_rejects_non_list():
    intents = [{"type": "generic"}] * (ws.MAX_SCRIPT_STEPS + 5)
    assert len(ws.compile_intents(_profile(), intents)) == ws.MAX_SCRIPT_STEPS
    assert ws.compile_intents(_profile(), None) == []
    assert ws.compile_intents(_profile(), {"type": "generic"}) == []


# ── Payload validation + rotation ───────────────────────────────────────────


def test_validate_scripts_payload_shapes():
    good = {"scripts": [{"theme": " t ", "intents": []}, {"intents": []}, {"theme": 1, "intents": "no"}, "junk"]}
    out = ws.validate_scripts_payload(good)
    assert out == [{"theme": "t", "intents": []}, {"theme": "", "intents": []}]
    assert ws.validate_scripts_payload([{"theme": "a", "intents": []}])[0]["theme"] == "a"
    assert ws.validate_scripts_payload({"nope": 1}) == []
    assert ws.validate_scripts_payload(None) == []


def test_rotation_walks_the_whole_batch():
    batch = [{"id": f"s{i}", "steps": []} for i in range(5)]
    start = date(2026, 10, 20)
    picked = [ws.pick_script_for_date(batch, start + timedelta(days=k))["id"] for k in range(5)]
    assert sorted(picked) == [f"s{i}" for i in range(5)]
    assert ws.pick_script_for_date(batch, start) is ws.pick_script_for_date(batch, start)
    assert ws.pick_script_for_date([], start) is None


def test_select_plan_filters_done_targets_and_falls_back():
    batch = [{
        "id": "only",
        "steps": [
            {"kind": "target", "platform": "youtube", "url": "https://www.youtube.com/", "follow_link": False},
            {"kind": "generic", "url": "https://www.bbc.com/", "follow_link": False},
        ],
    }]
    selected = ws.select_plan(batch, on_date=date(2026, 10, 22), targets_done={"youtube"})
    assert selected is not None
    steps, script_id = selected
    assert script_id == "only" and [s["kind"] for s in steps] == ["generic"]
    only_targets = [{"id": "t", "steps": [batch[0]["steps"][0]]}]
    assert ws.select_plan(only_targets, on_date=date(2026, 10, 22), targets_done={"youtube"}) is None
    assert ws.select_plan([], on_date=date(2026, 10, 22)) is None
    assert ws.select_plan([{"id": "x", "steps": []}], on_date=date(2026, 10, 22)) is None


# ── Storage: migration, persona, batch lifecycle ────────────────────────────


def _script_items(n=5):
    return [
        {
            "theme": f"主题{i}",
            "intents": [{"type": "generic", "dwell": "short"}],
            "steps": [{"kind": "generic", "url": "https://www.bbc.com/", "follow_link": False}],
        }
        for i in range(n)
    ]


def test_persona_and_batch_round_trip(tmp_db):
    profile = db.create_profile(name="Persona", warmup_persona="爱摄影的上班族")
    assert profile["warmup_persona"] == "爱摄影的上班族"
    updated = db.update_profile(profile["id"], warmup_persona="改追星了")
    assert updated["warmup_persona"] == "改追星了"

    created = db.create_warmup_script_batch(
        profile["id"], batch_id="batch-1", model="m1", persona="爱摄影的上班族",
        scripts=_script_items(),
    )
    assert len(created) == 5 and all(s["status"] == "draft" for s in created)
    assert created[0]["intents"] == [{"type": "generic", "dwell": "short"}]
    assert db.get_approved_warmup_batch(profile["id"]) == []

    assert db.set_warmup_batch_status(profile["id"], "batch-1", "approved") == 5
    approved = db.get_approved_warmup_batch(profile["id"])
    assert [s["theme"] for s in approved] == [f"主题{i}" for i in range(5)]
    # Deciding twice is a no-op; a newer approved batch archives the old one.
    assert db.set_warmup_batch_status(profile["id"], "batch-1", "approved") == 0
    db.create_warmup_script_batch(
        profile["id"], batch_id="batch-2", model="m1", persona=None, scripts=_script_items(2),
    )
    assert db.set_warmup_batch_status(profile["id"], "batch-2", "approved") == 2
    statuses = {s["batch_id"]: s["status"] for s in db.list_warmup_scripts(profile["id"])}
    assert statuses == {"batch-1": "archived", "batch-2": "approved"}
    assert len(db.get_approved_warmup_batch(profile["id"])) == 2


def test_reject_batch(tmp_db):
    profile = db.create_profile(name="Reject")
    db.create_warmup_script_batch(
        profile["id"], batch_id="b", model=None, persona=None, scripts=_script_items(3),
    )
    assert db.set_warmup_batch_status(profile["id"], "b", "rejected") == 3
    assert db.get_approved_warmup_batch(profile["id"]) == []
    assert db.set_warmup_batch_status(profile["id"], "b", "approved") == 0


# ── LLM client ──────────────────────────────────────────────────────────────

GOOD_SCRIPTS = {
    "scripts": [
        {
            "theme": f"主题{i}",
            "intents": [
                {"type": "target", "platform": "youtube", "query": "lofi beats", "dwell": "long", "follow": True},
                {"type": "target", "platform": "google", "query": "weather tomorrow", "dwell": "short"},
                {"type": "generic", "dwell": "medium", "follow": True},
            ],
        }
        for i in range(5)
    ]
}


def _configure(db_module=db):
    llm_client.save_config(
        db_module.set_setting,
        base_url="https://llm.example/v1/",
        model="test-model",
        api_key="sk-secret-key",
    )


def _transport(payload, calls=None, fail_first=False):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer sk-secret-key"
        if fail_first and calls is not None and len(calls) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})
    return httpx.MockTransport(handler)


def test_llm_config_is_encrypted_and_write_only(tmp_db):
    _configure()
    stored = db.get_setting(llm_client.SETTING_API_KEY)
    assert stored and stored.startswith("enc::") and "sk-secret-key" not in stored
    status = llm_client.config_status(db.get_setting)
    assert status == {
        "configured": True,
        "base_url": "https://llm.example/v1",
        "model": "test-model",
        "has_api_key": True,
        "executor_model": None,
        "executor_effort": None,
    }
    assert "sk-secret-key" not in json.dumps(status)
    # Saving without a key keeps the stored one.
    llm_client.save_config(db.set_setting, base_url="https://llm.example/v1", model="m2")
    assert llm_client.read_config(db.get_setting)["api_key"] == "sk-secret-key"
    assert llm_client.read_config(db.get_setting)["model"] == "m2"


async def test_generate_batch_compiles_and_returns_five(tmp_db):
    _configure()
    calls: list = []
    result = await llm_client.generate_batch(
        _profile(), get_setting=db.get_setting, transport=_transport(GOOD_SCRIPTS, calls),
    )
    assert len(calls) == 1
    assert result["model"] == "test-model"
    assert result["persona"] == "32 岁，喜欢摄影和手冲咖啡"
    assert len(result["scripts"]) == 5
    first = result["scripts"][0]
    assert first["theme"] == "主题0" and len(first["steps"]) == 3
    assert first["steps"][0]["search_query"] == "lofi beats"


async def test_generate_retries_once_on_garbage(tmp_db):
    _configure()
    calls: list = []
    result = await llm_client.generate_batch(
        _profile(), get_setting=db.get_setting,
        transport=_transport(GOOD_SCRIPTS, calls, fail_first=True),
    )
    assert len(calls) == 2 and len(result["scripts"]) == 5


async def test_generate_garbage_raises_and_stores_nothing(tmp_db):
    _configure()
    profile = db.create_profile(name="Garbage", warmup_targets=["google"])
    with pytest.raises(llm_client.LlmGenerationError):
        await llm_client.generate_batch(
            profile, get_setting=db.get_setting,
            transport=_transport({"scripts": "nope"}),
        )
    assert db.list_warmup_scripts(profile["id"]) == []


async def test_generate_requires_configuration(tmp_db):
    with pytest.raises(llm_client.LlmNotConfiguredError):
        await llm_client.generate_batch(_profile(), get_setting=db.get_setting)


def test_parse_scripts_tolerates_code_fences():
    text = "```json\n" + json.dumps(GOOD_SCRIPTS) + "\n```"
    scripts = llm_client.parse_scripts(text)
    assert len(scripts) == 5 and scripts[0]["theme"] == "主题0"


# ── Runner selection ────────────────────────────────────────────────────────


class _Page:
    def __init__(self):
        self.visited: list[str] = []
        self.mouse = SimpleNamespace(
            move=AsyncMock(), down=AsyncMock(), up=AsyncMock(), wheel=AsyncMock()
        )
        self.keyboard = SimpleNamespace(type=AsyncMock(), press=AsyncMock())

    async def goto(self, url, **_kw):
        self.visited.append(url)

    async def evaluate(self, js):
        return []

    async def close(self):
        pass


class _Mgr:
    def __init__(self, page):
        self.running: dict = {}
        self._launching: set = set()
        self.page = page

    async def launch(self, profile, launch_mode="debug", **kwargs):
        context = SimpleNamespace(new_page=AsyncMock(return_value=self.page))
        return SimpleNamespace(context=context)

    async def stop(self, profile_id, reason=None):
        pass


async def test_runner_uses_script_plan_and_records_script_id():
    steps = ws.compile_intents(_profile(), [
        {"type": "target", "platform": "youtube", "query": "jazz", "dwell": "long", "follow": False},
        {"type": "generic", "dwell": "short", "follow": False},
    ])
    page = _Page()
    records: list[dict] = []
    result = await wu.run_warmup(
        _profile(), browser_mgr=_Mgr(page), record_run=records.append,
        time_scale=0, plan_override=steps, script_id="script-42",
    )
    assert result["status"] == "ok"
    assert page.visited[0] == "https://www.youtube.com/"
    assert "search_query=jazz" in page.visited[1]
    assert records[0]["detail"]["script_id"] == "script-42"
    assert records[0]["detail"]["targets"] == ["youtube"]


async def test_runner_template_path_records_null_script_id():
    page = _Page()
    records: list[dict] = []
    result = await wu.run_warmup(
        _profile(), browser_mgr=_Mgr(page), record_run=records.append, time_scale=0,
    )
    assert result["status"] == "ok"
    assert records[0]["detail"]["script_id"] is None


def test_main_script_plan_selection(tmp_db):
    profile = db.create_profile(
        name="Selector", locale="en-US", warmup_targets=["youtube"],
        warmup_persona="p",
    )
    assert main._approved_script_plan(profile, set()) is None
    steps = ws.compile_intents(profile, [
        {"type": "target", "platform": "youtube", "query": "jazz"},
        {"type": "generic"},
    ])
    db.create_warmup_script_batch(
        profile["id"], batch_id="sel-1", model="m", persona="p",
        scripts=[{"theme": "t", "intents": [], "steps": steps}],
    )
    assert main._approved_script_plan(profile, set()) is None  # still draft
    db.set_warmup_batch_status(profile["id"], "sel-1", "approved")
    selected = main._approved_script_plan(profile, set())
    assert selected is not None
    plan, script_id = selected
    assert plan == steps and script_id
    # All targets done + script has a generic step → generic-only plan.
    plan2, _ = main._approved_script_plan(profile, {"youtube"})
    assert [s["kind"] for s in plan2] == ["generic"]


# ── API surface ─────────────────────────────────────────────────────────────


def _wait_for_generation(client, pid: str, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = client.get(f"/api/profiles/{pid}/warmup/scripts").json()
        if not info["generating"]:
            return info
        time.sleep(0.05)
    raise AssertionError("generation did not finish in time")


def test_llm_settings_api(app_client):
    status = app_client.get("/api/settings/llm").json()
    assert status["configured"] is False and status["has_api_key"] is False
    updated = app_client.put("/api/settings/llm", json={
        "base_url": "https://llm.example/v1", "model": "m1", "api_key": "sk-hidden",
    }).json()
    assert updated["configured"] is True and updated["has_api_key"] is True
    assert "sk-hidden" not in json.dumps(updated)
    # Updating without a key keeps it.
    updated = app_client.put("/api/settings/llm", json={
        "base_url": "https://llm.example/v1", "model": "m2",
    }).json()
    assert updated["model"] == "m2" and updated["has_api_key"] is True
    # Executor model round-trips independently of the generation model.
    assert updated["executor_model"] is None and updated["executor_effort"] is None
    updated = app_client.put("/api/settings/llm", json={
        "base_url": "https://llm.example/v1", "model": "m2",
        "executor_model": "claude-haiku-5-5", "executor_effort": "high",
    }).json()
    assert updated["executor_model"] == "claude-haiku-5-5"
    assert updated["executor_effort"] == "high"
    assert llm_client.read_executor_config(db.get_setting) == {
        "model": "claude-haiku-5-5", "effort": "high",
    }


def test_scripts_api_flow(app_client, monkeypatch):
    pid = app_client.post("/api/profiles", json={
        "name": "Script API", "warmup_targets": ["youtube", "google"],
        "warmup_persona": "爱摄影",
    }).json()["id"]

    info = app_client.get(f"/api/profiles/{pid}/warmup/scripts").json()
    assert info["llm_configured"] is False and info["batches"] == []
    blocked = app_client.post(f"/api/profiles/{pid}/warmup/scripts/generate")
    assert blocked.status_code == 400 and "尚未配置 LLM" in blocked.json()["detail"]

    async def fake_generate(profile, *, get_setting):
        return {
            "model": "fake-model",
            "persona": profile.get("warmup_persona"),
            "scripts": [
                {
                    "theme": f"主题{i}",
                    "intents": [{"type": "target", "platform": "youtube", "query": "jazz"}],
                    "steps": ws.compile_intents(profile, [
                        {"type": "target", "platform": "youtube", "query": "jazz", "dwell": "long"},
                        {"type": "generic", "dwell": "short"},
                    ]),
                }
                for i in range(5)
            ],
        }

    monkeypatch.setattr(main.llm_client, "generate_batch", fake_generate)
    app_client.put("/api/settings/llm", json={
        "base_url": "https://llm.example/v1", "model": "fake-model", "api_key": "sk-x",
    })
    started = app_client.post(f"/api/profiles/{pid}/warmup/scripts/generate")
    assert started.status_code == 200 and started.json()["started"] is True

    info = _wait_for_generation(app_client, pid)
    assert info["llm_configured"] is True
    assert info["last_generation"]["status"] == "done"
    assert len(info["batches"]) == 1
    batch = info["batches"][0]
    assert batch["status"] == "draft" and len(batch["scripts"]) == 5
    first_step = batch["scripts"][0]["steps"][0]
    assert first_step["platform_name"] == "YouTube"
    assert first_step["search_query"] == "jazz" and first_step["dwell"] == "long"

    batch_id = batch["batch_id"]
    approved = app_client.post(
        f"/api/profiles/{pid}/warmup/scripts/batches/{batch_id}/approve"
    )
    assert approved.status_code == 200 and approved.json()["count"] == 5
    info = app_client.get(f"/api/profiles/{pid}/warmup/scripts").json()
    assert info["batches"][0]["status"] == "approved"
    # A decided batch cannot be decided again.
    again = app_client.post(f"/api/profiles/{pid}/warmup/scripts/batches/{batch_id}/reject")
    assert again.status_code == 404
    assert app_client.get("/api/profiles/nope/warmup/scripts").status_code == 404
