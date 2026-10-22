"""Behavior trace recording: timing/rhythm only, never content.

An opt-in recorder can be attached to a running debug session. An injected
page script reports mouse moves (thinned), clicks (down/up with position),
scrolls and key *timings* through a Playwright binding. Key events carry no
key value, no field identity and no page content — a trace can bias the
behavior engine's rhythm statistics (see ``behavior.bias_personality``)
without ever capturing what the user typed or read.

Traces are stored as JSON under ``<data_dir>/behavior-traces/<profile_id>/``.
"""

from __future__ import annotations

import json
import re
import statistics
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

TRACES_DIRNAME = "behavior-traces"
MAX_EVENTS = 200_000

# The injected listener. Timing and geometry only: for keydown it forwards
# nothing but the event kind — no ``e.key``, no target, no values.
RECORDER_SCRIPT = r"""
(() => {
  if (window.__cbmBehaviorRecorder) return;
  window.__cbmBehaviorRecorder = true;
  const send = (ev) => {
    try { window.__cbmBehaviorRecord(JSON.stringify(ev)); } catch (e) {}
  };
  const t0 = performance.now();
  const now = () => Math.round(performance.now() - t0);
  let lastMove = 0, lastX = -1, lastY = -1;
  window.addEventListener("mousemove", (e) => {
    const t = now();
    if (t - lastMove < 50) return;
    if (lastX >= 0 && Math.hypot(e.clientX - lastX, e.clientY - lastY) < 4) return;
    lastMove = t; lastX = e.clientX; lastY = e.clientY;
    send({type: "move", t, x: e.clientX, y: e.clientY});
  }, {passive: true, capture: true});
  window.addEventListener("mousedown", (e) => {
    send({type: "down", t: now(), x: e.clientX, y: e.clientY, button: e.button});
  }, {passive: true, capture: true});
  window.addEventListener("mouseup", (e) => {
    send({type: "up", t: now(), x: e.clientX, y: e.clientY, button: e.button});
  }, {passive: true, capture: true});
  window.addEventListener("wheel", (e) => {
    send({type: "scroll", t: now(), deltaY: Math.round(e.deltaY)});
  }, {passive: true, capture: true});
  window.addEventListener("keydown", () => {
    send({type: "key", t: now()});
  }, {passive: true, capture: true});
})();
"""


