"""Self-adversarial evolution loop （自对抗进化闭环）.

The one-click detection report says *what* failed; this module closes the
loop without ever gambling with the user's real profiles:

1. **Attribution** — each failing/warning report item is mapped to the
   Manager-layer knobs that plausibly cause it (fingerprint noise,
   storage quota, Windows font metrics, the device template's GPU).
   Items whose causes live elsewhere (egress-IP reputation, kernel
   signals, proxy plumbing) are labelled 不可自动修复 with the reason —
   no fake fixes are ever generated for them.
2. **Experiments** — a candidate is applied to ONE disposable clone of
   the profile at a time, the detection battery re-runs on the clone,
   and the clone's report is scored against the source report. The
   clone is burned in every outcome.
3. **Approval gate** — a winning candidate becomes a *proposal*. The
   real profile changes only when the user approves the proposal in
   the panel, through the normal profile-update path.

All browser automation is serialized through one module-level lock
(shared with the site-check and warm-up entry points): the free
license has a single seat, and two automations racing helps nobody.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from . import device_templates, site_checks
from .fingerprint_options import RECOMMENDED_NEW_PROFILE_OPTIONS, parse_fingerprint_options

logger = logging.getLogger(__name__)

MAX_EXPERIMENTS_PER_CYCLE = 3

SEVERITY = {"pass": 0, "warn": 1, "fail": 2, "unknown": 3, "error": 3}

# Same markers warm-up uses to recognise a taken license seat.
_SEAT_MARKERS = ("session limit", "seat", "license", "licence", "并发", "授权", "concurren")
_PROFILE_RUNNING_MARKERS = ("正在运行", "请先关闭", "already running")


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def is_seat_error(error: str | None) -> bool:
    text = (error or "").lower()
    return any(marker in text for marker in _SEAT_MARKERS)


# ── Automation lock ──────────────────────────────────────────────────────────


class AutomationLock:
    """One browser automation at a time (site check / warm-up / evolution).

    The lock is advisory and self-healing: main.py registers a ``truth``
    callback reporting which automation is *actually* running, so a lock
    whose owner finished without releasing (crash, fake in tests) never
    blocks the others forever.
    """

    def __init__(self) -> None:
        self._owner: str | None = None
        self.truth: Callable[[], str | None] | None = None

    @property
    def owner(self) -> str | None:
        actual = self.truth() if self.truth else None
        if actual is not None:
            self._owner = actual
        elif self._owner is not None and self.truth is not None:
            # Recorded owner is not actually running any more — stale.
            self._owner = None
        return self._owner

    def try_acquire(self, owner: str) -> bool:
        current = self.owner
        if current is not None and current != owner:
            return False
        self._owner = owner
        return True

    def release(self, owner: str) -> None:
        if self._owner == owner:
            self._owner = None


AUTOMATION_LOCK = AutomationLock()


# ── Attribution: report problems → candidate fixes ───────────────────────────

KNOB_NOISE = "fingerprint_options.noise"
KNOB_STORAGE = "fingerprint_options.storage_quota_mb"
KNOB_FONT_METRICS = "fingerprint_options.windows_font_metrics"
KNOB_TEMPLATE = "device_template"

_KNOB_LABELS = {
    KNOB_NOISE: "关闭指纹噪声",
    KNOB_STORAGE: "存储配额改为 50GB",
    KNOB_FONT_METRICS: "开启 Windows 字体度量",
    KNOB_TEMPLATE: "更换设备模板（GPU）",
}

_NOISE_RATIONALE = (
    "指纹噪声扰动（Canvas/Audio）是 lies 与稳定性异常的已知成因："
    "成绩单实测关闭噪声后 CreepJS 的 lies 清零、BrowserScan 的音频异常消失"
)
_STORAGE_RATIONALE = (
    "内核按种子派生的默认存储配额读起来像无痕模式的上限，"
    "实测显式设为 50GB 后 BrowserScan 的「无痕」扣分消失"
)
_FONT_METRICS_RATIONALE = "Windows 字体度量让字体测量结果与真实 Windows 机器一致"
_TEMPLATE_RATIONALE = "WebGL 渲染器与画像不自洽时，更换设备模板的 GPU 是配置层可调的成因"

_NOISE_EXHAUSTED_REASON = "指纹噪声已经关闭仍未通过，剩余信号（headless/stealth 等）在内核层"

_UNFIXABLE_REASONS = {
    "fingerprint": "结论主要受出口 IP 信誉与检测方服务端信号影响，Manager 配置层没有对应开关",
    "iphey": "结论主要受出口 IP 信誉影响，Manager 配置层没有对应开关",
    "pixelscan": "结论受出口 IP 信誉与内核级伪装检测影响，Manager 配置层没有对应开关",
    "sannysoft": "webdriver / headless 等信号在内核层，配置层改不了",
    "browserleaks_webrtc": "WebRTC 泄漏与代理通道/内核有关；自动改 WebRTC 出口 IP 有填错反而泄漏的风险，不自动处理",
    "local_egress_ip": "出口 IP 属于网络层（代理/线路），不是画像配置能改的",
    "local_webdriver": "webdriver 标记在内核层",
    "local_native": "原生函数完整性属于内核层信号",
    "local_webrtc": "WebRTC 本地候选与代理通道/内核有关，不自动修改",
}


@dataclass
class Candidate:
    knob: str
    label: str
    from_value: Any
    to_value: Any
    targets: list[str] = field(default_factory=list)
    rationale: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.knob, repr(self.to_value))

    def as_dict(self) -> dict[str, Any]:
        return {
            "knob": self.knob,
            "label": self.label,
            "from_value": self.from_value,
            "to_value": self.to_value,
            "targets": list(self.targets),
            "rationale": self.rationale,
        }


def _pick_gpu_template(profile: dict[str, Any]) -> dict[str, Any] | None:
    """A template with a different GPU, preferring the same screen size."""
    templates = device_templates.list_templates()
    current_id = profile.get("device_profile")
    current_renderer = profile.get("gpu_renderer")
    pool = [
        tpl for tpl in templates
        if tpl["id"] != current_id and tpl.get("gpu_renderer") != current_renderer
    ]
    if not pool:
        return None
    same_screen = [
        tpl for tpl in pool
        if tpl["screen_width"] == profile.get("screen_width")
        and tpl["screen_height"] == profile.get("screen_height")
    ]
    return (same_screen or pool)[0]


def attribute(profile: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Map a report's problems to candidate fixes and unfixable labels.

    Returns {"candidates": [Candidate, ...], "unfixable": [{site, name,
    status, reason}, ...]}. Candidates are deduped: one knob change may
    target several report items and is then tested once.
    """
    options = parse_fingerprint_options(profile)
    noise_open = options.noise is not False  # None (kernel decides) counts as open
    quota = options.storage_quota_mb
    recommended_quota = RECOMMENDED_NEW_PROFILE_OPTIONS["storage_quota_mb"]
    is_windows = profile.get("platform") == "windows"

    candidates: dict[tuple[str, str], Candidate] = {}
    unfixable: list[dict[str, Any]] = []

    def add(knob: str, to_value: Any, from_value: Any, site: str, rationale: str) -> None:
        candidate = candidates.get((knob, repr(to_value)))
        if candidate is None:
            candidate = Candidate(
                knob=knob,
                label=_KNOB_LABELS[knob],
                from_value=from_value,
                to_value=to_value,
                rationale=rationale,
            )
            candidates[candidate.key] = candidate
        if site not in candidate.targets:
            candidate.targets.append(site)

    for result in report.get("results") or []:
        if not isinstance(result, dict):
            continue
        status = result.get("status")
        if status not in ("fail", "warn"):
            continue
        site = str(result.get("site") or "")
        name = str(result.get("name") or site)
        covered = False

        if site in ("creepjs", "local_canvas", "local_audio"):
            if noise_open:
                add(KNOB_NOISE, False, options.noise, site, _NOISE_RATIONALE)
                covered = True
            else:
                unfixable.append({
                    "site": site, "name": name, "status": status,
                    "reason": _NOISE_EXHAUSTED_REASON,
                })
                continue
        if site == "browserscan":
            if quota != recommended_quota:
                add(KNOB_STORAGE, recommended_quota, quota, site, _STORAGE_RATIONALE)
                covered = True
            if noise_open:
                add(KNOB_NOISE, False, options.noise, site, _NOISE_RATIONALE)
                covered = True
        if site == "local_storage":
            if quota != recommended_quota:
                add(KNOB_STORAGE, recommended_quota, quota, site, _STORAGE_RATIONALE)
                covered = True
        if site == "local_gpu" and is_windows:
            tpl = _pick_gpu_template(profile)
            if tpl is not None:
                add(KNOB_TEMPLATE, tpl["id"], profile.get("device_profile"), site, _TEMPLATE_RATIONALE)
                covered = True
        if site == "local_fonts" and is_windows and not options.windows_font_metrics:
            add(KNOB_FONT_METRICS, True, options.windows_font_metrics, site, _FONT_METRICS_RATIONALE)
            covered = True

        if covered:
            continue
        if site in _UNFIXABLE_REASONS:
            reason = _UNFIXABLE_REASONS[site]
        elif site.startswith("local_"):
            reason = f"「{name}」是画像配置一致性问题，需要人工核对画像设置，没有可安全自动调整的开关"
        elif site in site_checks.IP_DEPENDENT_SITES:
            reason = "结论受出口 IP 信誉影响，Manager 配置层没有对应开关"
        else:
            reason = "没有找到对应的 Manager 配置层成因"
        unfixable.append({"site": site, "name": name, "status": status, "reason": reason})

    ordered = sorted(
        candidates.values(),
        key=lambda c: (-len(c.targets), c.knob),
    )
    return {"candidates": ordered, "unfixable": unfixable}


