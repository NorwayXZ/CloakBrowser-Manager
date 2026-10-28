"""Exit-IP lookups keep the coordinates each provider reports."""

from __future__ import annotations

import asyncio

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


# ── Choosing the timezone ────────────────────────────────────────────────────


def _r(source: str, timezone: str, **extra) -> dict:
    return {"ip": "216.40.87.15", "source": source, "timezone": timezone, **extra}


def test_two_sites_on_one_database_count_once():
    # Measured on a real exit: both ipwhois.io sites said Washington, the
    # others Los Angeles; counting ipwhois.io twice picked New York, and
    # Fingerprint.com (Los Angeles) then flagged the timezone as a VPN.
    chosen = proxy_geo._choose_geo_result([
        _r("ipwho.is", "America/New_York"),
        _r("ipinfo.io", "America/Los_Angeles"),
        _r("ipwhois.app", "America/New_York"),
        _r("ip-api.com", "America/Los_Angeles"),
    ])
    assert chosen["timezone"] == "America/Los_Angeles"
    assert chosen["source"] == "majority: ipinfo.io, ip-api.com"


def test_a_tie_goes_to_the_more_widely_used_database():
    chosen = proxy_geo._choose_geo_result([_r("ipwho.is", "America/New_York"), _r("ipinfo.io", "America/Toronto")])
    assert chosen["timezone"] == "America/Toronto"


def test_maxmind_votes_but_an_online_answer_supplies_the_isp():
    chosen = proxy_geo._choose_geo_result([
        _r("ipinfo.io", "America/Los_Angeles", org="AS1 Example"),
        _r("ip-api.com", "America/Toronto", org="Zont LLC"),
        _r(proxy_geo.MAXMIND_SOURCE, "America/Toronto", org=None),
    ])
    assert chosen["timezone"] == "America/Toronto"
    assert chosen["org"] == "Zont LLC"
    assert chosen["source"] == "majority: MaxMind GeoLite2, ip-api.com"


@pytest.mark.asyncio
async def test_lookup_adds_the_local_maxmind_answer(monkeypatch):
    asked: list[str] = []

    def local(ip: str) -> dict:
        asked.append(ip)
        return _r(proxy_geo.MAXMIND_SOURCE, "Asia/Taipei", ip=ip)

    monkeypatch.setattr(proxy_geo, "_maxmind_lookup", local)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=RESPONSES[request.url.host]))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(proxy_geo.httpx, "AsyncClient", lambda **kw: real_client(transport=transport))
    chosen = await proxy_geo.fetch_proxy_geo(None)
    assert asked == ["198.51.100.7"]
    assert "MaxMind GeoLite2" in chosen["source"]


def test_maxmind_lookup_without_a_usable_database(monkeypatch, tmp_path):
    assert proxy_geo._maxmind_lookup("216.40.87.15") is None  # no database (conftest)
    broken = tmp_path / "GeoLite2-City.mmdb"
    broken.write_bytes(b"not a database")
    monkeypatch.setattr(proxy_geo, "_local_geoip_path", lambda: broken)
    monkeypatch.setattr(proxy_geo, "_READER", None)
    assert proxy_geo._maxmind_lookup("216.40.87.15") is None
    assert proxy_geo._maxmind_lookup("192.168.1.2") is None


# ── A proxy that accepts connections but never forwards ──────────────────────


async def _socks5_that_never_connects():
    """Answer the SOCKS5 greeting ("no auth"), then never answer CONNECT.

    Returns the server, its proxy URL and the open client connections. The
    test closes those itself: from Python 3.12 the server's shutdown waits for
    every connection handler, and these never end on their own.
    """
    held: list = []

    async def handle(reader, writer):
        held.append(writer)
        try:
            await reader.readexactly(3)
            writer.write(b"\x05\x00")
            await writer.drain()
            await reader.read()  # until the client gives up or the test ends
        except (ConnectionError, asyncio.IncompleteReadError):
            pass

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, f"socks5://127.0.0.1:{server.sockets[0].getsockname()[1]}", held


@pytest.mark.asyncio
async def test_lookup_through_a_proxy_that_never_forwards_gives_up(monkeypatch):
    # httpx does not time out the SOCKS5 handshake; this hung "check proxy" forever.
    monkeypatch.setattr(proxy_geo, "PROXY_REQUEST_SECONDS", 0.3)
    server, proxy, held = await _socks5_that_never_connects()
    started = asyncio.get_running_loop().time()
    try:
        with pytest.raises(proxy_geo.ProxyGeoError, match="no answer"):
            await asyncio.wait_for(proxy_geo.fetch_proxy_geo(proxy), 10)
    finally:
        for writer in held:
            writer.close()
        server.close()
        await asyncio.wait_for(server.wait_closed(), 5)
    assert asyncio.get_running_loop().time() - started < 5
