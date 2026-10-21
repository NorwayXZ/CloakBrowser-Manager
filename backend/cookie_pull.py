"""Two-way cookie channel for browsers the Manager cannot drive over CDP.

Manual (no-CDP) launches are plain browser processes: the Manager holds no
Playwright context for them, so v0.5.11's pull/export could not read their
cookies. Those launches already load a per-profile local extension (the
one-time cookie importer in ``browser_manager``); that extension now also
answers pull requests:

* At launch the Manager generates a random per-profile token, embeds it in
  the extension and keeps it here. The token only ever authorises the two
  ``/ext/cookie-pull`` endpoints for that one profile.
* The extension polls ``GET /ext/cookie-pull/{id}/pending``; when a pull is
  pending it reads ``chrome.cookies.getAll({})`` and posts the entries back
  to ``POST /ext/cookie-pull/{id}/result``.
* ``request_cookies`` is the panel side: register a pending pull and wait
  (bounded) for the post-back.

Neither the token nor cookie values are ever logged — counts only.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cloakbrowser.manager.cookie_pull")

PULL_TIMEOUT_SECONDS = 20.0


class CookiePullTimeout(RuntimeError):
    """The extension did not answer a pull request in time."""


class CookiePullUnavailable(RuntimeError):
    """A pending pull ended without cookies (browser closed, superseded)."""


@dataclass
class _PendingPull:
    request_id: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    cookies: list[dict[str, Any]] | None = None
    error: str | None = None


class CookiePullChannel:
    """Per-profile tokens plus the pending-pull registry."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}
        self._pending: dict[str, _PendingPull] = {}

    # -- tokens -------------------------------------------------------------

    def register_token(self, profile_id: str) -> str:
        """Fresh token for a profile being launched; replaces any old one."""
        token = secrets.token_urlsafe(32)
        self._tokens[profile_id] = token
        return token

    def has_token(self, profile_id: str) -> bool:
        return profile_id in self._tokens

    def _token_valid(self, profile_id: str, token: str | None) -> bool:
        expected = self._tokens.get(profile_id)
        return bool(expected) and bool(token) and hmac.compare_digest(expected, token)

    def drop(self, profile_id: str) -> None:
        """Forget a profile's token and fail any pull still waiting on it."""
        self._tokens.pop(profile_id, None)
        pending = self._pending.pop(profile_id, None)
        if pending is not None and not pending.event.is_set():
            pending.error = "浏览器已关闭"
            pending.event.set()

    # -- panel side -----------------------------------------------------------

    async def request_cookies(
        self,
        profile_id: str,
        *,
        timeout: float = PULL_TIMEOUT_SECONDS,
    ) -> list[dict[str, Any]]:
        """Ask the profile's extension for its cookies and wait for them.

        Returns the raw ``chrome.cookies`` entries; converting them to the
        stored profile shape is the caller's job (``cookie_formats``).
        """
        previous = self._pending.get(profile_id)
        if previous is not None and not previous.event.is_set():
            previous.error = "已被新的导回请求取代"
            previous.event.set()
        pending = _PendingPull(request_id=secrets.token_urlsafe(16))
        self._pending[profile_id] = pending
        try:
            await asyncio.wait_for(pending.event.wait(), timeout)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise CookiePullTimeout(profile_id) from exc
        finally:
            if self._pending.get(profile_id) is pending:
                del self._pending[profile_id]
        if pending.error:
            raise CookiePullUnavailable(pending.error)
        return pending.cookies or []

    # -- extension side -------------------------------------------------------

    def pending_request(self, profile_id: str, token: str | None) -> str | None:
        """Request id the extension should answer, or None.

        A bad token is indistinguishable from "nothing pending" so the poll
        endpoint cannot be used to probe for valid tokens.
        """
        if not self._token_valid(profile_id, token):
            return None
        pending = self._pending.get(profile_id)
        if pending is None or pending.event.is_set():
            return None
        return pending.request_id

    def submit_result(
        self,
        profile_id: str,
        token: str | None,
        request_id: str | None,
        cookies: Any,
    ) -> bool:
        """Accept the extension's post-back for a pending pull."""
        if not self._token_valid(profile_id, token):
            return False
        pending = self._pending.get(profile_id)
        if (
            pending is None
            or pending.event.is_set()
            or not isinstance(request_id, str)
            or not hmac.compare_digest(pending.request_id, request_id)
            or not isinstance(cookies, list)
        ):
            return False
        pending.cookies = [item for item in cookies if isinstance(item, dict)]
        pending.event.set()
        logger.info(
            "Extension returned %d cookies for profile %s",
            len(pending.cookies),
            profile_id,
        )
        return True
