"""AI warm-up scripts (AI 养号编排）: LLM intents → trusted session plans.

The LLM never writes URLs and never touches the browser. Offline, it
proposes a batch of *scripts* — each a theme plus a list of intents
(``{"type": "target"|"generic", "platform", "query", "dwell", "follow"}``).
This module compiles intents into exactly the step dicts
:func:`warmup.build_session_plan` produces, using only the trusted URL
builders in :mod:`warmup`. Anything the model invents that is not in the
catalog (unknown platform, a platform the profile did not choose, a URL —
the schema has no URL field at all) is dropped here, so a confused or
prompt-injected model can at worst suggest "a catalog platform plus one
search phrase".

Compilation is a pure function: no I/O, no randomness. Variety across days
comes from the batch itself (several variant scripts, rotated by date),
and the runner's own dwell/follow jitter is unchanged.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from . import warmup

# A script is one session's itinerary; the template builder emits 4–7
# steps, so cap scripts a little above that to keep sessions human-sized.
MAX_SCRIPT_STEPS = 8

QUERY_MAX_LEN = 80

# Dwell intent → share of the runner's per-step budget. The runner
# multiplies its existing per-step read time by ``dwell_scale``; the
# template path has no scale and behaves exactly as before (1.0).
DWELL_SCALES: dict[str, float] = {"short": 0.6, "medium": 1.0, "long": 1.5}
DEFAULT_DWELL = "medium"

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")


def sanitize_query(raw: Any) -> str | None:
    """Clean an LLM-proposed search query; None when nothing usable remains."""
    if not isinstance(raw, str):
        return None
    cleaned = _WHITESPACE.sub(" ", _CONTROL_CHARS.sub(" ", raw)).strip()
    if not cleaned:
        return None
    return cleaned[:QUERY_MAX_LEN].strip() or None


def _dwell_of(intent: dict[str, Any]) -> str:
    dwell = str(intent.get("dwell") or "").strip().lower()
    return dwell if dwell in DWELL_SCALES else DEFAULT_DWELL


def compile_intents(profile: dict[str, Any], intents: Any) -> list[dict[str, Any]]:
    """Compile raw LLM intents into session-plan steps for ``profile``.

    Output shape mirrors :func:`warmup.build_session_plan`: target steps
    carry ``kind/platform/url`` plus optional ``search_url/search_query``;
    generic steps carry ``kind/url``; every step carries ``follow_link``
    and the ``dwell``/``dwell_scale`` pair. Intents that reference unknown
    or unchosen platforms, unknown types, or nothing at all are dropped.
    """
    if not isinstance(intents, list):
        return []
    chosen = {
        t for t in (profile.get("warmup_targets") or [])
        if isinstance(t, str) and t in warmup.TARGET_CATALOG
    }
    generics = warmup.generic_sites_for(profile)
    steps: list[dict[str, Any]] = []
    generic_cursor = 0
    for intent in intents:
        if len(steps) >= MAX_SCRIPT_STEPS:
            break
        if not isinstance(intent, dict):
            continue
        dwell = _dwell_of(intent)
        kind = str(intent.get("type") or "").strip().lower()
        if kind == "target":
            platform = intent.get("platform")
            if not isinstance(platform, str) or platform not in chosen:
                continue
            step: dict[str, Any] = {
                "kind": "target",
                "platform": platform,
                "url": warmup.target_home_url(platform, profile),
            }
            query = sanitize_query(intent.get("query"))
            if query:
                search_url = warmup.target_search_url(platform, profile, query)
                if search_url:
                    step["search_url"] = search_url
                    step["search_query"] = query
            step["follow_link"] = bool(intent.get("follow"))
            step["dwell"] = dwell
            step["dwell_scale"] = DWELL_SCALES[dwell]
            steps.append(step)
        elif kind == "generic":
            if not generics:
                continue
            url = generics[generic_cursor % len(generics)]
            generic_cursor += 1
            steps.append({
                "kind": "generic",
                "url": url,
                "follow_link": bool(intent.get("follow")),
                "dwell": dwell,
                "dwell_scale": DWELL_SCALES[dwell],
            })
        # Unknown intent types are dropped silently: the schema is a
        # whitelist, and anything else the model emits is not a verb the
        # runner knows — by construction it can never become an action.
    return steps


def validate_scripts_payload(data: Any) -> list[dict[str, Any]]:
    """Normalize an LLM response payload into ``[{theme, intents}]``.

    Accepts either ``{"scripts": [...]}`` or a bare list. Scripts whose
    intents are not a list are dropped; individual bad intents are the
    compiler's problem, not this function's.
    """
    if isinstance(data, dict):
        data = data.get("scripts")
    if not isinstance(data, list):
        return []
    scripts: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        intents = item.get("intents")
        if not isinstance(intents, list):
            continue
        theme = item.get("theme")
        scripts.append({
            "theme": theme.strip()[:120] if isinstance(theme, str) else "",
            "intents": intents,
        })
    return scripts


def pick_script_for_date(scripts: list[dict[str, Any]], on_date: date) -> dict[str, Any] | None:
    """Rotate through an approved batch by calendar date (deterministic).

    Consecutive days walk the whole batch before repeating, so a profile
    never runs the identical itinerary twice in a row (unless the batch
    has a single script).
    """
    if not scripts:
        return None
    return scripts[on_date.toordinal() % len(scripts)]


def drop_done_targets(
    steps: list[dict[str, Any]],
    targets_done: set[str] | frozenset[str],
) -> list[dict[str, Any]]:
    """Remove target steps whose platform already hit today's cap.

    Mirrors the template builder's ``targets_done_today`` behaviour so the
    per-platform daily cap holds no matter where the plan came from.
    """
    if not targets_done:
        return steps
    return [
        step for step in steps
        if not (step.get("kind") == "target" and step.get("platform") in targets_done)
    ]
