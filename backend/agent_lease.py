"""Advisory per-profile control leases for AI agents.

A profile is a real browser identity that a person may be using at the same
time. A lease says "someone is driving this profile right now" so an agent does
not start clicking in a window the user is typing in, and two agents do not
fight over one profile.

* An agent takes (or renews) the lease on every browser-layer tool call.
* The person can take over from the panel: that parks the lease on ``human``
  for a while, and agents get ``profile_leased`` until the person hands it
  back (or it expires).
* Leases are in memory and expire on their own; they never outlive the
  Manager, and stopping a profile drops its lease.

The registry only keeps the books. Cutting a taken-over agent's live CDP
connections is the Manager's job (see ``main.py``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

HUMAN = "human"
KIND_AGENT = "agent"
KIND_HUMAN = "human"

# Renewed by every browser-layer call; short so a crashed agent frees the profile soon.
DEFAULT_TTL_S = 5 * 60
HUMAN_TTL_S = 30 * 60
MAX_TTL_S = 4 * 60 * 60


@dataclass(frozen=True)
class Lease:
    profile_id: str
    holder: str
    kind: str  # "agent" | "human"
    acquired_at: float
    expires_at: float


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


class LeaseRegistry:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._leases: dict[str, Lease] = {}

    def get(self, profile_id: str) -> Lease | None:
        lease = self._leases.get(profile_id)
        if lease is not None and lease.expires_at <= self._clock():
            del self._leases[profile_id]
            return None
        return lease

    def acquire(
        self, profile_id: str, holder: str, ttl: float = DEFAULT_TTL_S
    ) -> tuple[bool, Lease]:
        """Take or renew the lease. ``(False, current)`` when someone else holds it."""
        holder = holder.strip() or "agent"
        ttl = max(1.0, min(float(ttl), MAX_TTL_S))
        now = self._clock()
        current = self.get(profile_id)
        if current is not None and current.holder != holder:
            return False, current
        lease = Lease(
            profile_id=profile_id,
            holder=holder,
            kind=KIND_HUMAN if holder == HUMAN else KIND_AGENT,
            acquired_at=current.acquired_at if current is not None else now,
            expires_at=now + ttl,
        )
        self._leases[profile_id] = lease
        return True, lease

    def takeover(self, profile_id: str, ttl: float = HUMAN_TTL_S) -> Lease:
        """The person forces the lease onto themselves, whoever held it."""
        now = self._clock()
        lease = Lease(
            profile_id=profile_id,
            holder=HUMAN,
            kind=KIND_HUMAN,
            acquired_at=now,
            expires_at=now + max(1.0, min(float(ttl), MAX_TTL_S)),
        )
        self._leases[profile_id] = lease
        return lease

    def release(self, profile_id: str, holder: str | None = None) -> bool:
        """Drop the lease. ``holder=None`` forces it (the person handing back)."""
        current = self.get(profile_id)
        if current is None:
            return False
        if holder is not None and current.holder != holder:
            return False
        del self._leases[profile_id]
        return True

    def clear_profile(self, profile_id: str) -> None:
        self._leases.pop(profile_id, None)

    def describe(self, profile_id: str) -> dict | None:
        lease = self.get(profile_id)
        if lease is None:
            return None
        return {
            "holder": lease.holder,
            "kind": lease.kind,
            "acquired_at": _iso(lease.acquired_at),
            "expires_at": _iso(lease.expires_at),
            "seconds_left": max(0, int(lease.expires_at - self._clock())),
        }
