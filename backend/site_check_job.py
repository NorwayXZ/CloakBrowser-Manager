"""One fingerprint check at a time: open the profile in debug mode, run the
local consistency probe and visit the detection sites, save the combined
report, close the browser again."""

from __future__ import annotations

import asyncio
import logging
import platform
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from . import behavior, behavior_traces, site_checks

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
        "profile_id": profile.get("id"),
        "profile_name": profile.get("name"),
        "app_version": app_version,
        "kernel_version": kernel_version,
        "host_os": host_os,
        "host_os_version": platform.platform(),
        "launch_mode": "debug",
        "fingerprint": {key: profile.get(key) for key in FINGERPRINT_FIELDS},
        "effective_timezone": getattr(running, "effective_timezone", None),
        "effective_locale": getattr(running, "effective_locale", None),
        "effective_screen": list(getattr(running, "screen", None) or []) or None,
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
        on_finish: Callable[[], None] | None = None,
    ) -> bool:
        if self.busy:
            return False
        self.state = {
            "phase": "launching", "profile_id": profile["id"], "profile_name": profile.get("name"),
            "index": 0, "total": len(sites), "site": None, "results": [],
        }
        self._task = asyncio.create_task(
            self._run(profile, browser_mgr, data_dir, environment, sites, on_finish)
        )
        return True

    async def _run(self, profile, browser_mgr, data_dir, environment, sites, on_finish=None) -> None:
        profile_id = profile["id"]
        launched = False
        try:
            running = await browser_mgr.launch(profile, launch_mode="debug")
            launched = True
            if running.context is None:
                raise RuntimeError("调试模式没有拿到浏览器上下文")
            report_dir = site_checks.new_report_dir(data_dir, profile.get("name") or profile_id)
            self.state.update(phase="checking", report_id=report_dir.name)
            env = environment(profile, running)

            # The Manager's own consistency probe runs on the same debug
            # context first; its items are folded into the stored report
            # ahead of the site verdicts. A probe failure must not cost the
            # whole check — the sites still run.
            local_results: list[site_checks.CheckResult] = []
            try:
                probe = await browser_mgr.fingerprint_report(profile)
                local_results = site_checks.local_probe_results(
                    probe.get("analysis") or {},
                    probe.get("raw") or {},
                    exit_ip=env.get("exit_ip"),
                )
            except Exception:
                logger.exception(
                    "Local fingerprint probe failed for %s; continuing with sites only",
                    profile_id,
                )
            if local_results:
                self.state["results"] = [asdict(r) for r in local_results]

            def progress(site_id, index, total, result):
                self.state.update(site=site_id, index=index, total=total)
                if result is not None:
                    self.state["results"] = [*self.state["results"], asdict(result)]

            # Behavior layer: the check session browses with the profile's
            # human personality (and its recorded rhythm, when a trace
            # exists) instead of teleporting between detection pages. The
            # kernel `humanize` profile option gates it — same switch the
            # user already controls for launch-time input patching.
            human_factory = None
            if profile.get("humanize", True):
                trace_stats = None
                try:
                    trace_stats = behavior_traces.latest_trace_stats(data_dir, profile_id)
                except Exception:
                    trace_stats = None
                seed = f"{profile_id}:{profile.get('fingerprint_seed')}"

                def human_factory(page, _seed=seed, _stats=trace_stats):
                    return behavior.HumanSession(
                        page, seed=_seed, strength="subtle", trace_stats=_stats
                    )

            report = await site_checks.run_checks(
                running.context, report_dir,
                environment=env,
                progress=progress, sites=sites,
                extra_results=local_results,
                human_factory=human_factory,
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
            if on_finish is not None:
                try:
                    on_finish()
                except Exception:
                    logger.exception("Site-check finish callback failed")
