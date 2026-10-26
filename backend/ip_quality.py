"""Whether an exit IP is known as a proxy, VPN or datacenter address.

A clean browser fingerprint does not help when the IP itself is listed in a
proxy pool: sites using IP intelligence (Fingerprint, IPQS, MaxMind...) then
know a proxy is in use. The free, keyless sources below are asked through the
same proxy as the geo lookup, so they only ever see the proxy's address.
Scamalytics and IPQS are the most precise but have no keyless API, so they are
offered as links to open by hand.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx

from .proxy_geo import PROXY_REQUEST_SECONDS

Status = Literal["flagged", "suspicious", "clean", "unknown"]

# proxycheck.io risk score from which an IP counts as suspicious.
PROXYCHECK_SUSPICIOUS_RISK = 33


def _signal(source: str, status: Status, detail: str) -> dict[str, str]:
    return {"source": source, "status": status, "detail": detail}


async def _ip_api(client: httpx.AsyncClient, ip: str) -> dict[str, str]:
    resp = await client.get(
        f"http://ip-api.com/json/{ip}",
        params={"fields": "status,message,proxy,hosting,mobile,isp"},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        return _signal("ip-api.com", "unknown", str(data.get("message") or "查询失败"))
    if data.get("hosting"):
        return _signal("ip-api.com", "flagged", f"机房 IP（{data.get('isp') or '未知运营商'}）")
    if data.get("proxy"):
        return _signal("ip-api.com", "flagged", "代理 / VPN 出口")
    kind = "移动网络" if data.get("mobile") else "家庭宽带"
    return _signal("ip-api.com", "clean", f"没有标记（{kind}，{data.get('isp') or '未知运营商'}）")


async def _proxycheck(client: httpx.AsyncClient, ip: str) -> dict[str, str]:
    resp = await client.get(
        f"https://proxycheck.io/v2/{ip}",
        params={"vpn": "1", "asn": "1", "risk": "1"},
    )
    data = resp.json()
    status = str(data.get("status") or "")
    message = str(data.get("message") or "")
    if status == "denied" and "proxy" in message.lower():
        # It refuses keyless queries it sees arriving through a proxy, so
        # the refusal itself means it recognised this IP as one.
        return _signal("proxycheck.io", "flagged", "拒绝回答：它认出查询来自代理")
    entry = data.get(ip) if isinstance(data.get(ip), dict) else None
    if status not in {"ok", "warning"} or entry is None:
        return _signal("proxycheck.io", "unknown", message or status or "查询失败")
    risk = entry.get("risk")
    kind = entry.get("type") or "未知类型"
    if str(entry.get("proxy")).lower() == "yes":
        return _signal("proxycheck.io", "flagged", f"代理（{kind}，风险 {risk}）")
    if isinstance(risk, int) and risk >= PROXYCHECK_SUSPICIOUS_RISK:
        return _signal("proxycheck.io", "suspicious", f"没标成代理，但风险 {risk}（{kind}）")
    return _signal("proxycheck.io", "clean", f"没有标记（风险 {risk if risk is not None else '未知'}）")


SOURCES = (("proxycheck.io", _proxycheck), ("ip-api.com", _ip_api))


def manual_links(ip: str) -> list[dict[str, str]]:
    return [
        {"name": "Scamalytics", "url": f"https://scamalytics.com/ip/{ip}"},
        {"name": "IPQualityScore", "url": f"https://www.ipqualityscore.com/free-ip-lookup-proxy-vpn-test/lookup/{ip}"},
        {"name": "ipinfo", "url": f"https://ipinfo.io/{ip}"},
    ]


def summarize(signals: list[dict[str, str]]) -> tuple[Status, str]:
    statuses = {signal["status"] for signal in signals}
    if "flagged" in statuses:
        names = "、".join(s["source"] for s in signals if s["status"] == "flagged")
        return "flagged", f"已被标记为代理 / VPN / 机房 IP（{names}）：网站能看出你在用代理"
    if "suspicious" in statuses:
        return "suspicious", "有风险迹象，建议换 IP 或用下面的链接再确认"
    if "clean" in statuses:
        return "clean", "免费数据源没有标记；最准的结论请再点 Scamalytics 看是否在住宅代理池里"
    return "unknown", "IP 情报源都没有回答，无法判断"


async def check_ip_quality(
    proxy: str | None,
    ip: str | None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any] | None:
    """Ask every source about ``ip`` through ``proxy``; None without an IP."""
    if not ip:
        return None
    signals: list[dict[str, str]] = []
    connection: dict[str, Any] = {"transport": transport} if transport else {"proxy": proxy}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(12.0, connect=8.0),
        follow_redirects=True,
        **connection,
    ) as client:

        async def ask(name: str, source) -> dict[str, str]:
            try:
                return await asyncio.wait_for(source(client, ip), PROXY_REQUEST_SECONDS)
            except asyncio.TimeoutError:
                return _signal(name, "unknown", f"{PROXY_REQUEST_SECONDS:.0f} 秒内没有回答")
            except (httpx.HTTPError, ValueError) as exc:
                return _signal(name, "unknown", f"查询失败（{type(exc).__name__}）")

        signals = list(await asyncio.gather(*(ask(name, source) for name, source in SOURCES)))
    verdict, summary = summarize(signals)
    return {"verdict": verdict, "summary": summary, "signals": signals, "links": manual_links(ip)}
