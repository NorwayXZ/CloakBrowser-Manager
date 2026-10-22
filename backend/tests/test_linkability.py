"""Linkability analysis: clustering, weights, reasons, endpoint.

The analysis is pure — it reads stored profile records only. These tests
pin the weighting contract: strong signals cluster, the weak signal
(same timezone + language) never clusters on its own, reasons and
suggestions are always present, and analysis mutates nothing.
"""

from __future__ import annotations

import copy

import pytest
from starlette.testclient import TestClient

from backend import database as db
from backend import linkability
from backend.linkability import analyze, parse_proxy_endpoint, score_pair, extract_signals

TPL_A = "win-rtx4060-laptop-1920x1080-01"
TPL_B = "win-rtx4070-2560x1440-01"


def _profile(**overrides):
    base = {
        "id": "p-x",
        "name": "画像X",
        "fingerprint_seed": 11111,
        "proxy": None,
        "timezone": None,
        "locale": None,
        "device_profile": None,
        "gpu_vendor": None,
        "gpu_renderer": None,
        "screen_width": 1920,
        "screen_height": 1080,
        "hardware_concurrency": None,
        "device_memory": None,
        "proxy_geo": None,
    }
    base.update(overrides)
    return base


def _signals(**overrides):
    return extract_signals(_profile(**overrides))


# ── proxy endpoint parsing ───────────────────────────────────────────────


def test_parse_proxy_endpoint_strips_credentials():
    assert parse_proxy_endpoint("http://user:pass@1.2.3.4:8080") == "http://1.2.3.4:8080"
    assert parse_proxy_endpoint("socks5://User:Pass@Example.COM:1080") == "socks5://example.com:1080"
    assert parse_proxy_endpoint("vless://uuid@host.example:443?security=tls") == "vless://host.example:443"


def test_parse_proxy_endpoint_host_port_forms():
    assert parse_proxy_endpoint("1.2.3.4:8080") == "http://1.2.3.4:8080"
    assert parse_proxy_endpoint("1.2.3.4:8080:user:pass") == "http://1.2.3.4:8080"


def test_parse_proxy_endpoint_unparseable_or_empty():
    assert parse_proxy_endpoint(None) is None
    assert parse_proxy_endpoint("") is None
    assert parse_proxy_endpoint("vmess://eyJ2IjoiMiIsInBzIjoiYSJ9") is None


# ── pairwise scoring ─────────────────────────────────────────────────────


def test_same_proxy_endpoint_is_a_strong_link():
    a = _signals(id="a", name="甲", proxy="http://u:p@1.2.3.4:8080")
    b = _signals(id="b", name="乙", proxy="http://other:cred@1.2.3.4:8080", fingerprint_seed=22222)
    link = score_pair(a, b, {})
    assert link is not None
    assert link.level == "strong"
    assert link.score >= linkability.STRONG_THRESHOLD
    assert any("共用同一代理出口" in reason for reason in link.reasons)
    assert link.suggestions


def test_same_template_is_a_strong_link():
    from backend.device_templates import get_template

    tpl = get_template(TPL_A)
    fields = dict(
        device_profile=TPL_A,
        gpu_vendor=tpl["gpu_vendor"],
        gpu_renderer=tpl["gpu_renderer"],
        screen_width=tpl["screen_width"],
        screen_height=tpl["screen_height"],
        hardware_concurrency=tpl["hardware_concurrency"],
        device_memory=tpl["device_memory"],
    )
    a = _signals(id="a", name="甲", **fields)
    b = _signals(id="b", name="乙", fingerprint_seed=22222, **fields)
    link = score_pair(a, b, {})
    assert link is not None
    assert link.level == "strong"
    assert any("同一设备模板" in reason for reason in link.reasons)
    # Template subsumes the hardware combo: it must not be double-counted.
    assert not any("硬件组合完全相同" in reason for reason in link.reasons)


def test_same_hardware_combo_across_templates_links_medium():
    from backend.device_templates import get_template

    tpl = get_template(TPL_A)
    hardware = dict(
        gpu_vendor=tpl["gpu_vendor"],
        gpu_renderer=tpl["gpu_renderer"],
        screen_width=tpl["screen_width"],
        screen_height=tpl["screen_height"],
        hardware_concurrency=tpl["hardware_concurrency"],
        device_memory=tpl["device_memory"],
    )
    a = _signals(id="a", name="甲", device_profile=TPL_A, **hardware)
    b = _signals(id="b", name="乙", device_profile=TPL_B, fingerprint_seed=22222, **hardware)
    counts = {a.hardware: 2}
    link = score_pair(a, b, counts)
    assert link is not None
    assert link.level == "medium"
    assert any("硬件组合完全相同" in reason for reason in link.reasons)
    assert link.suggestions


