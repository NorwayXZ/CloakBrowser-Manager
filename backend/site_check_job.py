"""One fingerprint check at a time: open the profile in debug mode, visit the
detection sites, save the report, close the browser again."""

from __future__ import annotations

import asyncio
import logging
import platform
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from . import site_checks

logger = logging.getLogger(__name__)

# Profile fields that describe the fingerprint; never proxy credentials or cookies.
FINGERPRINT_FIELDS = (
    "browser_engine", "platform", "device_profile", "fingerprint_seed", "user_agent",
    "screen_width", "screen_height", "gpu_vendor", "gpu_renderer", "hardware_concurrency",
    "device_memory", "timezone", "locale", "geoip", "fingerprint_options",
)


def describe_environment(
    profile: dict[str, Any],
    running: Any,
    *,
    app_version: str | None,
    kernel_version: str | None,
    host_os: str,
) -> dict[str, Any]:
    geo = getattr(running, "proxy_geo", None) or {}
    proxy = str(profile.get("proxy") or "")
    return {
        "profile_name": profile.get("name"),
        "app_version": app_version,
        "kernel_version": kernel_version,
        "host_os": host_os,
        "host_os_version": platform.platform(),
        "launch_mode": "debug",
        "fingerprint": {key: profile.get(key) for key in FINGERPRINT_FIELDS},
        "effective_timezone": getattr(running, "effective_timezone", None),
        "effective_locale": getattr(running, "effective_locale", None),
        "proxy_type": proxy.split("://", 1)[0] if "://" in proxy else ("direct" if not proxy else "custom"),
        "exit_ip": geo.get("ip"),
        "exit_country": geo.get("country_code") or geo.get("country"),
        "exit_city": geo.get("city"),
    }


class SiteCheckJob:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {"phase": "idle"}
        self._task: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return self.state.get("phase") in {"launching", "checking", "closing"}

    def snapshot(self) -> dict[str, Any]:
        return dict(self.state)

    def start(
        self,
        profile: dict[str, Any],
        *,
        browser_mgr: Any,
        data_dir: Path,
        environment: Callable[[dict[str, Any], Any], dict[str, Any]],
        sites: tuple[site_checks.SiteCheck, ...] = site_checks.SITES,
    ) -> bool:
        if self.busy:
            return False
        self.state = {
            "phase": "launching", "profile_id": profile["id"], "profile_name": profile.get("name"),
            "index": 0, "total": len(sites), "site": None, "results": [],
        }
        self._task = asyncio.create_task(self._run(profile, browser_mgr, data_dir, environment, sites))
        return True

    async def _run(self, profile, browser_mgr, data_dir, environment, sites) -> None:
        profile_id = profile["id"]
        launched = False
        try:
            running = await browser_mgr.launch(profile, launch_mode="debug")
            launched = True
            if running.context is None:
                raise RuntimeError("调试模式没有拿到浏览器上下文")
            report_dir = site_checks.new_report_dir(data_dir, profile.get("name") or profile_id)
            self.state.update(phase="checking", report_id=report_dir.name)

            def progress(site_id, index, total, result):
                self.state.update(site=site_id, index=index, total=total)
                if result is not None:
                    self.state["results"] = [*self.state["results"], asdict(result)]

            report = await site_checks.run_checks(
                running.context, report_dir,
                environment=environment(profile, running),
                progress=progress, sites=sites,
            )
            self.state.update(phase="closing", overall=report["overall"])
        except Exception as exc:
            logger.exception("Fingerprint check failed for %s", profile_id)
            self.state.update(phase="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            if launched:
                try:
                    await browser_mgr.stop(profile_id, reason="指纹检测完成")
                except Exception:
                    logger.exception("Could not close %s after the check", profile_id)
            if self.state.get("phase") != "failed":
                self.state["phase"] = "done"
