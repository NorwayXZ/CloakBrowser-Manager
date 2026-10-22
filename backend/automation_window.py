"""Allowed-hours window for *scheduled* browser automation.

Automations (warm-up, evolution cycles) launch browsers on their own
schedule. Outside the hours the user picked, a scheduled run must not
pop up — it defers instead. Manual triggers ignore the window entirely;
this module only answers "is scheduled automation allowed right now?".

The setting lives in the settings table under ``automation_hours`` as a
local-time ``"HH-HH"`` range (e.g. ``"09-18"``, or the overnight
``"23-07"``). Missing/empty/invalid means no restriction.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable

SETTING_KEY = "automation_hours"

_RANGE_RE = re.compile(r"^\s*(\d{1,2})\s*-\s*(\d{1,2})\s*$")

# (start_hour, end_hour), local time, [start, end); start > end wraps midnight.
Window = tuple[int, int]


def parse_window(raw: str | None) -> Window | None:
    """Parse an ``"HH-HH"`` range; None means "no restriction".

    Equal hours (``"09-09"``) would describe an empty range, so they are
    treated as no restriction rather than "never allowed".
    """
    if not raw:
        return None
    match = _RANGE_RE.match(str(raw))
    if not match:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    if not (0 <= start <= 23 and 0 <= end <= 23) or start == end:
        return None
    return (start, end)


def is_valid_window_text(raw: str | None) -> bool:
    """True for empty (no restriction) or a parseable range."""
    if raw is None or not str(raw).strip():
        return True
    return parse_window(raw) is not None


def format_window(window: Window) -> str:
    return f"{window[0]:02d}-{window[1]:02d}"


def describe_window(window: Window) -> str:
    return f"{window[0]:02d}:00–{window[1]:02d}:00"


def is_open(now: datetime, window: Window | None) -> bool:
    """Whether local time ``now`` falls inside the window."""
    if window is None:
        return True
    start, end = window
    hour = now.hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # overnight range, e.g. 23-07


def read_window(get_setting: Callable[[str], str | None]) -> Window | None:
    return parse_window(get_setting(SETTING_KEY))


def window_open_now(
    get_setting: Callable[[str], str | None],
    *,
    now: datetime | None = None,
) -> bool:
    return is_open(now or datetime.now().astimezone(), read_window(get_setting))
