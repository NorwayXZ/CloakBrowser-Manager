"""Proxy geolocation helpers shared by API routes and browser launch."""

from __future__ import annotations

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


class ProxyGeoError(RuntimeError):
    pass


def suggested_locale(country_code: str | None) -> str | None:
    return COUNTRY_LOCALE_DEFAULTS.get(str(country_code or "").upper())


def _with_locale(data: dict[str, Any]) -> dict[str, Any]:
    data["suggested_locale"] = suggested_locale(data.get("country_code"))
    return data


async def _fetch_ip_api(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get(
        "http://ip-api.com/json/",
        params={
            "fields": "status,message,query,country,countryCode,regionName,city,timezone,isp,org,as",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise ProxyGeoError(str(data.get("message") or "ip-api lookup failed"))
    return _with_locale({
        "ip": data.get("query"),
        "country": data.get("country"),
        "country_code": data.get("countryCode"),
        "region": data.get("regionName"),
        "city": data.get("city"),
        "timezone": data.get("timezone"),
        "org": data.get("org") or data.get("isp"),
        "asn": str(data.get("as")) if data.get("as") is not None else None,
        "source": "ip-api.com",
    })


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
    return _with_locale({
        "ip": data.get("ip"),
        "country": data.get("country"),
        "country_code": data.get("country_code"),
        "region": data.get("region"),
        "city": data.get("city"),
        "timezone": timezone,
        "org": connection.get("org") or connection.get("isp"),
        "asn": str(connection.get("asn")) if connection.get("asn") is not None else None,
        "source": "ipwho.is",
    })


async def _fetch_ipapi(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get("https://ipapi.co/json/")
    resp.raise_for_status()
    data = resp.json()
    return _with_locale({
        "ip": data.get("ip"),
        "country": data.get("country_name"),
        "country_code": data.get("country_code"),
        "region": data.get("region"),
        "city": data.get("city"),
        "timezone": data.get("timezone"),
        "org": data.get("org"),
        "asn": str(data.get("asn")) if data.get("asn") is not None else None,
        "source": "ipapi.co",
    })


async def _fetch_ipinfo(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get("https://ipinfo.io/json")
    resp.raise_for_status()
    data = resp.json()
    return _with_locale({
        "ip": data.get("ip"),
        "country": data.get("country"),
        "country_code": data.get("country"),
        "region": data.get("region"),
        "city": data.get("city"),
        "timezone": data.get("timezone"),
        "org": data.get("org"),
        "asn": str(data.get("org")) if data.get("org") is not None else None,
        "source": "ipinfo.io",
    })


async def _fetch_ipwhois_app(client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await client.get("https://ipwhois.app/json/")
    resp.raise_for_status()
    data = resp.json()
    if data.get("success") is False:
        raise ProxyGeoError(str(data.get("message") or "ipwhois.app lookup failed"))
    return _with_locale({
        "ip": data.get("ip"),
        "country": data.get("country"),
        "country_code": data.get("country_code"),
        "region": data.get("region"),
        "city": data.get("city"),
        "timezone": data.get("timezone"),
        "org": data.get("org") or data.get("isp"),
        "asn": str(data.get("asn")) if data.get("asn") is not None else None,
        "source": "ipwhois.app",
    })


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


async def fetch_proxy_geo(proxy: str) -> dict[str, Any]:
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
                results.append(await provider(client))
            except (httpx.HTTPError, ValueError, ProxyGeoError) as exc:
                errors.append(f"{provider.__name__}: {type(exc).__name__}")

    if results:
        return _choose_geo_result(results)

    raise ProxyGeoError("; ".join(errors) or "proxy geo lookup failed")
