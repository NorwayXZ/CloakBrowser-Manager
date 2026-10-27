"""Shared test fixtures for backend tests."""

from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Backend modules resolve their data directory at import time. Point it at a
# throwaway folder first so no test can reach the user's real profiles.db —
# code paths such as BrowserManager.stop() write through the module default.
os.environ["CLOAKBROWSER_MANAGER_DATA_DIR"] = tempfile.mkdtemp(prefix="cbm-test-data-")
# Automatic backups copy to ~/CloakBrowser Manager Backups by default; never in tests.
os.environ["CLOAKBROWSER_MANAGER_BACKUP_COPY_DIR"] = tempfile.mkdtemp(prefix="cbm-test-backup-copy-")

# ---------------------------------------------------------------------------
# Mock cloakbrowser BEFORE any backend module is imported.
# browser_manager.py does `from cloakbrowser import launch_persistent_context_async`
# at module level, and main.py imports BrowserManager which triggers it.
# main.py:381 also does `from cloakbrowser.config import CHROMIUM_VERSION`.
# ---------------------------------------------------------------------------

_mock_cloakbrowser = types.ModuleType("cloakbrowser")
_mock_cloakbrowser.launch_persistent_context_async = AsyncMock()  # type: ignore[attr-defined]

_mock_config = types.ModuleType("cloakbrowser.config")
_mock_config.CHROMIUM_VERSION = "0.0.0-test"  # type: ignore[attr-defined]
# browser_manager's darwin launch path does
# `from cloakbrowser.config import binary_supports_maximized_window`; the mock
# must expose it or the macOS CI run ImportErrors (other platforms skip that
# branch via sys.platform). Conservative default: no maximized-window support.
_mock_config.binary_supports_maximized_window = lambda: False  # type: ignore[attr-defined]

sys.modules.setdefault("cloakbrowser", _mock_cloakbrowser)
sys.modules.setdefault("cloakbrowser.config", _mock_config)


from backend import database as db  # noqa: E402
from backend.runtime import RuntimeConfig  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_secret_key(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """Keep the encryption key in a temp dir: never read or create the real
    user's .secret_key (and /data does not exist on CI runners)."""
    from backend import secrets_crypto

    monkeypatch.setattr(secrets_crypto, "DATA_DIR", tmp_path_factory.mktemp("secret-key"))
    secrets_crypto.reset_key_cache()
    yield
    secrets_crypto.reset_key_cache()


@pytest.fixture(autouse=True)
def proxies_look_healthy(monkeypatch: pytest.MonkeyPatch):
    """No test reaches a real proxy: the health check answers "usable";
    the probe's own tests run it against local fake proxies."""
    from backend import browser_manager, main
    from backend.proxy_probe import ProbeResult

    healthy = lambda *_a, **_k: ProbeResult(ok=True, message="ok", stage="done", seconds=0.0)  # noqa: E731
    monkeypatch.setattr(browser_manager, "probe_proxy", healthy)
    monkeypatch.setattr(main, "probe_proxy", healthy)


@pytest.fixture(autouse=True)
def lsof_cannot_tell(monkeypatch: pytest.MonkeyPatch):
    """Launch tests use mock processes, which lsof knows nothing about: answer
    "unknown" so no launch waits for a window; tests of the window logic set
    their own answers."""
    from backend import browser_manager

    monkeypatch.setattr(browser_manager, "profile_files_open", lambda *_a, **_k: None)


@pytest.fixture(autouse=True)
def unknown_host_screen(monkeypatch: pytest.MonkeyPatch):
    """Tests see no real display, so results never depend on the machine's
    screen; tests of the follow-the-display behaviour set one explicitly."""
    from backend import browser_manager, main

    monkeypatch.setattr(browser_manager, "primary_screen_size", lambda: None)
    monkeypatch.setattr(browser_manager, "primary_visible_frame", lambda: None)
    monkeypatch.setattr(main, "primary_screen_size", lambda: None)


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point database module at a temp directory and init schema."""
    db_file = tmp_path / "profiles.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    db.init_db()
    return tmp_path


@pytest.fixture()
def sample_profile(tmp_db: Path):
    """Create and return a sample profile dict."""
    return db.create_profile(name="Test Profile", fingerprint_seed=12345)


@pytest.fixture()
def app_client(tmp_db: Path, monkeypatch: pytest.MonkeyPatch):
    """FastAPI TestClient with mocked DB and browser manager."""
    from backend import main

    # API tests exercise the existing Linux Docker contract on every host OS.
    monkeypatch.setattr(
        main.browser_mgr,
        "runtime",
        RuntimeConfig("linux", "docker", "vnc", tmp_db),
    )
    monkeypatch.setattr(main.browser_mgr.vnc, "enabled", True)

    # Patch lifespan-called methods to avoid host KasmVNC/process requirements.
    monkeypatch.setattr(main.browser_mgr.vnc, "validate_available", MagicMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
    monkeypatch.setattr(main.browser_mgr.vnc, "cleanup_stale", AsyncMock())

    from starlette.testclient import TestClient

    with TestClient(main.app, base_url="http://127.0.0.1:8080") as client:
        yield client
