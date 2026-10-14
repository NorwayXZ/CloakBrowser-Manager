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
    download_url: str | None = None


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


def _check_packaged_app(log: list[str]) -> UpdateResult:
    """DMG/installer builds have no Git checkout: point at the newest release instead.

    Returns ok=True even when the check fails so the browser-kernel check still runs.
    """
    from .desktop_app import app_version, check_for_app_update

    current = app_version()
    try:
        info = check_for_app_update(current)
    except Exception as exc:  # network errors, GitHub rate limits
        log.append(f"检查新版本失败：{exc}")
        return UpdateResult(
            ok=True, updated=False, before=current, after=None, branch=None,
            restart_required=False, log=log,
            message=f"当前版本 {current or '未知'}；暂时无法连接 GitHub 检查新版本，请稍后再试。",
        )
    if info["newer"]:
        message = (
            f"发现新版本 {info['latest']}（当前 {current}）。点击下方链接下载，"
            "打开后把新 App 拖到「应用程序」覆盖旧版即可；画像、Cookie 等数据不受影响。"
        )
    elif info["latest"]:
        message = f"当前版本 {current or '未知'} 已是最新。"
    else:
        message = f"当前版本 {current or '未知'}；GitHub 上还没有发布版本。"
    return UpdateResult(
        ok=True, updated=False, before=current, after=info["latest"], branch=None,
        restart_required=False, log=log, message=message,
        download_url=info["download_url"] if info["newer"] else None,
    )


def update_from_git(
    root: Path,
    *,
    runner: Runner = _run_command,
) -> UpdateResult:
    """Pull the current branch and rebuild runtime files when new code arrives."""
    root = root.resolve()
    log: list[str] = []
    if getattr(sys, "frozen", False):
        return _check_packaged_app(log)
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
    try:
        _run_checked([npm, "ci"], cwd=frontend_dir, runner=runner, timeout=600, log=log)
        _run_checked([npm, "run", "build"], cwd=frontend_dir, runner=runner, timeout=300, log=log)
    except UpdateError:
        # Build/install failed after the code was already updated: roll the
        # repository back to the pre-update commit so the next launch isn't left
        # on a half-updated tree with a broken frontend build.
        log.append(f"升级构建失败，回滚到 {before} ...")
        try:
            _run_checked(
                ["git", "reset", "--hard", before],
                cwd=root,
                runner=runner,
                timeout=120,
                log=log,
            )
        except UpdateError as rollback_err:
            log.append(f"回滚失败：{rollback_err}")
            raise UpdateError(
                "升级后的前端构建失败，且自动回滚失败。请手动执行 "
                f"`git reset --hard {before}` 后重试，或改用干净安装。"
            )
        raise UpdateError(
            "升级后的前端构建失败，已自动回滚到升级前的版本（你仍然可以使用当前版本）。\n"
            "常见原因：Node.js 版本过旧或网络问题导致 npm 构建失败。"
        )

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