# ── Scoring an experiment ────────────────────────────────────────────────────


def _status_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(r["site"]): r
        for r in report.get("results") or []
        if isinstance(r, dict) and r.get("site")
    }


def _severity(status: str | None, site: str) -> int:
    if status is None:
        # Local probe items vanish from a report when healthy; site items
        # are always produced, so a missing one means "not measured".
        return 0 if site.startswith("local_") else SEVERITY["error"]
    return SEVERITY.get(status, SEVERITY["error"])


def score_experiment(
    before_report: dict[str, Any],
    after_report: dict[str, Any],
    candidate: Candidate,
) -> dict[str, Any]:
    """Did the clone's change help the targeted items without regressions?"""
    before = _status_map(before_report)
    after = _status_map(after_report)

    targets: dict[str, dict[str, Any]] = {}
    gain = 0
    for site in candidate.targets:
        from_status = (before.get(site) or {}).get("status")
        to_status = (after.get(site) or {}).get("status")
        targets[site] = {"from": from_status, "to": to_status}
        gain += _severity(from_status, site) - _severity(to_status, site)

    regressions: list[dict[str, Any]] = []
    for site, result in after.items():
        if site in candidate.targets:
            continue
        from_status = (before.get(site) or {}).get("status")
        to_status = result.get("status")
        if _severity(to_status, site) > _severity(from_status, site):
            regressions.append({
                "site": site,
                "name": result.get("name") or site,
                "from": from_status,
                "to": to_status,
            })

    if regressions or gain < 0:
        verdict = "regressed"
    elif gain > 0:
        verdict = "improved"
    else:
        verdict = "no_change"
    return {"verdict": verdict, "targets": targets, "regressions": regressions, "gain": gain}


