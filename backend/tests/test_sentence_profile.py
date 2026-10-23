"""One-sentence profile creation （一句话建号）.

The parser (LLM or keyword fallback) only produces a white-listed spec;
assembly is deterministic over the trusted tables; the confirm endpoint
re-validates everything the client sends back. These tests pin the whole
chain: spec schema, rule fallback honesty, assembly mapping, template
race handling, and the draft/confirm API round-trip.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from backend import database as db
from backend import device_templates, llm_client, sentence_profile as sp
from backend import warmup


# ── validate_spec ────────────────────────────────────────────────────────


def test_validate_spec_accepts_full_payload():
    spec, warnings = sp.validate_spec({
        "country": "US", "city": "Seattle",
        "interests": ["camping", "photography"],
        "persona_notes": "周末常去国家公园", "purpose": "日常购物",
        "disposable": True, "invented_field": "drop me",
    })
    assert warnings == []
    assert spec == {
        "country": "US", "city": "Seattle",
        "interests": ["camping", "photography"],
        "persona_notes": "周末常去国家公园", "purpose": "日常购物",
        "disposable": True,
    }


def test_validate_spec_normalizes_chinese_city_and_lowercase_country():
    spec, _ = sp.validate_spec({"country": "us", "city": "西雅图"})
    assert spec["country"] == "US" and spec["city"] == "Seattle"


def test_validate_spec_rejects_country_outside_table():
    spec, _ = sp.validate_spec({"country": "XX"})
    assert spec is None
    spec, _ = sp.validate_spec({"city": "Seattle"})
    assert spec is None
    spec, _ = sp.validate_spec("not a dict")
    assert spec is None


def test_validate_spec_drops_unknown_city_with_warning():
    spec, warnings = sp.validate_spec({"country": "US", "city": "Springfield"})
    assert spec["city"] is None
    assert any("Springfield" in w and "未收录" in w for w in warnings)


def test_validate_spec_drops_out_of_table_interests_keeps_persona_notes():
    spec, warnings = sp.validate_spec({
        "country": "JP",
        "interests": ["gaming", "skydiving", "gaming", 42],
        "persona_notes": "喜欢跳伞",
    })
    assert spec["interests"] == ["gaming"]
    assert spec["persona_notes"] == "喜欢跳伞"
    assert any("兴趣" in w for w in warnings)


def test_validate_spec_truncates_free_text_and_caps_interests():
    spec, _ = sp.validate_spec({
        "country": "JP",
        "interests": list(sp.INTERESTS) + ["camping"],
        "persona_notes": "人" * 200,
        "purpose": "用" * 100,
    })
    assert len(spec["interests"]) == sp.MAX_INTERESTS
    assert len(spec["persona_notes"]) == 80
    assert len(spec["purpose"]) == 40


def test_validate_spec_non_bool_disposable_is_ignored():
    spec, _ = sp.validate_spec({"country": "JP", "disposable": "yes"})
    assert spec["disposable"] is False


# ── rule fallback parser ─────────────────────────────────────────────────


def test_rules_parse_canonical_sentence():
    spec, warnings = sp.parse_sentence_rules("建个美国号，西雅图，平时喜欢露营和摄影")
    assert spec["country"] == "US"
    assert spec["city"] == "Seattle"
    assert spec["interests"] == ["camping", "photography"]
    assert spec["persona_notes"] is None and spec["purpose"] is None
    assert warnings == []


def test_rules_parse_english_keywords():
    spec, _ = sp.parse_sentence_rules("Make a Japan profile in Tokyo, gaming fan")
    assert spec["country"] == "JP" and spec["city"] == "Tokyo"
    assert spec["interests"] == ["gaming"]


def test_rules_parse_city_alone_implies_country():
    spec, _ = sp.parse_sentence_rules("建个东京的号")
    assert spec["country"] == "JP" and spec["city"] == "Tokyo"


def test_rules_parse_synonym_interests():
    spec, _ = sp.parse_sentence_rules("来个日本号，平时爱拍照、撸铁")
    assert spec["interests"] == ["photography", "fitness"]


def test_rules_parse_multiple_countries_is_422():
    with pytest.raises(sp.SentenceParseError) as excinfo:
        sp.parse_sentence_rules("美国和日本各来一个")
    assert "多个国家" in str(excinfo.value)


def test_rules_parse_indonesia_is_not_india_ambiguity():
    spec, _ = sp.parse_sentence_rules("来个印度尼西亚号")
    assert spec["country"] == "ID"


def test_rules_parse_region_word_is_not_a_country():
    with pytest.raises(sp.SentenceParseError):
        sp.parse_sentence_rules("建个北美号")


def test_rules_parse_empty_and_punctuation_only():
    with pytest.raises(sp.SentenceParseError):
        sp.parse_sentence_rules("")
    with pytest.raises(sp.SentenceParseError):
        sp.parse_sentence_rules("，。！？")


def test_rules_parse_disposable_keyword_and_quantity_warning():
    spec, warnings = sp.parse_sentence_rules("建三个一次性的美国号")
    assert spec["disposable"] is True
    assert any("一次只建一个" in w for w in warnings)


# ── assembly ─────────────────────────────────────────────────────────────


def _spec(**overrides) -> dict:
    base = {
        "country": "US", "city": "Seattle",
        "interests": ["camping", "photography"],
        "persona_notes": None, "purpose": None, "disposable": False,
    }
    base.update(overrides)
    return base


def test_assemble_city_overrides_country_default_timezone():
    result = sp.assemble_spec(_spec(), sentence="建个美国号，西雅图", used_template_ids=set())
    assembled = result["assembled"]
    assert assembled["timezone"] == "America/Los_Angeles"  # not America/New_York
    assert assembled["locale"] == "en-US"
    assert assembled["platform"] == "windows"


def test_assemble_template_fields_are_coherent():
    result = sp.assemble_spec(_spec(), sentence="x", used_template_ids=set())
    assembled = result["assembled"]
    tpl = device_templates.get_template(assembled["device_profile"])
    assert tpl is not None
    for field in ("screen_width", "screen_height", "gpu_vendor", "gpu_renderer",
                  "hardware_concurrency", "device_memory"):
        assert assembled[field] == tpl[field]


def test_assemble_prefers_unused_templates():
    first = device_templates.list_templates()[0]
    result = sp.assemble_spec(_spec(), sentence="x", used_template_ids={first["id"]})
    assert result["assembled"]["device_profile"] != first["id"]


def test_assemble_falls_back_when_all_templates_used():
    all_ids = {tpl["id"] for tpl in device_templates.list_templates()}
    result = sp.assemble_spec(_spec(), sentence="x", used_template_ids=all_ids)
    assert device_templates.get_template(result["assembled"]["device_profile"]) is not None


def test_assemble_name_format_and_uniqueness():
    names = {
        sp.assemble_spec(_spec(), sentence="x", used_template_ids=set())["assembled"]["name"]
        for _ in range(20)
    }
    assert len(names) == 20
    name = next(iter(names))
    assert name.startswith("西雅图 · 露营摄影 ")
    assert len(name.rsplit("-", 1)[1]) == 4


def test_assemble_persona_within_200_chars():
    result = sp.assemble_spec(
        _spec(persona_notes="人" * 300), sentence="x", used_template_ids=set(),
    )
    persona = result["assembled"]["warmup_persona"]
    assert persona is not None and len(persona) <= 200
    assert persona.startswith("西雅图，喜欢露营、摄影")


def test_assemble_targets_from_interests_subset_of_catalog():
    result = sp.assemble_spec(
        _spec(interests=["shopping", "social", "tech", "gaming", "cooking"]),
        sentence="x", used_template_ids=set(),
    )
    targets = result["assembled"]["warmup_targets"]
    assert set(targets) <= set(warmup.TARGET_CATALOG)
    assert len(targets) <= 4
    assert targets[0] == "amazon"  # shopping maps first


def test_assemble_no_interests_gives_generic_targets():
    result = sp.assemble_spec(_spec(interests=[]), sentence="x", used_template_ids=set())
    assert result["assembled"]["warmup_targets"] == ["google", "youtube"]
    assert result["assembled"]["warmup_enabled"] is True


def test_assemble_fingerprint_options_are_recommended_preset():
    result = sp.assemble_spec(_spec(), sentence="x", used_template_ids=set())
    assert result["assembled"]["fingerprint_options"] == {"noise": False, "storage_quota_mb": 50000}
    assert result["assembled"]["disposable"] is False


def test_assemble_notes_carry_sentence_and_purpose():
    result = sp.assemble_spec(
        _spec(purpose="日常购物"), sentence="建个美国号", used_template_ids=set(),
    )
    assert result["assembled"]["notes"] == "一句话建号：建个美国号（用途：日常购物）"


# ── confirm-time validation ──────────────────────────────────────────────


def _assembled_payload(**overrides) -> dict:
    payload = sp.assemble_spec(_spec(), sentence="建个美国号", used_template_ids=set())["assembled"]
    payload.update(overrides)
    return payload


def test_validate_assembled_rewrites_hardware_from_template():
    payload = _assembled_payload(screen_width=1, gpu_renderer="tampered", device_memory=1)
    fields, warnings = sp.validate_assembled(payload, sentence="建个美国号", used_template_ids=set())
    tpl = device_templates.get_template(payload["device_profile"])
    assert fields["screen_width"] == tpl["screen_width"]
    assert fields["gpu_renderer"] == tpl["gpu_renderer"]
    assert fields["device_memory"] == tpl["device_memory"]
    assert warnings == []


def test_validate_assembled_unknown_template_rejected():
    payload = _assembled_payload(device_profile="tpl-does-not-exist")
    with pytest.raises(sp.SentenceValidationError):
        sp.validate_assembled(payload, sentence="x", used_template_ids=set())


def test_validate_assembled_template_race_swaps_with_warning():
    payload = _assembled_payload()
    taken = payload["device_profile"]
    fields, warnings = sp.validate_assembled(
        payload, sentence="建个美国号", used_template_ids={taken},
    )
    assert fields["device_profile"] != taken
    assert any("已被其他画像占用" in w for w in warnings)


def test_validate_assembled_rejects_bad_timezone_and_locale():
    with pytest.raises(sp.SentenceValidationError):
        sp.validate_assembled(_assembled_payload(timezone="Mars/Olympus"), sentence="x", used_template_ids=set())
    with pytest.raises(sp.SentenceValidationError):
        sp.validate_assembled(_assembled_payload(locale="not-a-locale"), sentence="x", used_template_ids=set())


def test_validate_assembled_filters_targets_and_forces_preset():
    payload = _assembled_payload(warmup_targets=["google", "myspace", "google", "x"])
    fields, _ = sp.validate_assembled(payload, sentence="x", used_template_ids=set())
    assert fields["warmup_targets"] == ["google", "x"]
    assert fields["fingerprint_options"] == {"noise": False, "storage_quota_mb": 50000}


def test_validate_assembled_empty_name_regenerated():
    payload = _assembled_payload(name="  ")
    fields, _ = sp.validate_assembled(payload, sentence="建个美国号，西雅图", used_template_ids=set())
    assert fields["name"].startswith("西雅图")


def test_validate_assembled_disposable_flag():
    fields, _ = sp.validate_assembled(_assembled_payload(disposable=True), sentence="x", used_template_ids=set())
    assert fields["disposable"] == 1
    fields, _ = sp.validate_assembled(_assembled_payload(disposable=False), sentence="x", used_template_ids=set())
    assert fields["disposable"] == 0


# ── LLM parsing ──────────────────────────────────────────────────────────


def _configure_llm():
    llm_client.save_config(
        db.set_setting,
        base_url="https://llm.example/v1",
        model="test-model",
        api_key="<redacted>",
    )


def _transport(payload, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})
    return httpx.MockTransport(handler)


async def test_parse_sentence_llm_path(tmp_db):
    _configure_llm()
    calls: list = []
    result = await sp.parse_sentence(
        "建个美国号，西雅图，喜欢露营",
        get_setting=db.get_setting,
        transport=_transport(
            {"country": "US", "city": "Seattle", "interests": ["camping"],
             "persona_notes": None, "purpose": None, "disposable": False},
            calls,
        ),
    )
    assert result["source"] == "llm"
    assert result["spec"]["country"] == "US" and result["spec"]["city"] == "Seattle"
    # The prompt must carry the white lists as data.
    body = json.loads(calls[0].content)
    user_text = body["messages"][1]["content"]
    assert '"code": "US"' in user_text and "Seattle" in user_text and "camping" in user_text


async def test_parse_sentence_no_config_uses_fallback(tmp_db):
    result = await sp.parse_sentence("建个日本号，东京", get_setting=db.get_setting)
    assert result["source"] == "fallback"
    assert result["spec"]["country"] == "JP"
    assert any("未配置 AI" in w for w in result["warnings"])


async def test_parse_sentence_llm_garbage_degrades_to_rules(tmp_db):
    _configure_llm()
    result = await sp.parse_sentence(
        "建个美国号",
        get_setting=db.get_setting,
        transport=_transport({"country": "XX", "interests": "junk"}),
    )
    assert result["source"] == "fallback"
    assert result["spec"]["country"] == "US"
    assert any("AI 解析失败" in w for w in result["warnings"])


async def test_parse_sentence_llm_fenced_json_is_rescued(tmp_db):
    _configure_llm()

    def handler(request: httpx.Request) -> httpx.Response:
        content = "好的，这是结果：\n```json\n" + json.dumps({"country": "JP", "city": "Tokyo"}) + "\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    result = await sp.parse_sentence(
        "建个东京的号", get_setting=db.get_setting, transport=httpx.MockTransport(handler),
    )
    assert result["source"] == "llm" and result["spec"]["city"] == "Tokyo"


async def test_parse_sentence_llm_down_and_rules_fail_is_422(tmp_db):
    _configure_llm()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(sp.SentenceParseError):
        await sp.parse_sentence(
            "来个号吧", get_setting=db.get_setting, transport=httpx.MockTransport(handler),
        )


# ── API round-trip ───────────────────────────────────────────────────────

SENTENCE = "建个美国号，西雅图，平时喜欢露营和摄影"


def _draft(client: TestClient, sentence: str = SENTENCE) -> dict:
    res = client.post("/api/profiles/from-sentence/draft", json={"sentence": sentence})
    assert res.status_code == 200, res.text
    return res.json()


def test_api_options_payload(app_client: TestClient):
    res = app_client.get("/api/profiles/from-sentence/options")
    assert res.status_code == 200
    payload = res.json()
    assert len(payload["countries"]) == 26
    assert any(c["name"] == "Seattle" for c in payload["cities"]["US"])
    assert len(payload["interests"]) == 14
    assert {t["id"] for t in payload["targets"]} == set(warmup.TARGET_CATALOG)


def test_api_draft_fallback_creates_nothing(app_client: TestClient):
    before = len(db.list_profiles())
    payload = _draft(app_client)
    assert payload["source"] == "fallback"
    assert payload["spec"]["country"] == "US"
    assert payload["assembled"]["timezone"] == "America/Los_Angeles"
    assert any("未配置 AI" in w for w in payload["warnings"])
    assert len(db.list_profiles()) == before


def test_api_draft_rejects_empty_and_overlong(app_client: TestClient):
    res = app_client.post("/api/profiles/from-sentence/draft", json={"sentence": "  "})
    assert res.status_code == 422
    res = app_client.post(
        "/api/profiles/from-sentence/draft", json={"sentence": "美" * 501},
    )
    assert res.status_code == 422


def test_api_draft_unknown_country_is_chinese_422(app_client: TestClient):
    res = app_client.post("/api/profiles/from-sentence/draft", json={"sentence": "建个号，喜欢露营"})
    assert res.status_code == 422
    assert "没认出国家" in res.json()["detail"]


def test_api_confirm_round_trip(app_client: TestClient):
    draft = _draft(app_client)
    res = app_client.post(
        "/api/profiles/from-sentence",
        json={"sentence": SENTENCE, "assembled": draft["assembled"]},
    )
    assert res.status_code == 201, res.text
    profile = res.json()
    assert profile["warnings"] == []
    assert profile["name"] == draft["assembled"]["name"]
    assert profile["timezone"] == "America/Los_Angeles"
    assert profile["locale"] == "en-US"
    assert profile["warmup_targets"] == ["youtube", "google"]
    assert profile["warmup_enabled"] is True
    assert profile["warmup_persona"] == "西雅图，喜欢露营、摄影"
    assert profile["disposable"] is False
    assert profile["fingerprint_options"]["noise"] is False
    assert profile["fingerprint_options"]["storage_quota_mb"] == 50000
    assert profile["notes"].startswith("一句话建号：")


def test_api_confirm_hardware_tamper_is_rewritten(app_client: TestClient):
    draft = _draft(app_client)
    assembled = dict(draft["assembled"], screen_width=1, gpu_renderer="tampered")
    res = app_client.post(
        "/api/profiles/from-sentence",
        json={"sentence": SENTENCE, "assembled": assembled},
    )
    assert res.status_code == 201, res.text
    tpl = device_templates.get_template(assembled["device_profile"])
    assert res.json()["screen_width"] == tpl["screen_width"]
    assert res.json()["gpu_renderer"] == tpl["gpu_renderer"]


def test_api_confirm_template_race_swaps_and_warns(app_client: TestClient):
    draft = _draft(app_client)
    db.create_profile(name="抢先占用", device_profile=draft["assembled"]["device_profile"])
    res = app_client.post(
        "/api/profiles/from-sentence",
        json={"sentence": SENTENCE, "assembled": draft["assembled"]},
    )
    assert res.status_code == 201, res.text
    profile = res.json()
    assert profile["device_profile"] != draft["assembled"]["device_profile"]
    assert any("已被其他画像占用" in w for w in profile["warnings"])


def test_api_confirm_unknown_template_is_422(app_client: TestClient):
    draft = _draft(app_client)
    assembled = dict(draft["assembled"], device_profile="tpl-nope")
    res = app_client.post(
        "/api/profiles/from-sentence",
        json={"sentence": SENTENCE, "assembled": assembled},
    )
    assert res.status_code == 422


def test_api_confirm_disposable_sentence_profile(app_client: TestClient):
    draft = _draft(app_client, "建个一次性的日本号，东京")
    assert draft["spec"]["disposable"] is True
    res = app_client.post(
        "/api/profiles/from-sentence",
        json={"sentence": "建个一次性的日本号，东京", "assembled": draft["assembled"]},
    )
    assert res.status_code == 201, res.text
    assert res.json()["disposable"] is True


def test_api_draft_with_llm_configured(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _configure_llm()

    async def fake_chat(config, messages, *, transport=None):
        return json.dumps({
            "country": "JP", "city": "Tokyo", "interests": ["gaming"],
            "persona_notes": "下班打游戏", "purpose": None, "disposable": False,
        })

    monkeypatch.setattr(llm_client, "chat_completion", fake_chat)
    payload = _draft(app_client, "随便来个日本打游戏的号")
    assert payload["source"] == "llm"
    assert payload["spec"]["country"] == "JP"
    assert payload["assembled"]["timezone"] == "Asia/Tokyo"
    assert payload["assembled"]["warmup_persona"] == "东京，喜欢游戏，下班打游戏"


def test_api_draft_llm_failure_degrades_visibly(app_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _configure_llm()

    async def failing_chat(config, messages, *, transport=None):
        raise RuntimeError("endpoint down")

    monkeypatch.setattr(llm_client, "chat_completion", failing_chat)
    payload = _draft(app_client, "建个美国号")
    assert payload["source"] == "fallback"
    assert any("AI 解析失败" in w for w in payload["warnings"])
