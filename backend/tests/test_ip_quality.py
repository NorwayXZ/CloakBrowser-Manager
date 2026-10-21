"""Tests for the proxy / VPN / datacenter reputation of an exit IP."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.ip_quality import check_ip_quality, summarize

IP = "150.31.13.127"


def _transport(proxycheck: dict, ip_api: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "proxycheck.io":
            assert request.url.path == f"/v2/{IP}"
            return httpx.Response(200, json=proxycheck)
        if request.url.host == "ip-api.com":
            assert request.url.path == f"/json/{IP}"
            return httpx.Response(200, json=ip_api)
        raise AssertionError(f"unexpected request {request.url}")

    return httpx.MockTransport(handler)


CLEAN_IP_API = {"status": "success", "proxy": False, "hosting": False, "mobile": False, "isp": "IIJ"}


async def _check(proxycheck: dict, ip_api: dict) -> dict:
    return await check_ip_quality(None, IP, transport=_transport(proxycheck, ip_api))


@pytest.mark.asyncio
async def test_a_known_proxy_is_flagged_with_its_type_and_risk():
    result = await _check(
        {"status": "ok", IP: {"proxy": "yes", "type": "Shadowsocks", "risk": 66}},
        CLEAN_IP_API,
    )

    assert result["verdict"] == "flagged"
    assert "proxycheck.io" in result["summary"]
    signal = next(s for s in result["signals"] if s["source"] == "proxycheck.io")
    assert signal["detail"] == "代理（Shadowsocks，风险 66）"


@pytest.mark.asyncio
async def test_a_refusal_to_answer_over_a_proxy_counts_as_flagged():
    result = await _check(
        {"status": "denied", "message": "Your access to the API has been blocked due to using a proxy server to perform your query."},
        CLEAN_IP_API,
    )

    assert result["verdict"] == "flagged"
    assert "认出查询来自代理" in result["signals"][0]["detail"]


@pytest.mark.asyncio
async def test_a_datacenter_ip_is_flagged():
    result = await _check(
        {"status": "ok", IP: {"proxy": "no", "type": "Business", "risk": 0}},
        {**CLEAN_IP_API, "hosting": True, "isp": "Amazon"},
    )

    assert result["verdict"] == "flagged"
    assert any(s["detail"].startswith("机房 IP") for s in result["signals"])


@pytest.mark.asyncio
async def test_a_risky_ip_is_suspicious():
    result = await _check({"status": "ok", IP: {"proxy": "no", "type": "Residential", "risk": 40}}, CLEAN_IP_API)

    assert result["verdict"] == "suspicious"


@pytest.mark.asyncio
async def test_a_clean_ip_still_points_to_manual_checks():
    result = await _check({"status": "ok", IP: {"proxy": "no", "type": "Residential", "risk": 0}}, CLEAN_IP_API)

    assert result["verdict"] == "clean"
    assert "Scamalytics" in result["summary"]
    assert result["links"][0]["url"] == f"https://scamalytics.com/ip/{IP}"


@pytest.mark.asyncio
async def test_failed_sources_are_unknown_not_clean():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    result = await check_ip_quality(None, IP, transport=httpx.MockTransport(handler))

    assert result["verdict"] == "unknown"
    assert all(s["status"] == "unknown" for s in result["signals"])


@pytest.mark.asyncio
async def test_no_ip_means_no_check():
    assert await check_ip_quality(None, None) is None


def test_summary_prefers_the_worst_signal():
    signals = [
        {"source": "a", "status": "clean", "detail": ""},
        {"source": "b", "status": "suspicious", "detail": ""},
    ]
    assert summarize(signals)[0] == "suspicious"
    assert summarize([*signals, {"source": "c", "status": "flagged", "detail": ""}])[0] == "flagged"


def test_proxy_test_response_carries_the_quality():
    from backend.models import ProxyTestResponse

    quality = {"verdict": "clean", "summary": "x", "signals": [], "links": []}
    response = ProxyTestResponse(ip=IP, ip_quality=quality)

    assert json.loads(response.model_dump_json())["ip_quality"]["verdict"] == "clean"
