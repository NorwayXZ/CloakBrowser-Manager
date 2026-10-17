"""Exit-IP lookups keep the coordinates each provider reports."""

from __future__ import annotations

import httpx
import pytest

from backend import proxy_geo

RESPONSES = {
    "ipwho.is": {"success": True, "ip": "198.51.100.7", "country_code": "TW", "timezone": {"id": "Asia/Taipei"},
                 "latitude": 25.05, "longitude": 121.53},
    "ipinfo.io": {"ip": "198.51.100.7", "country": "TW", "timezone": "Asia/Taipei", "loc": "25.0478,121.5319"},
    "ipwhois.app": {"success": True, "ip": "198.51.100.7", "country_code": "TW", "timezone": "Asia/Taipei",
                    "latitude": "25.04", "longitude": "121.52"},
    "ip-api.com": {"status": "success", "query": "198.51.100.7", "countryCode": "TW", "timezone": "Asia/Taipei",
                   "lat": 25.0, "lon": 121.5},
    "ipapi.co": {"ip": "198.51.100.7", "country_code": "TW", "timezone": "Asia/Taipei",
                 "latitude": 999, "longitude": 121.5},
}


def _client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=RESPONSES[request.url.host])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@pytest.mark.parametrize(("fetch", "expected"), [
    (proxy_geo._fetch_ipwho, (25.05, 121.53)),
    (proxy_geo._fetch_ipinfo, (25.0478, 121.5319)),
    (proxy_geo._fetch_ipwhois_app, (25.04, 121.52)),
    (proxy_geo._fetch_ip_api, (25.0, 121.5)),
])
async def test_providers_report_coordinates(fetch, expected):
    async with _client() as client:
        result = await fetch(client)
    assert (result["latitude"], result["longitude"]) == expected


@pytest.mark.asyncio
async def test_out_of_range_coordinates_are_dropped():
    async with _client() as client:
        result = await proxy_geo._fetch_ipapi(client)
    assert "latitude" not in result
    assert "longitude" not in result
