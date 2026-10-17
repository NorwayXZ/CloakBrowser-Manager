"""Runs one one-click update in the background and reports its progress."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import self_update

logger = logging.getLogger(__name__)

PHASE_LABELS = {
    "idle": "",
    "checking": "正在检查新版本",
    "downloading": "正在下载新版本",
    "backing_up": "正在做更新前备份",
    "preparing": "正在准备安装",
    "restarting": "正在安装，应用会自动重启",
    "failed": "更新没有完成",
}


@dataclass
class UpdateEnv:
    """Everything the job touches on the host, injectable for tests."""

    data_dir: Path
    current_version: str | None
    port: int
    platform: str  # "darwin" | "win32"
    keyword: str
    fetch_release: Callable[[], dict | None]
    backup: Callable[[], object]
    request_exit: Callable[[], bool]
    running_app: Path | None = None
    pid: int = field(default_factory=os.getpid)
    download: Callable[..., Path] = self_update.download_verified
    stage_macos: Callable[..., Path] = self_update.macos_stage_app
    launch: Callable[[list[str]], None] = self_update.launch_detached


class UpdateJob:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict = {"phase": "idle"}

    def snapshot(self) -> dict:
        with self._lock:
            state = dict(self._state)
        state["label"] = PHASE_LABELS.get(state["phase"], "")
        return state

    def _set(self, **changes) -> None:
        with self._lock:
            self._state.update(changes)

    @property
    def busy(self) -> bool:
        return self.snapshot()["phase"] not in {"idle", "failed"}

    def start(self, env: UpdateEnv) -> bool:
        with self._lock:
            if self._state["phase"] not in {"idle", "failed"}:
                return False
            self._state = {"phase": "checking"}
        threading.Thread(target=self._run, args=(env,), name="self-update", daemon=True).start()
        return True

    def _run(self, env: UpdateEnv) -> None:
        try:
            self.run(env)
        except self_update.UpdateError as exc:
            self._set(phase="failed", error=str(exc))
        except Exception as exc:  # network, disk, unexpected
            logger.exception("One-click update failed")
            self._set(phase="failed", error=f"更新失败：{exc}")

    def run(self, env: UpdateEnv) -> None:
        release = env.fetch_release()
        if not release:
            raise self_update.UpdateError("GitHub 上还没有发布版本。")
        plan = self_update.plan_update(release, env.keyword)
        from .desktop_app import is_newer

        if not is_newer(plan.version, env.current_version):
            raise self_update.UpdateError(f"当前版本 {env.current_version} 已是最新。")
        self._set(phase="downloading", target=plan.version, done=0, total=plan.size)

        work = self_update.updates_dir(env.data_dir)
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        package = env.download(plan, work, progress=lambda done, total: self._set(done=done, total=total))

        self._set(phase="backing_up")
        env.backup()

        self._set(phase="preparing")
        log_path = work / self_update.SCRIPT_LOG_NAME
        if env.platform == "darwin":
            if env.running_app is None:
                raise self_update.UpdateError("找不到正在运行的应用，请手动下载安装。")
            target = self_update.macos_install_target(env.running_app)
            staged = env.stage_macos(package, work, target, plan.version)
            script = work / "swap.sh"
            script.write_text(self_update.macos_swap_script(
                pid=env.pid,
                target_app=target,
                staged_app=staged,
                backup_app=target.with_name(f".{target.stem}.previous.app"),
                version=plan.version,
                port=env.port,
                log_path=log_path,
            ))
            script.chmod(0o700)
            command = ["/bin/sh", str(script)]
        elif env.platform == "win32":
            script = work / "install.cmd"
            script.write_text(self_update.windows_install_script(pid=env.pid, installer=package, log_path=log_path))
            command = ["cmd.exe", "/c", str(script)]
        else:
            raise self_update.UpdateError("这个系统不支持一键更新。")

        self_update.write_pending(env.data_dir, from_version=env.current_version, to_version=plan.version)
        env.launch(command)
        self._set(phase="restarting")
        if not env.request_exit():
            raise self_update.UpdateError("没法让应用自动退出，请从菜单栏/托盘退出，更新会接着完成。")


def platform_name() -> str:
    return "darwin" if sys.platform == "darwin" else "win32" if sys.platform == "win32" else sys.platform
