"""Local self-update helpers for Git-installed Manager copies."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


class UpdateError(RuntimeError):
    """Raised when the local update cannot continue safely."""


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def display_command(self) -> str:
        return " ".join(self.command)

    @property
    def output(self) -> str:
        return "\n".join(part.strip() for part in (self.stdout, self.stderr) if part.strip()).strip()


@dataclass
class UpdateResult:
    ok: bool
    updated: bool
    before: str | None
    after: str | None
    branch: str | None
    restart_required: bool
    message: str
    log: list[str] = field(default_factory=list)


Runner = Callable[[list[str], Path, int], CommandResult]


def _run_command(command: list[str], cwd: Path, timeout: int) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _run_checked(
    command: list[str],
    *,
    cwd: Path,
    runner: Runner,
    timeout: int,
    log: list[str],
) -> CommandResult:
    result = runner(command, cwd, timeout)
    output = result.output
    log.append(f"$ {result.display_command}" + (f"\n{output}" if output else ""))
    if result.returncode != 0:
        raise UpdateError(output or f"Command failed: {result.display_command}")
    return result


def _npm_executable() -> str:
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise UpdateError("未找到 npm。请先安装 Node.js LTS，并确认 npm 可以在终端运行。")
    return npm


def update_from_git(
    root: Path,
    *,
    runner: Runner = _run_command,
) -> UpdateResult:
    """Pull the current branch and rebuild runtime files when new code arrives."""
    root = root.resolve()
    log: list[str] = []
    if not (root / ".git").exists():
        raise UpdateError("当前不是 Git 安装版，无法在面板里自动升级。请用 git clone 安装，或手动下载新版 ZIP。")

    branch_result = _run_checked(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=root,
        runner=runner,
        timeout=30,
        log=log,
    )
    branch = branch_result.stdout.strip()
    if not branch or branch == "HEAD":
        raise UpdateError("当前 Git 仓库处于 detached HEAD，无法自动判断升级分支。")

    before_result = _run_checked(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=root,
        runner=runner,
        timeout=30,
        log=log,
    )
    before = before_result.stdout.strip() or None

    status_result = _run_checked(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        runner=runner,
        timeout=30,
        log=log,
    )
    dirty = status_result.stdout.strip()
    if dirty:
        raise UpdateError(
            "本地代码有未提交改动，为了避免覆盖你的修改，已停止升级。\n"
            "请先提交、备份或还原这些改动后再升级：\n"
            f"{dirty}"
        )

    pull_result = _run_checked(
        ["git", "pull", "--ff-only"],
        cwd=root,
        runner=runner,
        timeout=180,
        log=log,
    )

    after_result = _run_checked(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=root,
        runner=runner,
        timeout=30,
        log=log,
    )
    after = after_result.stdout.strip() or None
    updated = bool(before and after and before != after)

    if not updated:
        return UpdateResult(
            ok=True,
            updated=False,
            before=before,
            after=after,
            branch=branch,
            restart_required=False,
            message="已经是最新版本，无需升级。",
            log=log,
        )

    requirements = root / "backend" / "requirements.txt"
    frontend_dir = root / "frontend"
    npm = _npm_executable()

    _run_checked(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements)],
        cwd=root,
        runner=runner,
        timeout=600,
        log=log,
    )
    _run_checked([npm, "ci"], cwd=frontend_dir, runner=runner, timeout=600, log=log)
    _run_checked([npm, "run", "build"], cwd=frontend_dir, runner=runner, timeout=300, log=log)

    pull_output = pull_result.output
    return UpdateResult(
        ok=True,
        updated=True,
        before=before,
        after=after,
        branch=branch,
        restart_required=True,
        message=(
            f"已升级到 {after}。请重启 Manager 后使用新版后端。"
            if not pull_output else
            f"已升级到 {after}。请重启 Manager 后使用新版后端。\n{pull_output}"
        ),
        log=log,
    )
