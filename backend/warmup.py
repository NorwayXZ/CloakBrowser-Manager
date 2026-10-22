"""Profile warm-up / aging （养号）: scheduled, human, logged-out browsing.

A fresh profile is suspicious partly because it has no past: no first-party
cookies with any age, no history. Warm-up gives it one. On a schedule the
Manager debug-launches the profile and browses like a person would —
locale-matched public landing pages plus the profile's chosen *target
platforms* — so first-party state (e.g. Facebook's ``datr``, Amazon's
``session-id``) is set by the platforms themselves and ages naturally.

Hard guardrails, enforced by construction and by the URL policy below:
logged-out only; never types into forms, never logs in, never uses stored
credentials, never submits personal data; no purchases, carts, checkouts,
posting, liking or following. The runner only navigates, dwells and
scrolls (through :class:`behavior.HumanSession`), and follows only
same-site links whose paths contain no account/commerce segments.

The 1-seat free-license reality is respected: a profile that is already
running, or whose launch reports the seat is taken, is *skipped* and the
reason recorded — never forced.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from urllib.parse import quote_plus, urlparse

from . import behavior

logger = logging.getLogger(__name__)

# ── Target platform catalog ─────────────────────────────────────────────────
# platform id → regional home domains (keyed by country code from the
# profile locale, "*" = default), an optional logged-out search URL
# template, and a neutral query pool. Search is navigation only — the
# runner never types into a form.

TARGET_CATALOG: dict[str, dict[str, Any]] = {
    "amazon": {
        "name": "Amazon",
        "domains": {
            "US": "www.amazon.com", "GB": "www.amazon.co.uk", "DE": "www.amazon.de",
            "FR": "www.amazon.fr", "JP": "www.amazon.co.jp", "CA": "www.amazon.ca",
            "AU": "www.amazon.com.au", "ES": "www.amazon.es", "IT": "www.amazon.it",
            "*": "www.amazon.com",
        },
        "search": "https://{domain}/s?k={query}",
        "queries": [
            "coffee mug", "desk lamp", "notebook", "water bottle", "backpack",
            "wireless mouse", "yoga mat", "picture frame", "storage box", "plant pot",
        ],
    },
    "facebook": {
        "name": "Facebook",
        "domains": {"*": "www.facebook.com"},
        "search": None,  # logged-out search is not offered; browse only
        "queries": [],
    },
    "google": {
        "name": "Google",
        "domains": {
            "JP": "www.google.co.jp", "GB": "www.google.co.uk", "DE": "www.google.de",
            "FR": "www.google.fr", "*": "www.google.com",
        },
        "search": "https://{domain}/search?q={query}",
        "queries": [
            "weather tomorrow", "news today", "how to boil eggs",
            "best hiking trails", "train timetable", "movie showtimes",
        ],
    },
    "x": {
        "name": "X",
        "domains": {"*": "x.com"},
        "entry_path": "/explore",
        "search": None,  # logged-out search requires an account; browse only
        "queries": [],
    },
    "ebay": {
        "name": "eBay",
        "domains": {
            "US": "www.ebay.com", "GB": "www.ebay.co.uk", "DE": "www.ebay.de",
            "AU": "www.ebay.com.au", "*": "www.ebay.com",
        },
        "search": "https://{domain}/sch/i.html?_nkw={query}",
        "queries": [
            "vintage watch", "film camera", "vinyl record", "leather bag",
            "mechanical keyboard", "desk clock",
        ],
    },
    "youtube": {
        "name": "YouTube",
        "domains": {"*": "www.youtube.com"},
        "search": "https://{domain}/results?search_query={query}",
        "queries": [
            "lofi beats", "cooking basics", "city walk tour", "piano cover",
            "gardening tips", "space documentary",
        ],
    },
}

# Per-platform per-day warm-up session cap (a target is aged steadily, not
# farmed — more than this stops looking like a person anyway).
TARGET_DAILY_CAP = 1

# Path segments that make a URL off-limits for link following: account,
# commerce and creation flows. The plan builder only ever emits catalog
# URLs, and the runner re-checks every followed link against this policy.
BLOCKED_PATH_SEGMENTS = (
    "login", "signin", "sign-in", "signup", "sign-up", "register",
    "account", "checkout", "cart", "basket", "buy", "purchase", "order",
    "payment", "subscribe", "sell", "post", "compose", "settings",
    "password", "recover", "auth", "oauth",
)


def catalog_public() -> list[dict[str, str]]:
    return [{"id": pid, "name": entry["name"]} for pid, entry in TARGET_CATALOG.items()]


def _country_of(profile: dict[str, Any]) -> str | None:
    locale = str(profile.get("locale") or "")
    parts = re.split(r"[-_]", locale)
    if len(parts) >= 2 and len(parts[-1]) == 2:
        return parts[-1].upper()
    return None


def _language_of(profile: dict[str, Any]) -> str:
    locale = str(profile.get("locale") or "en")
    return re.split(r"[-_]", locale)[0].lower() or "en"


def target_home_url(platform_id: str, profile: dict[str, Any]) -> str:
    entry = TARGET_CATALOG[platform_id]
    country = _country_of(profile)
    domain = entry["domains"].get(country or "", entry["domains"]["*"])
    return f"https://{domain}{entry.get('entry_path', '/')}"


def target_search_url(platform_id: str, profile: dict[str, Any], query: str) -> str | None:
    entry = TARGET_CATALOG[platform_id]
    template = entry.get("search")
    if not template:
        return None
    country = _country_of(profile)
    domain = entry["domains"].get(country or "", entry["domains"]["*"])
    return template.format(domain=domain, query=quote_plus(query))


def _site_root(host: str) -> str:
    """Registrable-domain approximation (handles co.uk/com.au/co.jp…)."""
    labels = host.lower().split(".")
    if len(labels) >= 3 and labels[-2] in ("co", "com", "net", "org", "ac", "gov") and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else host.lower()


def is_safe_follow_url(url: str, home_url: str) -> bool:
    """Same site (same registrable domain) and no account/commerce paths."""
    try:
        target = urlparse(url)
        home = urlparse(home_url)
    except ValueError:
        return False
    if target.scheme not in ("http", "https") or not target.hostname or not home.hostname:
        return False
    if _site_root(target.hostname) != _site_root(home.hostname):
        return False
    segments = [seg for seg in target.path.lower().split("/") if seg]
    return not any(seg in BLOCKED_PATH_SEGMENTS for seg in segments)


# ── Generic locale browsing ─────────────────────────────────────────────────

GENERIC_SITES: dict[str, list[str]] = {
    "zh": [
        "https://www.baidu.com/", "https://www.bing.com/",
        "https://www.sina.com.cn/", "https://www.bilibili.com/",
        "https://www.weather.com.cn/",
    ],
    "en": [
        "https://www.bbc.com/", "https://www.weather.com/",
        "https://en.wikipedia.org/", "https://www.bing.com/",
        "https://www.nasa.gov/",
    ],
    "ja": [
        "https://www.yahoo.co.jp/", "https://www3.nhk.or.jp/",
        "https://weathernews.jp/", "https://ja.wikipedia.org/",
    ],
    "ko": [
        "https://www.naver.com/", "https://www.daum.net/",
        "https://ko.wikipedia.org/",
    ],
    "de": [
        "https://www.tagesschau.de/", "https://www.wetter.com/",
        "https://de.wikipedia.org/",
    ],
    "fr": [
        "https://www.lemonde.fr/", "https://meteofrance.com/",
        "https://fr.wikipedia.org/",
    ],
    "es": [
        "https://elpais.com/", "https://es.wikipedia.org/",
    ],
    "pt": [
        "https://www.globo.com/", "https://pt.wikipedia.org/",
    ],
    "ru": [
        "https://www.ria.ru/", "https://ru.wikipedia.org/",
    ],
}


def generic_sites_for(profile: dict[str, Any]) -> list[str]:
    return GENERIC_SITES.get(_language_of(profile), GENERIC_SITES["en"])


# ── Session plan ────────────────────────────────────────────────────────────


def build_session_plan(
    profile: dict[str, Any],
    rng: random.Random,
    *,
    targets_done_today: set[str] | frozenset[str] = frozenset(),
    total_steps: int | None = None,
) -> list[dict[str, Any]]:
    """Build one warm-up session's itinerary.

    Target platforms come first (they are the point of the run), each at
    most once per session and skipped entirely once its daily cap is hit;
    generic locale sites fill the rest so the pattern never looks like
    single-site farming. Every URL is a catalog/generic URL — the runner
    may additionally follow safe same-site links from these pages.
    """
    steps: list[dict[str, Any]] = []
    wanted = [t for t in (profile.get("warmup_targets") or []) if t in TARGET_CATALOG]
    rng.shuffle(wanted)
    for platform_id in wanted[:2]:
        if platform_id in targets_done_today:
            continue
        entry = TARGET_CATALOG[platform_id]
        step: dict[str, Any] = {
            "kind": "target",
            "platform": platform_id,
            "url": target_home_url(platform_id, profile),
        }
        queries = entry.get("queries") or []
        if entry.get("search") and queries and rng.random() < 0.75:
            query = rng.choice(queries)
            search_url = target_search_url(platform_id, profile, query)
            if search_url:
                step["search_url"] = search_url
                step["search_query"] = query
        step["follow_link"] = rng.random() < 0.5
        steps.append(step)

    generics = list(generic_sites_for(profile))
    rng.shuffle(generics)
    total = total_steps if total_steps is not None else rng.randint(4, 7)
    for url in generics:
        if len(steps) >= total:
            break
        steps.append({"kind": "generic", "url": url, "follow_link": rng.random() < 0.35})
    # Targets lead the session; generic steps interleave after the first.
    if len(steps) > 2 and steps[0].get("kind") == "target":
        head, tail = steps[:1], steps[1:]
        rng.shuffle(tail)
        steps = head + tail
    return steps[:total]


# ── Scheduling ──────────────────────────────────────────────────────────────

MIN_GAP = timedelta(hours=3)


def start_of_today(now: datetime) -> str:
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def is_due(
    profile: dict[str, Any],
    *,
    runs_today: int,
    last_run_at: datetime | None,
    now: datetime,
) -> bool:
    """Whether the scheduler should start a warm-up for this profile now."""
    if not profile.get("warmup_enabled") or profile.get("deleted_at"):
        return False
    daily_max = int(profile.get("warmup_daily_max") or 1)
    if runs_today >= daily_max:
        return False
    if last_run_at is not None and now - last_run_at < MIN_GAP:
        return False
    return True


def identity_age(profile: dict[str, Any], stats: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """The profile's identity-age stats for display."""
    created_raw = profile.get("created_at")
    age_days = None
    if created_raw:
        try:
            created = datetime.fromisoformat(str(created_raw))
            if created.tzinfo is None:
                created = created.replace(tzinfo=now.tzinfo)
            age_days = max(0, (now - created).days)
        except ValueError:
            age_days = None
    return {
        "created_at": created_raw,
        "age_days": age_days,
        "warmup_sessions": int(stats.get("ok_runs") or 0),
        "warmup_runs_total": int(stats.get("total_runs") or 0),
        "last_warmup_at": stats.get("last_run_at"),
    }


