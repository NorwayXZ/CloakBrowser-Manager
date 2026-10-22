"""Manager-side behavior humanization engine （行为拟真引擎）.

Relationship to the profile's ``humanize`` / ``human_preset`` fields: those
are *kernel/wrapper* options — at launch the wrapper patches the Playwright
context (``cloakbrowser.human.patch_context_async``) so input injected
through that context carries human-like timing. They do nothing for manual
launches, and they do not decide *what* a session does: a Manager-driven
session that loads a page, sits perfectly still and leaves still looks like
a robot even with patched input primitives.

This module is the Manager-side complement: for sessions the Manager itself
drives through Playwright (fingerprint site checks, profile warm-up), a
:class:`HumanSession` wraps the Page and performs the *actions* — mouse
travel along curved eased paths, typing with a per-profile rhythm and
bounded mistakes, inertial scrolling, reading dwells — with a personality
derived deterministically from the profile, so the same profile behaves
like the same "person" on every run.

Nothing here logs typed text; the typing planner never sees field
semantics, and ``sensitive=True`` disables typos entirely.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import random
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable

# Strength presets scale how much human imperfection is layered on top of a
# plain action: "off" is the robot (instant, exact), "subtle" smooths the
# motion, "natural" adds the full personality (jitter, overshoot, typos).
PRESET_SCALES: dict[str, float] = {"off": 0.0, "subtle": 0.55, "natural": 1.0}

# QWERTY neighbours, used to pick plausible typos.
_KEY_NEIGHBORS: dict[str, str] = {
    "q": "wa", "w": "qeas", "e": "wrsd", "r": "etdf", "t": "ryfg",
    "y": "tugh", "u": "yijh", "i": "uojk", "o": "ipkl", "p": "ol",
    "a": "qwsz", "s": "awedxz", "d": "serfcx", "f": "drtgcv",
    "g": "ftyhvb", "h": "gyujnb", "j": "huiknm", "k": "jiolm",
    "l": "kop", "z": "asx", "x": "zsdc", "c": "xdfv", "v": "cfgb",
    "b": "vghn", "n": "bhjm", "m": "njk",
}


def _rng_for(seed: Any) -> random.Random:
    """A deterministic RNG stream for one seed (stable across runs)."""
    digest = hashlib.sha256(f"cbm-behavior:{seed}".encode("utf-8")).digest()
    return random.Random(digest)


def _ease(t: float) -> float:
    """Smoothstep: slow-fast-slow, monotonic on [0, 1]."""
    return t * t * (3.0 - 2.0 * t)


@dataclass(frozen=True)
class Personality:
    """One profile's behavioral fingerprint (all times in seconds)."""

    mouse_speed: float          # peak travel speed, px/s
    jitter_px: float            # mouse micro-jitter amplitude
    overshoot_chance: float     # probability of overshooting a long move
    key_interval: float         # mean delay between keystrokes
    key_jitter: float           # stddev of the keystroke delay
    typo_rate: float            # per-character typo probability
    word_pause: tuple[float, float]    # extra pause after a space
    press_ms: tuple[int, int]          # mouse down→up duration range
    scroll_burst_px: tuple[int, int]   # wheel delta per burst
    scroll_pause: tuple[float, float]  # pause between scroll bursts
    read_pause: tuple[float, float]    # pause while "reading" a page


def personality_for(seed: Any, strength: str = "natural") -> Personality:
    """Derive a profile's personality deterministically from its seed.

    The same seed always yields the same person; the strength preset scales
    only the imperfection amplitudes, never the identity ranges.
    """
    scale = PRESET_SCALES.get(strength, PRESET_SCALES["natural"])
    rng = _rng_for(f"personality:{seed}")
    return Personality(
        mouse_speed=rng.uniform(650.0, 1500.0),
        jitter_px=rng.uniform(0.6, 1.8) * scale,
        overshoot_chance=0.35 * scale,
        key_interval=rng.uniform(0.075, 0.16),
        key_jitter=rng.uniform(0.02, 0.05),
        typo_rate=rng.uniform(0.006, 0.028) * scale,
        word_pause=(0.12 * scale, 0.45 * scale),
        press_ms=(55, 160),
        scroll_burst_px=(180, 620),
        scroll_pause=(0.25, 0.9),
        read_pause=(0.8, 3.2),
    )


