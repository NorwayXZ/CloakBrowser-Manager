"""Proxy geolocation helpers shared by API routes and browser launch."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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


# Which database answers behind each lookup site. ipwho.is and ipwhois.app
# are both ipwhois.io: counted as two votes they could outvote the other
# sites with one database's answer (measured: Washington vs Los Angeles,
# and anti-fraud services that use the other databases flagged the
# mismatched timezone as a VPN).
_DATABASE_OF = {"ipwho.is": "ipwhois.io", "ipwhois.app": "ipwhois.io"}
MAXMIND_SOURCE = "MaxMind GeoLite2"
# Ties go to the database anti-fraud services use most.
_DATABASE_PREFERENCE = (MAXMIND_SOURCE, "ipinfo.io", "ip-api.com", "ipapi.co", "ipwhois.io")


def _database(result: dict[str, Any]) -> str:
    source = str(result.get("source") or "")
    return _DATABASE_OF.get(source, source)


def _preference(database: str) -> int:
    return _DATABASE_PREFERENCE.index(database) if database in _DATABASE_PREFERENCE else len(_DATABASE_PREFERENCE)


def _choose_geo_result(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose the timezone most distinct databases agree on (one vote each)."""
    if not results:
        raise ProxyGeoError("proxy geo lookup failed")

    by_database: dict[str, dict[str, Any]] = {}
    for result in results:
        by_database.setdefault(_database(result), result)
    voters = {db: result for db, result in by_database.items() if result.get("timezone")}
    if not voters:
        return results[0]

    votes = Counter(str(result["timezone"]) for result in voters.values())
    best_rank = {
        timezone: min(_preference(db) for db, result in voters.items() if result["timezone"] == timezone)
        for timezone in votes
    }
    chosen_timezone = min(votes, key=lambda tz: (-votes[tz], best_rank[tz]))
    agreeing = sorted(
        (db for db, result in voters.items() if result["timezone"] == chosen_timezone),
        key=_preference,
    )
    # The local database knows no ISP; show an online site's answer when one agrees.
    base_db = next((db for db in agreeing if db != MAXMIND_SOURCE), agreeing[0])
    chosen = dict(voters[base_db])
    chosen["source"] = "majority: " + ", ".join(agreeing)
    return chosen


def _local_geoip_path() -> Path | None:
    """The GeoLite2-City database the cloakbrowser package keeps, if it is there.

    Only read: downloading it is the package's job (on its own schedule).
    """
    try:
        from cloakbrowser.config import get_cache_dir
    except ImportError:
        return None
    path = get_cache_dir() / "geoip" / "GeoLite2-City.mmdb"
    return path if path.is_file() else None


_READER: Any = None
_READER_PATH: Path | None = None


def _maxmind_lookup(ip: str) -> dict[str, Any] | None:
    """MaxMind's answer for ``ip`` from the local database; None if unavailable."""
    global _READER, _READER_PATH
    path = _local_geoip_path()
    if path is None:
        return None
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if address.is_private or address.is_loopback:
        return None
    try:
        import geoip2.database

        if _READER is None or _READER_PATH != path:
            _READER = geoip2.database.Reader(str(path))
            _READER_PATH = path
        city = _READER.city(ip)
    except Exception as exc:  # missing package, unreadable file, unknown address
        logger.debug("Local GeoIP lookup failed for %s: %s", ip, exc)
        return None
    if not city.location.time_zone:
        return None
    return _with_locale(_with_coordinates({
        "ip": ip,
        "country": city.country.name,
        "country_code": city.country.iso_code,
        "region": city.subdivisions.most_specific.name,
        "city": city.city.name,
        "timezone": city.location.time_zone,
        "org": None,
        "asn": None,
        "source": MAXMIND_SOURCE,
    }, city.location.latitude, city.location.longitude))


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

        async def ask(provider) -> tuple[dict[str, Any] | None, str | None]:
            try:
                return await asyncio.wait_for(provider(client), PROXY_REQUEST_SECONDS), None
            except asyncio.TimeoutError:
                return None, f"{provider.__name__}: no answer in {PROXY_REQUEST_SECONDS:.0f} s"
            except (httpx.HTTPError, ValueError, ProxyGeoError) as exc:
                return None, f"{provider.__name__}: {type(exc).__name__}"

        # All sites at once: the slowest one sets the time, not their sum.
        # Each still uses its own connection, so a rotating exit shows up.
        for result, error in await asyncio.gather(*(ask(provider) for provider in providers)):
            if result is not None:
                results.append(result)
            if error is not None:
                errors.append(error)

    if results:
        exit_ips, rotating = exit_ip_spread(results)
        # The address most sites saw is the exit; MaxMind gets a vote on it too.
        seen = Counter(str(result["ip"]) for result in results if result.get("ip"))
        local = _maxmind_lookup(seen.most_common(1)[0][0]) if seen else None
        chosen = _choose_geo_result([*results, local] if local else results)
        chosen["exit_ips"], chosen["rotating_ip"] = exit_ips, rotating
        return chosen

    raise ProxyGeoError("出口 IP 查询站全部没有回答（" + "; ".join(errors) + "）")
