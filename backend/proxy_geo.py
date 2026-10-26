"""Proxy geolocation helpers shared by API routes and browser launch."""

from __future__ import annotations

import asyncio
import ipaddress
from collections import Counter
from typing import Any

import httpx


COUNTRY_LOCALE_DEFAULTS: dict[str, str] = {
    "AR": "es-AR",
    "AU": "en-AU",
    "BR": "pt-BR",
    "CA": "en-CA",
    "CN": "zh-CN",
    "DE": "de-DE",
    "ES": "es-ES",
    "FR": "fr-FR",
    "GB": "en-GB",
    "HK": "zh-HK",
    "ID": "id-ID",
    "IN": "en-IN",
    "IT": "it-IT",
    "JP": "ja-JP",
    "KR": "ko-KR",
    "MX": "es-MX",
    "MY": "ms-MY",
    "NL": "nl-NL",
    "PH": "en-PH",
    "RU": "ru-RU",
    "SG": "en-SG",
    "TH": "th-TH",
    "TR": "tr-TR",
    "TW": "zh-TW",
    "US": "en-US",
    "VN": "vi-VN",
}


COUNTRY_TIMEZONE_DEFAULTS: dict[str, str] = {
    "AR": "America/Argentina/Buenos_Aires",
    "AU": "Australia/Sydney",
    "BR": "America/Sao_Paulo",
    "CA": "America/Toronto",
    "CN": "Asia/Shanghai",
    "DE": "Europe/Berlin",
    "ES": "Europe/Madrid",
    "FR": "Europe/Paris",
    "GB": "Europe/London",
    "HK": "Asia/Hong_Kong",
    "ID": "Asia/Jakarta",
    "IN": "Asia/Kolkata",
    "IT": "Europe/Rome",
    "JP": "Asia/Tokyo",
    "KR": "Asia/Seoul",
    "MX": "America/Mexico_City",
    "MY": "Asia/Kuala_Lumpur",
    "NL": "Europe/Amsterdam",
    "PH": "Asia/Manila",
    "RU": "Europe/Moscow",
    "SG": "Asia/Singapore",
    "TH": "Asia/Bangkok",
    "TR": "Europe/Istanbul",
    "TW": "Asia/Taipei",
    "US": "America/New_York",
    "VN": "Asia/Ho_Chi_Minh",
}


def suggested_timezone(country_code: str | None) -> str | None:
    return COUNTRY_TIMEZONE_DEFAULTS.get(str(country_code or "").upper())


class ProxyGeoError(RuntimeError):
    pass


# httpx bounds connecting and reading, but not the SOCKS5 handshake: a proxy
# that accepts the connection and never answers its CONNECT request would
# keep a lookup waiting forever. Every request through a proxy gets this cap.
PROXY_REQUEST_SECONDS = 15.0


def suggested_locale(country_code: str | None) -> str | None:
    return COUNTRY_LOCALE_DEFAULTS.get(str(country_code or "").upper())