# ── Applying a candidate (shared by experiments and proposal approval) ──────


def update_kwargs(profile: dict[str, Any], knob: str, to_value: Any) -> dict[str, Any]:
    """db.update_profile kwargs that set one knob on a profile."""
    if knob.startswith("fingerprint_options."):
        field_name = knob.split(".", 1)[1]
        merged = dict(profile.get("fingerprint_options") or {})
        merged[field_name] = to_value
        return {"fingerprint_options": merged}
    if knob == KNOB_TEMPLATE:
        tpl = device_templates.get_template(str(to_value))
        if tpl is None:
            raise ValueError(f"设备模板不存在：{to_value}")
        return {
            "platform": "windows",
            "device_profile": tpl["id"],
            "screen_width": tpl["screen_width"],
            "screen_height": tpl["screen_height"],
            "gpu_vendor": tpl["gpu_vendor"],
            "gpu_renderer": tpl["gpu_renderer"],
            "hardware_concurrency": tpl["hardware_concurrency"],
            "device_memory": tpl["device_memory"],
        }
    raise ValueError(f"未知的进化旋钮：{knob}")


# ── Scheduling ───────────────────────────────────────────────────────────────


def is_due(profile: dict[str, Any], *, last_cycle_at: str | None, now: datetime) -> bool:
    """Whether the scheduler should start an evolution cycle now."""
    if not profile.get("evolution_enabled") or profile.get("deleted_at"):
        return False
    if last_cycle_at is None:
        return True
    try:
        last = datetime.fromisoformat(str(last_cycle_at))
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=now.tzinfo)
    interval = timedelta(hours=int(profile.get("evolution_interval_hours") or 24))
    return now - last >= interval