def targets_done_today(runs_today: list[dict[str, Any]]) -> set[str]:
    """Platforms already aged today, from today's ok runs' details."""
    done: set[str] = set()
    for run in runs_today:
        if run.get("status") != "ok":
            continue
        detail = run.get("detail") or {}
        for platform_id in detail.get("targets") or []:
            if platform_id in TARGET_CATALOG:
                done.add(platform_id)
    return done


# ── Runner ──────────────────────────────────────────────────────────────────

_SEAT_MARKERS = ("session limit", "seat", "license", "licence", "并发", "授权", "concurren")

RecordFn = Callable[[dict[str, Any]], Any]
SleepFn = Callable[[float], Awaitable[None]]

_LINK_EXTRACT_JS = """
() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)
"""


def _classify_launch_error(exc: Exception) -> tuple[str, str]:
    message = f"{type(exc).__name__}: {exc}"
    if any(marker in message.lower() for marker in _SEAT_MARKERS):
        return "skipped", f"授权并发已满，本次跳过（{message[:120]}）"
    return "failed", message[:200]


async def run_warmup(
    profile: dict[str, Any],
    *,
    browser_mgr: Any,
    record_run: RecordFn,
    targets_done: set[str] | frozenset[str] = frozenset(),
    seed: Any = None,
    time_scale: float = 1.0,
    sleep: SleepFn = asyncio.sleep,
    plan_override: list[dict[str, Any]] | None = None,
    script_id: str | None = None,
) -> dict[str, Any]:
    """Run one warm-up session and record it. Returns the record dict.

    ``time_scale`` shrinks every dwell (tests use ~0); production uses 1,
    giving a randomized 3–8 minute session. The browser is closed in all
    outcomes once launched.

    ``plan_override`` supplies an externally built plan — an approved AI
    script compiled by :mod:`warmup_script` — in the exact step shape
    :func:`build_session_plan` returns. Execution semantics are identical
    either way (navigate, dwell, scroll; nothing else exists); the only
    addition is that a step may carry a ``dwell_scale`` share of the
    per-step budget, which template steps never set (default 1.0).
    """
    profile_id = profile["id"]
    started = datetime.now().astimezone()
    record: dict[str, Any] = {
        "profile_id": profile_id,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": None,
        "duration_s": None,
        "pages_visited": 0,
        "status": "failed",
        "reason": None,
        "detail": {"targets": [], "urls": [], "script_id": script_id},
    }

    def finish() -> dict[str, Any]:
        finished = datetime.now().astimezone()
        record["finished_at"] = finished.isoformat(timespec="seconds")
        record["duration_s"] = round((finished - started).total_seconds(), 1)
        record_run(dict(record))
        return record

    if profile_id in getattr(browser_mgr, "running", {}) or profile_id in getattr(browser_mgr, "_launching", set()):
        record.update(status="skipped", reason="画像正在使用中，本次跳过")
        return finish()

    rng = random.Random(f"cbm-warmup:{seed if seed is not None else profile_id}:{started.date()}")
    launched = False
    try:
        # Always headless: a scheduled warm-up must never open a window on
        # the user's desktop. Cookies and history still accrue — the run
        # uses the same user data dir, only the window is gone.
        running = await browser_mgr.launch(profile, launch_mode="debug", headless=True)
        launched = True
        context = getattr(running, "context", None)
        if context is None:
            record.update(status="failed", reason="调试模式没有拿到浏览器上下文")
            return finish()

        plan = plan_override if plan_override else build_session_plan(
            profile, rng, targets_done_today=set(targets_done)
        )
        record["detail"]["targets"] = [s["platform"] for s in plan if s.get("kind") == "target"]
        budget = rng.uniform(180.0, 480.0) * time_scale
        per_step = budget / max(1, len(plan))
        page = await context.new_page()
        session = behavior.HumanSession(
            page,
            seed=f"{profile_id}:warmup",
            strength="natural",
            sleep=sleep,
        )
        for step in plan:
            scale = step.get("dwell_scale")
            scale = float(scale) if isinstance(scale, (int, float)) and scale > 0 else 1.0
            try:
                await page.goto(step["url"], timeout=45_000, wait_until="domcontentloaded")
                record["pages_visited"] += 1
                record["detail"]["urls"].append(step["url"])
            except Exception:
                continue  # a dead landing page must not kill the session
            await session.read_page(per_step * scale * rng.uniform(0.5, 0.8))
            if step.get("search_url"):
                try:
                    await page.goto(step["search_url"], timeout=45_000, wait_until="domcontentloaded")
                    record["pages_visited"] += 1
                    record["detail"]["urls"].append(step["search_url"])
                    await session.read_page(per_step * scale * rng.uniform(0.4, 0.7))
                except Exception:
                    pass
            if step.get("follow_link"):
                try:
                    hrefs = await page.evaluate(_LINK_EXTRACT_JS)
                    home = step.get("search_url") or step["url"]
                    candidates = [
                        h for h in (hrefs or [])
                        if isinstance(h, str) and h != home and is_safe_follow_url(h, step["url"])
                    ]
                    if candidates:
                        link = rng.choice(candidates)
                        await page.goto(link, timeout=45_000, wait_until="domcontentloaded")
                        record["pages_visited"] += 1
                        record["detail"]["urls"].append(link)
                        await session.read_page(per_step * scale * rng.uniform(0.3, 0.6))
                except Exception:
                    pass
        record.update(status="ok")
    except Exception as exc:
        status, reason = _classify_launch_error(exc) if not launched else ("failed", f"{type(exc).__name__}: {exc}"[:200])
        record.update(status=status, reason=reason)
        if not launched:
            logger.info("Warm-up %s for %s: %s", status, profile_id, reason)
    finally:
        if launched:
            try:
                await browser_mgr.stop(profile_id, reason="养号完成")
            except Exception:
                logger.exception("Could not close %s after warm-up", profile_id)
    return finish()