def bias_personality(personality: Personality, stats: dict[str, Any] | None) -> Personality:
    """Bias a personality toward a recorded trace's rhythm statistics.

    Only timing/speed medians are used, clamped to sane human ranges, so a
    trace can make the synthetic person type and move at *their* pace
    without importing anything else from the recording.
    """
    if not stats:
        return personality
    updates: dict[str, Any] = {}
    key_interval = stats.get("median_key_interval_s")
    if isinstance(key_interval, (int, float)) and key_interval > 0:
        updates["key_interval"] = min(0.4, max(0.03, float(key_interval)))
    move_speed = stats.get("median_move_speed_px_s")
    if isinstance(move_speed, (int, float)) and move_speed > 0:
        updates["mouse_speed"] = min(2600.0, max(220.0, float(move_speed)))
    press_ms = stats.get("median_press_ms")
    if isinstance(press_ms, (int, float)) and press_ms > 0:
        centre = min(400.0, max(30.0, float(press_ms)))
        updates["press_ms"] = (int(centre * 0.6), int(centre * 1.5))
    return replace(personality, **updates) if updates else personality


# ── Pure planners (unit-testable, no page involved) ─────────────────────────


def plan_mouse_path(
    rng: random.Random,
    start: tuple[float, float],
    end: tuple[float, float],
    personality: Personality,
) -> list[tuple[float, float, float]]:
    """Plan a mouse journey as ``(x, y, delay_before_point)`` steps.

    The path is a cubic Bézier whose control points bow off the straight
    line, sampled on an eased (slow-fast-slow) parameter so velocity rises
    and falls like a hand. Long moves may overshoot the target and correct.
    The final point is always exactly ``end``.
    """
    sx, sy = start
    ex, ey = end
    dist = math.hypot(ex - sx, ey - sy)
    if dist < 2.0:
        return [(ex, ey, 0.03)]
    targets: list[tuple[float, float]] = []
    if dist > 350.0 and rng.random() < personality.overshoot_chance:
        ux, uy = (ex - sx) / dist, (ey - sy) / dist
        over = dist * rng.uniform(0.03, 0.10)
        targets.append((ex + ux * over, ey + uy * over))
    targets.append((ex, ey))

    points: list[tuple[float, float, float]] = []
    cursor = (sx, sy)
    for tx, ty in targets:
        seg_dist = math.hypot(tx - cursor[0], ty - cursor[1])
        duration = min(2.5, max(0.08, seg_dist / personality.mouse_speed * rng.uniform(0.85, 1.25)))
        steps = max(4, min(120, int(duration / 0.016)))
        # Control points bowed perpendicular to the travel direction.
        bow = seg_dist * rng.uniform(0.05, 0.24) * rng.choice((-1.0, 1.0))
        dx, dy = tx - cursor[0], ty - cursor[1]
        px, py = (-dy / seg_dist, dx / seg_dist) if seg_dist else (0.0, 0.0)
        c1 = (cursor[0] + dx * 0.3 + px * bow, cursor[1] + dy * 0.3 + py * bow)
        c2 = (cursor[0] + dx * 0.7 + px * bow * rng.uniform(0.4, 1.0),
              cursor[1] + dy * 0.7 + py * bow * rng.uniform(0.4, 1.0))
        previous_t = 0.0
        for i in range(1, steps + 1):
            t = _ease(i / steps)
            mt = 1.0 - t
            x = (mt ** 3 * cursor[0] + 3 * mt * mt * t * c1[0]
                 + 3 * mt * t * t * c2[0] + t ** 3 * tx)
            y = (mt ** 3 * cursor[1] + 3 * mt * mt * t * c1[1]
                 + 3 * mt * t * t * c2[1] + t ** 3 * ty)
            if i < steps and personality.jitter_px > 0:
                x += rng.gauss(0.0, personality.jitter_px)
                y += rng.gauss(0.0, personality.jitter_px)
            points.append((x, y, duration * (t - previous_t)))
            previous_t = t
        cursor = (tx, ty)
    # Land exactly on the target regardless of jitter/rounding.
    lx, ly, ld = points[-1]
    points[-1] = (ex, ey, ld)
    return points