def test_same_seed_is_a_strong_link():
    a = _signals(id="a", name="甲", fingerprint_seed=424242)
    b = _signals(id="b", name="乙", fingerprint_seed=424242)
    link = score_pair(a, b, {})
    assert link is not None
    assert link.level == "strong"
    assert any("指纹种子相同" in reason for reason in link.reasons)


def test_same_exit_ip_is_a_strong_link():
    a = _signals(id="a", name="甲", proxy_geo={"ip": "36.235.166.91"})
    b = _signals(id="b", name="乙", fingerprint_seed=22222, proxy_geo={"ip": "36.235.166.91"})
    link = score_pair(a, b, {})
    assert link is not None
    assert link.level == "strong"
    assert any("出口 IP 相同" in reason for reason in link.reasons)


def test_weak_signal_alone_never_links():
    a = _signals(id="a", name="甲", timezone="Asia/Taipei", locale="zh-TW")
    b = _signals(id="b", name="乙", fingerprint_seed=22222, timezone="Asia/Taipei", locale="zh-TW")
    assert score_pair(a, b, {}) is None


def test_unrelated_profiles_do_not_link():
    a = _signals(id="a", name="甲", proxy="socks5://1.1.1.1:1080", timezone="Asia/Taipei", locale="zh-TW")
    b = _signals(
        id="b", name="乙", fingerprint_seed=22222,
        proxy="socks5://2.2.2.2:1080", timezone="America/New_York", locale="en-US",
    )
    assert score_pair(a, b, {}) is None


# ── clustering ───────────────────────────────────────────────────────────


def test_analyze_clusters_transitively_and_counts_the_rest():
    profiles = [
        _profile(id="a", name="甲", proxy="socks5://1.2.3.4:1080"),
        _profile(id="b", name="乙", fingerprint_seed=22222, proxy="socks5://1.2.3.4:1080", device_profile=TPL_A),
        _profile(id="c", name="丙", fingerprint_seed=33333, device_profile=TPL_A),
        _profile(id="d", name="丁", fingerprint_seed=44444, proxy="socks5://9.9.9.9:1080"),
    ]
    result = analyze(profiles)
    assert result["profile_count"] == 4
    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert {p["id"] for p in cluster["profiles"]} == {"a", "b", "c"}
    assert cluster["risk"] == "high"
    assert len(cluster["links"]) == 2
    assert result["unclustered_count"] == 1


def test_analyze_no_profiles_no_clusters():
    assert analyze([]) == {"profile_count": 0, "unclustered_count": 0, "clusters": []}


def test_analyze_does_not_mutate_profiles():
    profiles = [
        _profile(id="a", name="甲", proxy="socks5://1.2.3.4:1080", proxy_geo={"ip": "1.2.3.4"}),
        _profile(id="b", name="乙", fingerprint_seed=22222, proxy="socks5://1.2.3.4:1080"),
    ]
    snapshot = copy.deepcopy(profiles)
    analyze(profiles)
    assert profiles == snapshot


# ── endpoint ─────────────────────────────────────────────────────────────


def test_linkability_endpoint_reports_clusters(app_client: TestClient):
    db.create_profile(name="出口甲", fingerprint_seed=10001, proxy="socks5://1.2.3.4:1080")
    db.create_profile(name="出口乙", fingerprint_seed=10002, proxy="socks5://1.2.3.4:1080")
    db.create_profile(name="独行者", fingerprint_seed=10003, proxy="socks5://5.6.7.8:1080")

    res = app_client.get("/api/linkability")
    assert res.status_code == 200
    payload = res.json()
    assert payload["profile_count"] == 3
    assert payload["unclustered_count"] == 1
    assert len(payload["clusters"]) == 1
    cluster = payload["clusters"][0]
    assert {p["name"] for p in cluster["profiles"]} == {"出口甲", "出口乙"}
    assert cluster["risk"] == "high"
    assert cluster["links"][0]["reasons"]
    assert cluster["links"][0]["suggestions"]


def test_linkability_endpoint_all_clear_when_nothing_links(app_client: TestClient):
    db.create_profile(name="甲", fingerprint_seed=20001, proxy="socks5://1.1.1.1:1080")
    db.create_profile(name="乙", fingerprint_seed=20002, proxy="socks5://2.2.2.2:1080")
    res = app_client.get("/api/linkability")
    assert res.status_code == 200
    assert res.json()["clusters"] == []
