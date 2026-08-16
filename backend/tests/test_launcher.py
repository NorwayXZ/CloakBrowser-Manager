"""Tests for the lightweight native Manager launcher."""

import pytest

import run as launcher


def test_linux_directs_users_to_docker(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="use Docker on Linux"):
        launcher._ensure_environment()


def test_platform_launchers_target_shared_runner():
    assert "run.py" in (launcher.ROOT / "run-windows.bat").read_text()
    assert "python3 run.py" in (launcher.ROOT / "run-macos.sh").read_text()
    assert "run-macos.sh" in (launcher.ROOT / "install-macos.sh").read_text()
    assert "run-windows.bat" in (launcher.ROOT / "install-windows.bat").read_text()
    assert "--uninstall" in (launcher.ROOT / "uninstall-macos.sh").read_text()
    assert "--uninstall" in (launcher.ROOT / "uninstall-windows.bat").read_text()


def test_cleanup_installation_preserves_profile_data(tmp_path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "repo"
    frontend = root / "frontend"
    venv_dir = root / ".venv"
    data_dir = tmp_path / "CloakBrowser Manager"

    (frontend / "node_modules").mkdir(parents=True)
    (frontend / "dist").mkdir()
    (frontend / ".vite").mkdir()
    (frontend / ".cache").mkdir()
    venv_dir.mkdir(parents=True)
    data_dir.mkdir()

    monkeypatch.setattr(launcher, "ROOT", root)
    monkeypatch.setattr(launcher, "VENV_DIR", venv_dir)
    monkeypatch.setattr(launcher, "FRONTEND_DIR", frontend)
    monkeypatch.setattr(launcher, "_manager_data_dir", lambda: data_dir)

    launcher._cleanup_installation(purge_data=False)

    assert not venv_dir.exists()
    assert not (frontend / "node_modules").exists()
    assert not (frontend / "dist").exists()
    assert data_dir.exists()


def test_cleanup_installation_can_purge_profile_data(tmp_path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "repo"
    frontend = root / "frontend"
    venv_dir = root / ".venv"
    data_dir = tmp_path / "CloakBrowser Manager"

    (frontend / "node_modules").mkdir(parents=True)
    venv_dir.mkdir(parents=True)
    data_dir.mkdir()

    monkeypatch.setattr(launcher, "ROOT", root)
    monkeypatch.setattr(launcher, "VENV_DIR", venv_dir)
    monkeypatch.setattr(launcher, "FRONTEND_DIR", frontend)
    monkeypatch.setattr(launcher, "_manager_data_dir", lambda: data_dir)

    launcher._cleanup_installation(purge_data=True)

    assert not venv_dir.exists()
    assert not data_dir.exists()


def test_frontend_source_timestamp_is_available():
    source_files = [
        path for path in (launcher.FRONTEND_DIR / "src").rglob("*") if path.is_file()
    ]
    assert source_files
    assert max(path.stat().st_mtime for path in source_files) > 0
