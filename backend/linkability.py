"""Linkability analysis: which stored profiles look like the same person.

External risk engines (Fingerprint-style velocity / linked-ID signals)
correlate accounts that share an exit, a device, or a derived fingerprint.
This module surfaces the same correlations from the records the Manager
already stores, so the user can see — before a detector does — which of
their profiles look linked and why.

Pure analysis: no browser is launched, nothing is mutated, and only stored
profile fields are read (proxy credentials are never included — endpoints
are compared as scheme://host:port only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from . import device_templates

# Pairwise weights. A single strong signal is enough to cluster two
# profiles; the weak signal (same timezone + language) only ever adds
# colour to a pair that already links for a harder reason — whole regions
# share a timezone and language, so it must never cluster on its own.
W_SEED = 60        # same fingerprint seed -> near-identical derived fingerprint
W_PROXY = 55       # same proxy endpoint (scheme://host:port)
W_EXIT_IP = 50     # same last recorded exit IP
W_TEMPLATE = 45    # same device template pinned
W_COMBO = 30       # same GPU+screen+CPU+RAM combo (rare: shared by <= 3)
W_COMBO_COMMON = 15  # same combo, but the combo is common in this library
W_WEAK = 10        # same timezone + language
EDGE_THRESHOLD = 30
STRONG_THRESHOLD = 45
COMBO_RARE_MAX = 3

_URL_SCHEMES = ("http://", "https://", "socks5://", "socks://", "ss://", "vless://", "trojan://", "vmess://")
_RENDERER_MODEL_RE = re.compile(r"^ANGLE \(\w+,\s+(.+?)\s+\(0x[0-9A-Fa-f]+\)")


def parse_proxy_endpoint(proxy: str | None) -> str | None:
    """scheme://host:port of a stored proxy value, credentials stripped.

    Handles the formats _normalize_proxy accepts. Opaque share links whose
    endpoint is not visible in the stored string (e.g. vmess://) yield None
    and simply contribute no proxy signal.
    """
    value = (proxy or "").strip()
    if not value:
        return None
    if value.lower().startswith(_URL_SCHEMES):
        parsed = urlparse(value)
        if parsed.hostname and parsed.port:
            return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}:{parsed.port}"
        return None
    parts = value.split(":")
    if len(parts) >= 2 and parts[1].isdigit():
        return f"http://{parts[0].lower()}:{parts[1]}"
    return None


@dataclass
class ProfileSignals:
    profile_id: str
    name: str
    template_id: str | None = None
    template_name: str | None = None
    hardware: tuple[Any, ...] | None = None
    proxy_endpoint: str | None = None
    exit_ip: str | None = None
    seed: int | None = None
    timezone: str | None = None
    locale: str | None = None


@dataclass
class Link:
    a_id: str
    b_id: str
    a_name: str
    b_name: str
    score: int
    level: str  # "strong" | "medium"
    reasons: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def extract_signals(profile: dict[str, Any]) -> ProfileSignals:
    """Pull the correlation signals out of one stored profile record."""
    signals = ProfileSignals(
        profile_id=str(profile.get("id")),
        name=str(profile.get("name") or profile.get("id")),
        seed=profile.get("fingerprint_seed"),
        timezone=profile.get("timezone") or None,
        locale=profile.get("locale") or None,
        proxy_endpoint=parse_proxy_endpoint(profile.get("proxy")),
    )

    device_profile = profile.get("device_profile")
    if device_profile:
        tpl = device_templates.get_template(str(device_profile))
        if tpl:
            signals.template_id = tpl["id"]
            signals.template_name = tpl["name"]

    renderer = profile.get("gpu_renderer") or None
    width, height = profile.get("screen_width"), profile.get("screen_height")
    cores = profile.get("hardware_concurrency")
    if renderer and width and height and cores:
        signals.hardware = (renderer, width, height, cores, profile.get("device_memory"))

    geo = profile.get("proxy_geo")
    if isinstance(geo, dict) and geo.get("ip"):
        signals.exit_ip = str(geo["ip"])
    return signals


def _renderer_short(renderer: str) -> str:
    match = _RENDERER_MODEL_RE.match(renderer)
    return match.group(1) if match else renderer


def _combo_text(hardware: tuple[Any, ...]) -> str:
    renderer, width, height, cores, memory = hardware
    text = f"{_renderer_short(str(renderer))} · {width}×{height} · {cores} 核"
    if memory:
        text += f" · {memory} GB"
    return text


def score_pair(
    a: ProfileSignals,
    b: ProfileSignals,
    combo_counts: dict[tuple[Any, ...], int],
) -> Link | None:
    """Score one pair; None when the pair does not reach the link threshold."""
    score = 0
    reasons: list[str] = []
    suggestions: list[str] = []
    pair = f"「{a.name}」与「{b.name}」"

    if a.seed is not None and a.seed == b.seed:
        score += W_SEED
        reasons.append(f"{pair}的指纹种子相同（{a.seed}），派生出的指纹几乎完全一致")
        suggestions.append("给其中一个画像换一个新的指纹种子，旧种子派生的指纹不要再复用")

    if a.proxy_endpoint and a.proxy_endpoint == b.proxy_endpoint:
        score += W_PROXY
        reasons.append(f"{pair}共用同一代理出口（{a.proxy_endpoint}）")
        suggestions.append("给其中一个画像换一个独立的代理出口 — 共用出口是最强的关联信号")

    if a.exit_ip and a.exit_ip == b.exit_ip:
        score += W_EXIT_IP
        reasons.append(f"{pair}最近一次打开的出口 IP 相同（{a.exit_ip}）")
        suggestions.append("错开两个画像的使用时间，或更换其中一个的出口后再打开")

    same_template = a.template_id is not None and a.template_id == b.template_id
    if same_template:
        score += W_TEMPLATE
        reasons.append(f"{pair}使用同一设备模板（{a.template_name}）")
        suggestions.append("给其中一个画像换一个不同的设备模板，避免整套硬件身份完全相同")
    elif a.hardware is not None and a.hardware == b.hardware:
        # The hardware combo is only scored when a shared template does not
        # already explain it (a template pins exactly this combo).
        rare = combo_counts.get(a.hardware, 0) <= COMBO_RARE_MAX
        score += W_COMBO if rare else W_COMBO_COMMON
        reasons.append(f"{pair}的硬件组合完全相同（{_combo_text(a.hardware)}）")
        suggestions.append("至少改动硬件组合中的一项 — 换一个设备模板最省事")

    if a.timezone and a.locale and a.timezone == b.timezone and a.locale == b.locale:
        score += W_WEAK
        reasons.append(f"{pair}的时区与语言相同（{a.timezone} · {a.locale}）")

    if score < EDGE_THRESHOLD:
        return None
    return Link(
        a_id=a.profile_id,
        b_id=b.profile_id,
        a_name=a.name,
        b_name=b.name,
        score=score,
        level="strong" if score >= STRONG_THRESHOLD else "medium",
        reasons=reasons,
        suggestions=suggestions,
    )


def analyze(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Cluster stored profiles by linkability. Returns the API payload."""
    signals = [extract_signals(profile) for profile in profiles]

    combo_counts: dict[tuple[Any, ...], int] = {}
    for item in signals:
        if item.hardware is not None:
            combo_counts[item.hardware] = combo_counts.get(item.hardware, 0) + 1

    links: list[Link] = []
    for i, a in enumerate(signals):
        for b in signals[i + 1:]:
            link = score_pair(a, b, combo_counts)
            if link is not None:
                links.append(link)

    # Union-find over linked pairs -> clusters.
    parent: dict[str, str] = {item.profile_id: item.profile_id for item in signals}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for link in links:
        ra, rb = find(link.a_id), find(link.b_id)
        if ra != rb:
            parent[ra] = rb

    by_root: dict[str, list[ProfileSignals]] = {}
    for item in signals:
        by_root.setdefault(find(item.profile_id), []).append(item)

    names = {item.profile_id: item.name for item in signals}
    clusters: list[dict[str, Any]] = []
    clustered_ids: set[str] = set()
    for root, members in by_root.items():
        if len(members) < 2:
            continue
        member_ids = {item.profile_id for item in members}
        clustered_ids |= member_ids
        cluster_links = [
            link for link in links if link.a_id in member_ids and link.b_id in member_ids
        ]
        cluster_links.sort(key=lambda link: -link.score)
        risk = "high" if any(link.score >= STRONG_THRESHOLD for link in cluster_links) else "medium"
        clusters.append({
            "id": f"cluster-{len(clusters) + 1}",
            "risk": risk,
            "profiles": [
                {"id": item.profile_id, "name": item.name}
                for item in sorted(members, key=lambda item: item.name)
            ],
            "links": [
                {
                    "a_id": link.a_id,
                    "b_id": link.b_id,
                    "a_name": names[link.a_id],
                    "b_name": names[link.b_id],
                    "score": link.score,
                    "level": link.level,
                    "reasons": link.reasons,
                    "suggestions": link.suggestions,
                }
                for link in cluster_links
            ],
        })

    clusters.sort(key=lambda c: (0 if c["risk"] == "high" else 1, -len(c["profiles"])))
    for index, cluster in enumerate(clusters, start=1):
        cluster["id"] = f"cluster-{index}"

    return {
        "profile_count": len(signals),
        "unclustered_count": len(signals) - len(clustered_ids),
        "clusters": clusters,
    }