def plan_typing(
    rng: random.Random,
    text: str,
    personality: Personality,
    *,
    sensitive: bool = False,
) -> list[dict[str, Any]]:
    """Plan keystrokes as ``{kind, value, delay}`` events.

    ``kind`` is ``"char"`` (type the character) or ``"key"`` (a named key,
    currently only ``"Backspace"`` for typo correction). With
    ``sensitive=True`` no typos are planned and the caller must not log the
    plan. Typos are bounded: never on the first character, never twice
    within five characters, and the wrong key is a QWERTY neighbour.
    Replaying the plan always reproduces ``text`` exactly.
    """
    events: list[dict[str, Any]] = []
    last_typo_at = -10
    for index, ch in enumerate(text):
        delay = max(0.015, rng.gauss(personality.key_interval, personality.key_jitter))
        if index > 0 and text[index - 1] == " " and personality.word_pause[1] > 0:
            delay += rng.uniform(*personality.word_pause)
        if (
            not sensitive
            and ch.isalpha()
            and index > 0
            and index - last_typo_at >= 5
            and rng.random() < personality.typo_rate
        ):
            neighbours = _KEY_NEIGHBORS.get(ch.lower(), "")
            if neighbours:
                wrong = rng.choice(neighbours)
                if ch.isupper():
                    wrong = wrong.upper()
                events.append({"kind": "char", "value": wrong, "delay": delay})
                events.append({"kind": "key", "value": "Backspace",
                               "delay": rng.uniform(0.09, 0.22)})
                events.append({"kind": "char", "value": ch,
                               "delay": max(0.03, rng.gauss(personality.key_interval, personality.key_jitter))})
                last_typo_at = index
                continue
        events.append({"kind": "char", "value": ch, "delay": delay})
    return events


def plan_scroll(
    rng: random.Random,
    distance: float,
    personality: Personality,
) -> list[tuple[int, float]]:
    """Plan a scroll as ``(wheel_delta, delay_after)`` bursts.

    Bursts shrink as the target approaches (inertial deceleration) and the
    deltas always sum exactly to ``distance``.
    """
    total = int(round(distance))
    if total == 0:
        return []
    sign = 1 if total > 0 else -1
    remaining = abs(total)
    bursts: list[tuple[int, float]] = []
    progress = 0.0
    while remaining > 0:
        lo, hi = personality.scroll_burst_px
        hi = max(lo, int(hi * (1.0 - 0.55 * progress)))
        burst = min(remaining, rng.randint(lo, hi))
        delay = rng.uniform(*personality.scroll_pause) * (0.5 + progress)
        bursts.append((sign * burst, delay))
        remaining -= burst
        progress = 1.0 - remaining / abs(total)
    return bursts


# ── Session driver ──────────────────────────────────────────────────────────


SleepFn = Callable[[float], Awaitable[None]]