def _coordinate(value: Any, limit: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if -limit <= number <= limit else None


def _with_coordinates(data: dict[str, Any], latitude: Any, longitude: Any) -> dict[str, Any]:
    lat = _coordinate(latitude, 90)
    lon = _coordinate(longitude, 180)
    if lat is not None and lon is not None:
        data["latitude"] = lat
        data["longitude"] = lon
    return data


def _with_locale(data: dict[str, Any]) -> dict[str, Any]:
    data["suggested_locale"] = suggested_locale(data.get("country_code"))
    return data


async def _fetch_ip_api(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get(
        "http://ip-api.com/json/",
        params={
            "fields": "status,message,query,country,countryCode,regionName,city,lat,lon,timezone,isp,org,as",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise ProxyGeoError(str(data.get("message") or "ip-api lookup failed"))
    return _with_locale(_with_coordinates({
        "ip": data.get("query"),
        "country": data.get("country"),
        "country_code": data.get("countryCode"),
        "region": data.get("regionName"),
        "city": data.get("city"),
        "timezone": data.get("timezone"),
        "org": data.get("org") or data.get("isp"),
        "asn": str(data.get("as")) if data.get("as") is not None else None,
        "source": "ip-api.com",
    }, data.get("lat"), data.get("lon")))


async def _fetch_ipwho(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get("https://ipwho.is/")
    resp.raise_for_status()
    data = resp.json()
    if data.get("success") is False:
        raise ProxyGeoError(str(data.get("message") or "ipwho lookup failed"))
    timezone = data.get("timezone")
    if isinstance(timezone, dict):
        timezone = timezone.get("id")
    connection = data.get("connection") if isinstance(data.get("connection"), dict) else {}
    return _with_locale(_with_coordinates({
        "ip": data.get("ip"),
        "country": data.get("country"),
        "country_code": data.get("country_code"),
        "region": data.get("region"),
        "city": data.get("city"),
        "timezone": timezone,
        "org": connection.get("org") or connection.get("isp"),
        "asn": str(connection.get("asn")) if connection.get("asn") is not None else None,
        "source": "ipwho.is",
    }, data.get("latitude"), data.get("longitude")))


async def _fetch_ipapi(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get("https://ipapi.co/json/")
    resp.raise_for_status()
    data = resp.json()
    return _with_locale(_with_coordinates({
        "ip": data.get("ip"),
        "country": data.get("country_name"),
        "country_code": data.get("country_code"),
        "region": data.get("region"),
        "city": data.get("city"),
        "timezone": data.get("timezone"),
        "org": data.get("org"),
        "asn": str(data.get("asn")) if data.get("asn") is not None else None,
        "source": "ipapi.co",
    }, data.get("latitude"), data.get("longitude")))


async def _fetch_ipinfo(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get("https://ipinfo.io/json")
    resp.raise_for_status()
    data = resp.json()
    latitude, _, longitude = str(data.get("loc") or "").partition(",")
    return _with_locale(_with_coordinates({
        "ip": data.get("ip"),
        "country": data.get("country"),
        "country_code": data.get("country"),
        "region": data.get("region"),
        "city": data.get("city"),
        "timezone": data.get("timezone"),
        "org": data.get("org"),
        "asn": str(data.get("org")) if data.get("org") is not None else None,
        "source": "ipinfo.io",
    }, latitude, longitude))


async def _fetch_ipwhois_app(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get("https://ipwhois.app/json/")
    resp.raise_for_status()
    data = resp.json()
    if data.get("success") is False:
        raise ProxyGeoError(str(data.get("message") or "ipwhois.app lookup failed"))
    return _with_locale(_with_coordinates({
        "ip": data.get("ip"),
        "country": data.get("country"),
        "country_code": data.get("country_code"),
        "region": data.get("region"),
        "city": data.get("city"),
        "timezone": data.get("timezone"),
        "org": data.get("org") or data.get("isp"),
        "asn": str(data.get("asn")) if data.get("asn") is not None else None,
        "source": "ipwhois.app",
    }, data.get("latitude"), data.get("longitude")))


def _choose_geo_result(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose a stable GeoIP result, preferring timezone consensus."""
    if not results:
        raise ProxyGeoError("proxy geo lookup failed")

    timezone_counts = Counter(
        str(result.get("timezone"))
        for result in results
        if result.get("timezone")
    )
    if not timezone_counts:
        return results[0]

    chosen_timezone, _count = timezone_counts.most_common(1)[0]
    agreeing = [
        result for result in results
        if result.get("timezone") == chosen_timezone
    ]
    chosen = dict(agreeing[0])
    chosen["source"] = "majority: " + ", ".join(
        str(result.get("source")) for result in agreeing if result.get("source")
    )
    return chosen


def exit_ip_spread(results: list[dict[str, Any]]) -> tuple[list[str], bool]:
    """Every exit IP the lookup sites saw, and whether the exit rotates.

    The sites are asked one after another over separate connections, so a
    proxy that hands out a new address per connection shows several IPs.
    A dual-stack direct connection legitimately shows one IPv4 and one IPv6
    address, so only a second address of the same family counts.
    """
    ips = sorted({str(result["ip"]) for result in results if result.get("ip")})
    families: Counter[int] = Counter()
    for ip in ips:
        try:
            families[ipaddress.ip_address(ip).version] += 1
        except ValueError:
            continue
    return ips, any(count > 1 for count in families.values())


async def fetch_proxy_geo(proxy: str | None) -> dict[str, Any]:
    errors: list[str] = []
    async with httpx.AsyncClient(
        proxy=proxy,
        timeout=httpx.Timeout(12.0, connect=8.0),
        follow_redirects=True,
    ) as client:
        results: list[dict[str, Any]] = []
        providers = (
            _fetch_ipwho,
            _fetch_ipinfo,
            _fetch_ipwhois_app,
            _fetch_ip_api,
            _fetch_ipapi,
        )
        for provider in providers:
            try:
                results.append(await asyncio.wait_for(provider(client), PROXY_REQUEST_SECONDS))
            except asyncio.TimeoutError:
                errors.append(f"{provider.__name__}: no answer in {PROXY_REQUEST_SECONDS:.0f} s")
            except (httpx.HTTPError, ValueError, ProxyGeoError) as exc:
                errors.append(f"{provider.__name__}: {type(exc).__name__}")

    if results:
        chosen = _choose_geo_result(results)
        chosen["exit_ips"], chosen["rotating_ip"] = exit_ip_spread(results)
        return chosen

    raise ProxyGeoError("; ".join(errors) or "proxy geo lookup failed")