def extract_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Rhythm statistics of a trace: medians the engine can be biased with."""
    stats: dict[str, Any] = {"event_count": len(events)}
    key_times = [e["t"] for e in events if e.get("type") == "key" and isinstance(e.get("t"), (int, float))]
    if len(key_times) >= 3:
        gaps = [(b - a) / 1000.0 for a, b in zip(key_times, key_times[1:]) if 0 < b - a < 3000]
        if gaps:
            stats["median_key_interval_s"] = round(statistics.median(gaps), 4)
    moves = [e for e in events if e.get("type") == "move" and isinstance(e.get("t"), (int, float))]
    speeds: list[float] = []
    for a, b in zip(moves, moves[1:]):
        dt = (b["t"] - a["t"]) / 1000.0
        if 0 < dt <= 1.0 and all(isinstance(p.get(k), (int, float)) for p in (a, b) for k in ("x", "y")):
            dist = ((b["x"] - a["x"]) ** 2 + (b["y"] - a["y"]) ** 2) ** 0.5
            if dist > 0:
                speeds.append(dist / dt)
    if speeds:
        stats["median_move_speed_px_s"] = round(statistics.median(speeds), 1)
    downs = [e["t"] for e in events if e.get("type") == "down" and isinstance(e.get("t"), (int, float))]
    ups = [e["t"] for e in events if e.get("type") == "up" and isinstance(e.get("t"), (int, float))]
    presses = [u - d for d, u in zip(downs, ups) if 0 < u - d < 2000]
    if presses:
        stats["median_press_ms"] = round(statistics.median(presses), 1)
    if events:
        times = [e["t"] for e in events if isinstance(e.get("t"), (int, float))]
        if times:
            stats["duration_s"] = round((max(times) - min(times)) / 1000.0, 1)
    return stats


class BehaviorRecorder:
    """Attaches to one page and collects timing-only behavior events."""

    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        self.events: list[dict[str, Any]] = []
        self.started_at: datetime | None = None
        self.active = False
        self._overflowed = False

    async def start(self, page: Any) -> None:
        if self.active:
            return
        self.started_at = datetime.now().astimezone()
        self.active = True

        def _sink(_source: Any, payload: Any) -> None:
            if not self.active:
                return
            try:
                event = json.loads(payload) if isinstance(payload, str) else dict(payload)
            except (ValueError, TypeError):
                return
            if not isinstance(event, dict) or "type" not in event or "t" not in event:
                return
            if len(self.events) >= MAX_EVENTS:
                self._overflowed = True
                return
            self.events.append(event)

        await page.expose_binding("__cbmBehaviorRecord", _sink)
        await page.add_init_script(RECORDER_SCRIPT)
        # Pages already open need the script now, not just on next navigation.
        try:
            await page.evaluate(RECORDER_SCRIPT)
        except Exception:
            pass

    def stop(self) -> list[dict[str, Any]]:
        self.active = False
        return list(self.events)


# ── Storage ─────────────────────────────────────────────────────────────────


def _profile_dir(data_dir: Path, profile_id: str) -> Path:
    if not re.fullmatch(r"[\w.@-]+", profile_id or ""):
        raise FileNotFoundError(profile_id)
    return data_dir / TRACES_DIRNAME / profile_id


def save_trace(
    data_dir: Path,
    profile_id: str,
    events: list[dict[str, Any]],
    *,
    started_at: datetime | None,
) -> dict[str, Any]:
    folder = _profile_dir(data_dir, profile_id)
    folder.mkdir(parents=True, exist_ok=True)
    stopped_at = datetime.now().astimezone()
    trace_id = f"{stopped_at.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    payload = {
        "id": trace_id,
        "profile_id": profile_id,
        "started_at": started_at.isoformat(timespec="seconds") if started_at else None,
        "stopped_at": stopped_at.isoformat(timespec="seconds"),
        "stats": extract_stats(events),
        "events": events,
    }
    (folder / f"{trace_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return _meta(payload)


def _meta(payload: dict[str, Any]) -> dict[str, Any]:
    stats = payload.get("stats") or {}
    return {
        "id": payload.get("id"),
        "profile_id": payload.get("profile_id"),
        "started_at": payload.get("started_at"),
        "stopped_at": payload.get("stopped_at"),
        "event_count": stats.get("event_count", len(payload.get("events") or [])),
        "duration_s": stats.get("duration_s"),
        "stats": stats,
    }


def list_traces(data_dir: Path, profile_id: str) -> list[dict[str, Any]]:
    try:
        folder = _profile_dir(data_dir, profile_id)
    except FileNotFoundError:
        return []
    if not folder.is_dir():
        return []
    traces = []
    for path in sorted(folder.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        traces.append(_meta(payload))
    return traces


def load_trace(data_dir: Path, profile_id: str, trace_id: str) -> dict[str, Any]:
    folder = _profile_dir(data_dir, profile_id)
    if not re.fullmatch(r"[\w.@-]+", trace_id or ""):
        raise FileNotFoundError(trace_id)
    path = folder / f"{trace_id}.json"
    if not path.is_file():
        raise FileNotFoundError(trace_id)
    return json.loads(path.read_text(encoding="utf-8"))


def latest_trace_stats(data_dir: Path, profile_id: str) -> dict[str, Any] | None:
    """Stats of the profile's newest trace, or None when it has none."""
    traces = list_traces(data_dir, profile_id)
    if not traces:
        return None
    return traces[0].get("stats") or None