class HumanSession:
    """Drives one Playwright Page with a per-profile human personality."""

    def __init__(
        self,
        page: Any,
        *,
        seed: Any,
        strength: str = "natural",
        trace_stats: dict[str, Any] | None = None,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self.page = page
        self.strength = strength if strength in PRESET_SCALES else "natural"
        self.personality = bias_personality(personality_for(seed, self.strength), trace_stats)
        self.rng = _rng_for(f"session:{seed}")
        self._sleep = sleep
        self._pos: tuple[float, float] = (0.0, 0.0)

    # -- mouse -------------------------------------------------------------

    async def move_to(self, x: float, y: float) -> None:
        path = plan_mouse_path(self.rng, self._pos, (float(x), float(y)), self.personality)
        for px, py, delay in path:
            if delay > 0:
                await self._sleep(delay)
            await self.page.mouse.move(px, py)
        self._pos = (float(x), float(y))

    async def click(self, target: Any = None, *, button: str = "left") -> None:
        """Human-click a point ``(x, y)``, a locator, or the current spot."""
        if target is not None:
            point = await self._resolve_point(target)
            if point is not None:
                await self.move_to(*point)
            elif hasattr(target, "click"):
                await target.click()
                return
        await self._sleep(self.rng.uniform(0.03, 0.12))
        await self.page.mouse.down(button=button)
        await self._sleep(self.rng.uniform(*self.personality.press_ms) / 1000.0)
        await self.page.mouse.up(button=button)

    async def _resolve_point(self, target: Any) -> tuple[float, float] | None:
        if isinstance(target, (tuple, list)) and len(target) == 2:
            return float(target[0]), float(target[1])
        bounding_box = getattr(target, "bounding_box", None)
        if bounding_box is not None:
            box = await bounding_box()
            if box:
                # Land inside the element, off-centre like a hand would.
                ox = box["width"] * self.rng.uniform(-0.22, 0.22)
                oy = box["height"] * self.rng.uniform(-0.22, 0.22)
                return box["x"] + box["width"] / 2 + ox, box["y"] + box["height"] / 2 + oy
        return None

    # -- keyboard ----------------------------------------------------------

    async def type_text(
        self,
        text: str,
        *,
        sensitive: bool = False,
        locator: Any = None,
    ) -> None:
        """Type text with the personality's rhythm. Never logged.

        ``sensitive=True`` (passwords, tokens) disables typos; the plan is
        executed and discarded.
        """
        if locator is not None:
            await self.click(locator)
        plan = plan_typing(self.rng, text, self.personality, sensitive=sensitive)
        keyboard = self.page.keyboard
        for event in plan:
            if event["delay"] > 0:
                await self._sleep(event["delay"])
            if event["kind"] == "char":
                await keyboard.type(event["value"])
            else:
                await keyboard.press(event["value"])

    # -- scrolling / dwelling ----------------------------------------------

    async def scroll(self, delta_y: float) -> None:
        for chunk, delay in plan_scroll(self.rng, delta_y, self.personality):
            await self.page.mouse.wheel(0, chunk)
            if delay > 0:
                await self._sleep(delay)

    async def scroll_to(self, y: float) -> None:
        try:
            current = await self.page.evaluate("() => window.scrollY")
        except Exception:
            current = 0
        delta = float(y) - float(current or 0)
        if abs(delta) > 4:
            await self.scroll(delta)

    async def dwell(self, seconds: float) -> None:
        """Idle like a reading human: tiny drifts, rare micro-scrolls."""
        remaining = max(0.0, float(seconds))
        while remaining > 0:
            chunk = min(remaining, self.rng.uniform(0.4, 1.2))
            await self._sleep(chunk)
            remaining -= chunk
            if remaining <= 0:
                break
            roll = self.rng.random()
            if roll < 0.45:
                # Small unconscious hand drift.
                nx = self._pos[0] + self.rng.gauss(0.0, 6.0)
                ny = self._pos[1] + self.rng.gauss(0.0, 6.0)
                await self.page.mouse.move(max(0.0, nx), max(0.0, ny))
                self._pos = (max(0.0, nx), max(0.0, ny))
            elif roll < 0.58:
                await self.page.mouse.wheel(0, self.rng.randint(15, 70))

    async def read_page(self, seconds: float | None = None) -> None:
        """Dwell on a freshly loaded page, glancing down and back up."""
        pause = seconds if seconds is not None else self.rng.uniform(*self.personality.read_pause)
        await self.dwell(pause * 0.6)
        await self.scroll(self.rng.randint(220, 560))
        await self.dwell(pause * 0.4)

    async def settle(self, seconds: float = 3.0) -> None:
        """Short human presence after a page load (site checks, warm-up)."""
        budget = max(0.0, float(seconds))
        if budget == 0 or self.strength == "off":
            return
        await self.read_page(budget)
        await self.scroll_to(0)