# ── The cycle engine (dependencies injected for testability) ──────────────────


@dataclass
class CheckOutcome:
    report: dict[str, Any] | None
    error: str | None = None


@dataclass
class EngineDeps:
    run_check: Callable[[dict[str, Any]], Awaitable[CheckOutcome]]
    make_clone: Callable[[dict[str, Any]], dict[str, Any]]
    apply_change: Callable[[dict[str, Any], Candidate], dict[str, Any]]
    burn: Callable[[dict[str, Any]], Awaitable[None]]
    record_log: Callable[[dict[str, Any]], str]
    update_log: Callable[[str, dict[str, Any]], None]
    file_proposal: Callable[[dict[str, Any]], str]


class EvolutionEngine:
    def __init__(
        self,
        deps: EngineDeps,
        *,
        lock: AutomationLock = AUTOMATION_LOCK,
        scheduled_defer: Callable[[], str | None] | None = None,
    ) -> None:
        self.deps = deps
        self.lock = lock
        # Optional gate for *scheduled* cycles only (e.g. outside the
        # user's automation hours): returns a defer reason, or None to
        # proceed. Manual cycles never consult it. A deferred cycle is
        # logged like a seat-busy one and does not advance the cadence
        # clock (see db.last_evolution_cycle_at).
        self.scheduled_defer = scheduled_defer

    async def run_cycle(self, source: dict[str, Any], *, trigger: str) -> dict[str, Any]:
        """One full cycle; returns the finished log-entry fields.

        Never mutates ``source``: checks run on it read-only (the check
        itself launches/closes it, as a manual check would), experiments
        run on disposable clones, and wins are filed as proposals.
        """
        deps = self.deps
        started = _now()
        entry: dict[str, Any] = {
            "profile_id": source.get("id"),
            "profile_name": source.get("name"),
            "started_at": _iso(started),
            "finished_at": None,
            "trigger": trigger,
            "outcome": "running",
            "summary": "进化周期进行中",
            "detail": {"experiments": [], "unfixable": [], "proposals": []},
        }
        log_id = deps.record_log(entry)
        detail = entry["detail"]

        def finish(outcome: str, summary: str) -> dict[str, Any]:
            entry.update(
                outcome=outcome, summary=summary, finished_at=_iso(_now()),
            )
            deps.update_log(log_id, {
                "outcome": outcome, "summary": summary,
                "finished_at": entry["finished_at"], "detail": detail,
            })
            return entry

        if not self.lock.try_acquire("evolution"):
            return finish("deferred", f"另一个自动化（{self.lock.owner}）正在运行，本轮推迟")

        try:
            if trigger == "scheduled" and self.scheduled_defer is not None:
                defer_reason = self.scheduled_defer()
                if defer_reason:
                    return finish("deferred", defer_reason)
            outcome = await deps.run_check(source)
            if outcome.report is None:
                error = outcome.error or "检测没有完成"
                if is_seat_error(error):
                    return finish("deferred", f"授权并发已满，本轮推迟（{error[:120]}）")
                if any(marker in error for marker in _PROFILE_RUNNING_MARKERS):
                    return finish("deferred", f"画像正在使用中，本轮推迟（{error[:120]}）")
                return finish("check_failed", f"源画像检测失败：{error[:160]}")
            source_report = outcome.report
            detail["source_report_id"] = source_report.get("id")

            found = attribute(source, source_report)
            candidates: list[Candidate] = found["candidates"]
            detail["unfixable"] = found["unfixable"]
            problems = sum(1 for r in source_report.get("results") or []
                           if isinstance(r, dict) and r.get("status") in ("fail", "warn"))
            detail["problem_count"] = problems

            if problems == 0:
                return finish("clean", "源画像检测全部通过，没有需要修复的问题")
            if not candidates:
                return finish(
                    "unfixable_only",
                    f"检测发现 {problems} 个问题，但都不在 Manager 配置层可修复范围（见战报明细）",
                )

            proposals_before = len(detail["proposals"])
            ran = 0
            seat_hit = False
            for candidate in candidates[:MAX_EXPERIMENTS_PER_CYCLE]:
                experiment = await self._run_experiment(source, source_report, candidate, detail)
                detail["experiments"].append(experiment)
                if experiment["verdict"] == "deferred":
                    seat_hit = True
                    break
                ran += 1

            filed = len(detail["proposals"]) - proposals_before
            if ran == 0 and seat_hit:
                return finish("deferred", "实验阶段授权并发被占用，本轮推迟")
            improved = sum(1 for e in detail["experiments"] if e["verdict"] == "improved")
            return finish(
                "experiments",
                f"检测发现 {problems} 个问题，克隆实验 {ran} 个：{improved} 个有效"
                + (f"，已生成 {filed} 条待批准提案" if filed else "，没有生成提案"),
            )
        except Exception as exc:  # the cycle must always leave a log entry
            logger.exception("Evolution cycle failed for %s", source.get("id"))
            return finish("error", f"进化周期出错：{type(exc).__name__}: {exc}"[:200])
        finally:
            self.lock.release("evolution")

    async def _run_experiment(
        self,
        source: dict[str, Any],
        source_report: dict[str, Any],
        candidate: Candidate,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        deps = self.deps
        experiment: dict[str, Any] = {
            **candidate.as_dict(),
            "verdict": "error",
            "targets_detail": {},
            "regressions": [],
            "clone_report_id": None,
            "note": None,
        }
        clone: dict[str, Any] | None = None
        try:
            clone = deps.make_clone(source)
            experiment["clone_id"] = clone.get("id")
            clone = deps.apply_change(clone, candidate)
            outcome = await deps.run_check(clone)
            if outcome.report is None:
                error = outcome.error or "克隆检测没有完成"
                if is_seat_error(error):
                    experiment["verdict"] = "deferred"
                experiment["note"] = error[:200]
                return experiment
            clone_report = outcome.report
            experiment["clone_report_id"] = clone_report.get("id")
            scored = score_experiment(source_report, clone_report, candidate)
            experiment["verdict"] = scored["verdict"]
            experiment["targets_detail"] = scored["targets"]
            experiment["regressions"] = scored["regressions"]
            if scored["verdict"] == "improved":
                proposal_id = deps.file_proposal({
                    "profile_id": source.get("id"),
                    "profile_name": source.get("name"),
                    "knob": candidate.knob,
                    "label": candidate.label,
                    "from_value": candidate.from_value,
                    "to_value": candidate.to_value,
                    "targets": list(candidate.targets),
                    "evidence": {
                        "source_report_id": source_report.get("id"),
                        "clone_report_id": clone_report.get("id"),
                        "verdict": scored["verdict"],
                        "targets": scored["targets"],
                        "rationale": candidate.rationale,
                    },
                })
                experiment["proposal_id"] = proposal_id
                detail["proposals"].append(proposal_id)
            return experiment
        except Exception as exc:
            experiment["note"] = f"{type(exc).__name__}: {exc}"[:200]
            return experiment
        finally:
            if clone is not None:
                try:
                    await deps.burn(clone)
                except Exception:
                    logger.exception("Could not burn evolution clone %s", clone.get("id"))
