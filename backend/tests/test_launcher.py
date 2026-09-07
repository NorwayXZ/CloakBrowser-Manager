"""Tests for the lightweight native Manager launcher."""

import pytest

import run as launcher


def test_linux_directs_users_to_docker(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Linux 请使用 Docker"):
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


def test_running_manager_is_detected_from_status_api(monkeypatch: pytest.MonkeyPatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"running_count": 0, "profiles_total": 1, "runtime_mode": "native"}'

    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    assert launcher._manager_is_running() is True


def test_other_service_is_not_treated_as_manager(monkeypatch: pytest.MonkeyPatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"status": "ok"}'

    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    assert launcher._manager_is_running() is False
