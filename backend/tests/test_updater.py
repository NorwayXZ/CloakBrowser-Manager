from __future__ import annotations

from pathlib import Path

import pytest

from backend.updater import CommandResult, UpdateError, update_from_git


def test_update_from_git_rebuilds_when_commit_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").write_text("")
    (tmp_path / "frontend").mkdir()
    monkeypatch.setattr("backend.updater.shutil.which", lambda _name: "npm")

    rev_calls = 0
    commands: list[list[str]] = []

    def runner(command: list[str], cwd: Path, timeout: int) -> CommandResult:
        nonlocal rev_calls
        commands.append(command)
        if command[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return CommandResult(command, 0, stdout="main\n")
        if command[:3] == ["git", "rev-parse", "--short"]:
            rev_calls += 1
            return CommandResult(command, 0, stdout="old123\n" if rev_calls == 1 else "new456\n")
        if command[:3] == ["git", "status", "--porcelain"]:
            return CommandResult(command, 0, stdout="")
        if command[:2] == ["git", "pull"]:
            return CommandResult(command, 0, stdout="Updating old123..new456\nFast-forward\n")
        return CommandResult(command, 0, stdout="ok\n")

    result = update_from_git(tmp_path, runner=runner)

    assert result.ok is True
    assert result.updated is True
    assert result.restart_required is True
    assert result.before == "old123"
    assert result.after == "new456"
    assert ["npm", "ci"] in commands
    assert ["npm", "run", "build"] in commands


def test_update_from_git_reports_latest_without_rebuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr("backend.updater.shutil.which", lambda _name: "npm")
    commands: list[list[str]] = []

    def runner(command: list[str], cwd: Path, timeout: int) -> CommandResult:
        commands.append(command)
        if command[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return CommandResult(command, 0, stdout="main\n")
        if command[:3] == ["git", "rev-parse", "--short"]:
            return CommandResult(command, 0, stdout="same123\n")
        if command[:3] == ["git", "status", "--porcelain"]:
            return CommandResult(command, 0, stdout="")
        if command[:2] == ["git", "pull"]:
            return CommandResult(command, 0, stdout="Already up to date.\n")
        return CommandResult(command, 0, stdout="ok\n")

    result = update_from_git(tmp_path, runner=runner)

    assert result.updated is False
    assert result.restart_required is False
    assert result.message == "已经是最新版本，无需升级。"
    assert ["npm", "ci"] not in commands


def test_update_from_git_stops_when_worktree_is_dirty(tmp_path: Path):
    (tmp_path / ".git").mkdir()

    def runner(command: list[str], cwd: Path, timeout: int) -> CommandResult:
        if command[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return CommandResult(command, 0, stdout="main\n")
        if command[:3] == ["git", "rev-parse", "--short"]:
            return CommandResult(command, 0, stdout="abc123\n")
        if command[:3] == ["git", "status", "--porcelain"]:
            return CommandResult(command, 0, stdout=" M frontend/src/App.tsx\n")
        return CommandResult(command, 0)

    with pytest.raises(UpdateError, match="本地代码有未提交改动"):
        update_from_git(tmp_path, runner=runner)


def test_update_from_git_requires_git_install(tmp_path: Path):
    with pytest.raises(UpdateError, match="不是 Git 安装版"):
        update_from_git(tmp_path)
